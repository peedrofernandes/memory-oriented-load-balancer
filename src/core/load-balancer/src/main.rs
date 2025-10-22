use load_balancer::{LoadBalancer, ServerSelectionStrategy};
use load_balancer::strategies::round_robin::RoundRobinStrategy;
use load_balancer::strategies::random::RandomStrategy;
use load_balancer::strategies::memory_monitoring::MemoryMonitoringStrategy;
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

    // MQTT broker location from env, fallback to nanomq-broker:1883 inside docker network.
    // Used by memory-monitoring strategy; ignored by others.
    let broker_host = std::env::var("MQTT_BROKER_HOST").unwrap_or_else(|_| "nanomq-broker".to_string());
    let broker_port: u16 = std::env::var("MQTT_BROKER_PORT").ok().and_then(|s| s.parse().ok()).unwrap_or(1883);
    let strategy: Arc<dyn ServerSelectionStrategy> = Arc::new(RoundRobinStrategy::new());

    let load_balancer = LoadBalancer::new(servers, strategy);
    
    println!("Starting HTTP Load Balancer...");
    load_balancer.start(bind_address).await?;

    Ok(())
}
