use crate::strategy::ServerSelectionStrategy;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::Mutex;

pub struct LoadBalancer {
    servers: Vec<String>,
    strategy: Arc<dyn ServerSelectionStrategy>,
    request_counter: Arc<AtomicU64>,
    per_server_connection_counts: Arc<Mutex<HashMap<String, u64>>>,
}

impl LoadBalancer {
    pub fn new(servers: Vec<String>, strategy: Arc<dyn ServerSelectionStrategy>) -> Self {
        let mut counts = HashMap::new();
        for s in &servers {
            counts.insert(s.clone(), 0u64);
        }

        Self { 
            servers, 
            strategy,
            request_counter: Arc::new(AtomicU64::new(0)),
            per_server_connection_counts: Arc::new(Mutex::new(counts)),
        }
    }

    pub async fn start(&self, bind_address: &str) -> Result<(), Box<dyn std::error::Error>> {
        let listener = TcpListener::bind(bind_address).await?;
        println!("Load balancer listening on {}", bind_address);
        println!("Available servers: {:?}", self.servers);

        let metrics_counter = Arc::clone(&self.request_counter);
        let per_server_counts = Arc::clone(&self.per_server_connection_counts);
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(30));
            loop {
                interval.tick().await;
                let total_requests = metrics_counter.load(Ordering::Relaxed);
                println!("[METRICS] Total requests processed: {}", total_requests);
                if let Ok(map) = per_server_counts.try_lock() {
                    println!("[METRICS] Per-server connection counts:");
                    for (server, count) in map.iter() {
                        println!("    {} => {} connections", server, count);
                    }
                }
            }
        });

        loop {
            let (client_stream, client_addr) = listener.accept().await?;
            println!("New TCP connection from: {}", client_addr);

            let servers = self.servers.clone();
            let strategy = Arc::clone(&self.strategy);
            let request_counter = Arc::clone(&self.request_counter);
            let per_server_counts = Arc::clone(&self.per_server_connection_counts);

            tokio::spawn(async move {
                if let Err(e) = handle_connection(
                    client_stream, 
                    servers, 
                    strategy, 
                    request_counter, 
                    per_server_counts,
                    client_addr
                ).await {
                    eprintln!("Error handling connection from {}: {}", client_addr, e);
                }
            });
        }
    }
}

async fn handle_connection(
    client_stream: TcpStream,
    servers: Vec<String>,
    strategy: Arc<dyn ServerSelectionStrategy>,
    request_counter: Arc<AtomicU64>,
    per_server_counts: Arc<Mutex<HashMap<String, u64>>>,
    client_addr: std::net::SocketAddr,
) -> Result<(), Box<dyn std::error::Error>> {
    let server_addr = strategy
        .pick_server(&servers)
        .ok_or("No available servers")?;

    println!("[{}] Forwarding connection to: {}", client_addr, server_addr);

    // Increment per-server connection counter
    {
        let mut map = per_server_counts.lock().await;
        if let Some(entry) = map.get_mut(&server_addr) {
            *entry += 1;
        } else {
            map.insert(server_addr.clone(), 1);
        }
    }

    let server_stream = TcpStream::connect(&server_addr).await?;

    let (mut client_read, mut client_write) = client_stream.into_split();
    let (mut server_read, mut server_write) = server_stream.into_split();

    let request_counter_c2s = Arc::clone(&request_counter);
    let client_addr_c2s = client_addr;
    let server_addr_c2s = server_addr.clone();
    let server_addr_s2c = server_addr.clone();

    let client_to_server = tokio::spawn(async move {
        let mut buffer = vec![0; 8192];
        let mut http_buffer = Vec::new();
        let mut in_request = false;
        let mut headers_complete = false;
        let mut request_path: Option<String> = None;
        let mut host_header: Option<String> = None;
        
        loop {
            match client_read.read(&mut buffer).await {
                Ok(0) => break,
                Ok(n) => {
                    let data = &buffer[..n];
                    
                    if !in_request && (data.starts_with(b"GET ") || 
                                      data.starts_with(b"POST ") || 
                                      data.starts_with(b"PUT ") || 
                                      data.starts_with(b"DELETE ") || 
                                      data.starts_with(b"HEAD ") || 
                                      data.starts_with(b"OPTIONS ") ||
                                      data.starts_with(b"PATCH ")) {
                        in_request = true;
                        http_buffer.clear();
                        http_buffer.extend_from_slice(data);
                        
                        let req_id = request_counter_c2s.fetch_add(1, Ordering::Relaxed) + 1;
                        
                        if let Some(first_line_end) = data.iter().position(|&b| b == b'\n') {
                            let request_line = String::from_utf8_lossy(&data[..first_line_end]).trim().to_string();
                            let parts: Vec<&str> = request_line.split_whitespace().collect();
                            if parts.len() >= 2 {
                                request_path = Some(parts[1].to_string());
                                println!("[REQ:{}] {} {} {} -> {}", 
                                        req_id, 
                                        client_addr_c2s,
                                        parts[0], // Method
                                        parts[1], // Path
                                        server_addr_c2s);
                            }
                        }
                    } else if in_request {
                        http_buffer.extend_from_slice(data);
                    }
                    
                    if in_request && !headers_complete {
                        if http_buffer.windows(4).any(|w| w == b"\r\n\r\n") {
                            headers_complete = true;
                            if let Ok(text) = String::from_utf8(http_buffer.clone()) {
                                for line in text.lines() {
                                    if let Some(rest) = line.strip_prefix("Host:") {
                                        host_header = Some(rest.trim().to_string());
                                        break;
                                    }
                                }
                            }
                            println!("[HDR] {} Host={} Path={}", 
                                    client_addr_c2s,
                                    host_header.as_deref().unwrap_or("<none>"),
                                    request_path.as_deref().unwrap_or("<unknown>"));
                        }
                    }

                    if in_request && http_buffer.windows(4).any(|w| w == b"\r\n\r\n") {
                        in_request = false;
                    }
                    
                    if server_write.write_all(data).await.is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        let _ = server_write.shutdown().await;
        println!("[{}] Client to server stream closed", client_addr_c2s);
    });

    let server_to_client = tokio::spawn(async move {
        let mut buffer = vec![0; 8192];
        let mut response_started = false;
        
        loop {
            match server_read.read(&mut buffer).await {
                Ok(0) => break,
                Ok(n) => {
                    let data = &buffer[..n];
                    
                    if !response_started && data.starts_with(b"HTTP/") {
                        response_started = true;
                        if let Some(first_line_end) = data.iter().position(|&b| b == b'\n') {
                            let status_line = String::from_utf8_lossy(&data[..first_line_end]).trim().to_string();
                            let parts: Vec<&str> = status_line.split_whitespace().collect();
                            if parts.len() >= 2 {
                                println!("[RES] {} <- {} ({})", 
                                        client_addr,
                                        server_addr_s2c, 
                                        parts[1]); // Status code
                            }
                        }
                    }
                    
                    if client_write.write_all(data).await.is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        let _ = client_write.shutdown().await;
        println!("[{}] Server to client stream closed", client_addr);
    });

    tokio::select! {
        _ = client_to_server => {
            println!("[{}] Client to server task completed", client_addr);
        }
        _ = server_to_client => {
            println!("[{}] Server to client task completed", client_addr);
        }
    }

    Ok(())
}
