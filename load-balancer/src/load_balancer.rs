use crate::strategy::ServerSelectionStrategy;
use std::sync::Arc;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};

pub struct LoadBalancer {
    servers: Vec<String>,
    strategy: Arc<dyn ServerSelectionStrategy>,
}

impl LoadBalancer {
    pub fn new(servers: Vec<String>, strategy: Arc<dyn ServerSelectionStrategy>) -> Self {
        Self { servers, strategy }
    }

    pub async fn start(&self, bind_address: &str) -> Result<(), Box<dyn std::error::Error>> {
        let listener = TcpListener::bind(bind_address).await?;
        println!("Load balancer listening on {}", bind_address);
        println!("Available servers: {:?}", self.servers);

        loop {
            let (client_stream, client_addr) = listener.accept().await?;
            println!("New connection from: {}", client_addr);

            let servers = self.servers.clone();
            let strategy = Arc::clone(&self.strategy);

            tokio::spawn(async move {
                if let Err(e) = handle_connection(client_stream, servers, strategy).await {
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
) -> Result<(), Box<dyn std::error::Error>> {
    // Pick a server using the strategy
    let server_addr = strategy
        .pick_server(&servers)
        .ok_or("No available servers")?;

    println!("Forwarding connection to: {}", server_addr);

    // Connect to the selected server
    let server_stream = TcpStream::connect(&server_addr).await?;

    // Split both streams into read and write halves
    let (mut client_read, mut client_write) = client_stream.into_split();
    let (mut server_read, mut server_write) = server_stream.into_split();

    // Spawn tasks to forward data in both directions
    let client_to_server = tokio::spawn(async move {
        let mut buffer = vec![0; 4096];
        loop {
            match client_read.read(&mut buffer).await {
                Ok(0) => break, // Connection closed
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
        let mut buffer = vec![0; 4096];
        loop {
            match server_read.read(&mut buffer).await {
                Ok(0) => break, // Connection closed
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

    // Wait for either direction to close
    tokio::select! {
        _ = client_to_server => {
            println!("Client to server connection closed");
        }
        _ = server_to_client => {
            println!("Server to client connection closed");
        }
    }

    Ok(())
}
