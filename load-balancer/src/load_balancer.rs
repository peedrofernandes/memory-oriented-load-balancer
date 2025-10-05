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

        // Metrics logging removed to reduce per-connection overhead

        loop {
            let (client_stream, client_addr) = listener.accept().await?;

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
    _client_addr: std::net::SocketAddr,
) -> Result<(), Box<dyn std::error::Error>> {
    let server_addr = strategy
        .pick_server(&servers)
        .ok_or("No available servers")?;

    // Forward connection to selected backend server

    // Per-server connection accounting removed to reduce overhead

    let server_stream = TcpStream::connect(&server_addr).await?;

    let (mut client_read, mut client_write) = client_stream.into_split();
    let (mut server_read, mut server_write) = server_stream.into_split();

    let _request_counter_c2s = Arc::clone(&request_counter);

    let client_to_server = tokio::spawn(async move {
        let mut buffer = vec![0; 16384];
        loop {
            match client_read.read(&mut buffer).await {
                Ok(0) => break,
                Ok(n) => {
                    if server_write.write_all(&buffer[..n]).await.is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        let _ = server_write.shutdown().await;
    });

    let server_to_client = tokio::spawn(async move {
        let mut buffer = vec![0; 16384];
        loop {
            match server_read.read(&mut buffer).await {
                Ok(0) => break,
                Ok(n) => {
                    if client_write.write_all(&buffer[..n]).await.is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        let _ = client_write.shutdown().await;
    });

    tokio::select! { _ = client_to_server => {}, _ = server_to_client => {} }

    Ok(())
}
