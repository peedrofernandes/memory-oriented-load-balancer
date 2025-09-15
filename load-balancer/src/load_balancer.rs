use crate::strategy::ServerSelectionStrategy;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

pub struct LoadBalancer {
    servers: Vec<String>,
    strategy: Arc<dyn ServerSelectionStrategy>,
    request_counter: Arc<AtomicU64>,
}

impl LoadBalancer {
    pub fn new(servers: Vec<String>, strategy: Arc<dyn ServerSelectionStrategy>) -> Self {
        Self { 
            servers, 
            strategy,
            request_counter: Arc::new(AtomicU64::new(0)),
        }
    }

    pub async fn start(&self, bind_address: &str) -> Result<(), Box<dyn std::error::Error>> {
        let listener = TcpListener::bind(bind_address).await?;
        println!("Load balancer listening on {}", bind_address);
        println!("Available servers: {:?}", self.servers);

        // Start metrics logging task
        let metrics_counter = Arc::clone(&self.request_counter);
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(30));
            loop {
                interval.tick().await;
                let total_requests = metrics_counter.load(Ordering::Relaxed);
                println!("[METRICS] Total requests processed: {}", total_requests);
            }
        });

        loop {
            let (client_stream, client_addr) = listener.accept().await?;
            println!("New TCP connection from: {}", client_addr);

            let servers = self.servers.clone();
            let strategy = Arc::clone(&self.strategy);
            let request_counter = Arc::clone(&self.request_counter);

            tokio::spawn(async move {
                if let Err(e) = handle_connection(client_stream, servers, strategy, request_counter, client_addr).await {
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
    client_addr: std::net::SocketAddr,
) -> Result<(), Box<dyn std::error::Error>> {
    // Pick a server using the strategy
    let server_addr = strategy
        .pick_server(&servers)
        .ok_or("No available servers")?;

    println!("[{}] Forwarding connection to: {}", client_addr, server_addr);

    // Connect to the selected server
    let server_stream = TcpStream::connect(&server_addr).await?;

    // Split both streams into read and write halves
    let (mut client_read, mut client_write) = client_stream.into_split();
    let (mut server_read, mut server_write) = server_stream.into_split();

    // Clone the request counter for use in the spawned tasks
    let request_counter_c2s = Arc::clone(&request_counter);
    let client_addr_c2s = client_addr;
    let server_addr_c2s = server_addr.clone();
    let server_addr_s2c = server_addr.clone();

    // Spawn tasks to forward data in both directions
    let client_to_server = tokio::spawn(async move {
        let mut buffer = vec![0; 8192]; // Increased buffer size for HTTP headers
        let mut http_buffer = Vec::new();
        let mut in_request = false;
        
        loop {
            match client_read.read(&mut buffer).await {
                Ok(0) => break, // Connection closed
                Ok(n) => {
                    // Check if this looks like an HTTP request start
                    let data = &buffer[..n];
                    
                    // Look for HTTP request methods at the beginning of new requests
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
                        
                        // Log the request immediately for quick feedback
                        let req_id = request_counter_c2s.fetch_add(1, Ordering::Relaxed) + 1;
                        
                        // Try to extract method and path from the first line
                        if let Some(first_line_end) = data.iter().position(|&b| b == b'\n') {
                            let request_line = String::from_utf8_lossy(&data[..first_line_end]).trim().to_string();
                            let parts: Vec<&str> = request_line.split_whitespace().collect();
                            if parts.len() >= 2 {
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
                    
                    // Check if we've reached the end of headers (double CRLF)
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
                Ok(0) => break, // Connection closed
                Ok(n) => {
                    let data = &buffer[..n];
                    
                    // Log response status if this is the start of an HTTP response
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

    // Wait for either direction to close
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
