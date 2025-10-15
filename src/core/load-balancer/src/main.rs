use load_balancer::{LoadBalancer, ServerSelectionStrategy};
use load_balancer::strategy::RoundRobinStrategy;
use std::sync::Arc;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let bind_address = "0.0.0.0:8080";
    let servers = vec![
        "mpeg-dash-processor-1:8080".to_string(),
        "mpeg-dash-processor-2:8080".to_string(),
        "mpeg-dash-processor-3:8080".to_string(),
        "mpeg-dash-processor-4:8080".to_string(),
        "mpeg-dash-processor-5:8080".to_string(),
        "mpeg-dash-processor-6:8080".to_string(),
        "mpeg-dash-processor-7:8080".to_string(),
        "mpeg-dash-processor-8:8080".to_string(),
    ];

    let strategy: Arc<dyn ServerSelectionStrategy> = Arc::new(RoundRobinStrategy::new());

    let load_balancer = LoadBalancer::new(servers, strategy);
    
    println!("Starting TCP Load Balancer...");
    load_balancer.start(bind_address).await?;

    Ok(())
}
