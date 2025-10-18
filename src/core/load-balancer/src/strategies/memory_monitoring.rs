use std::collections::HashMap;
use std::sync::{Arc};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use parking_lot::RwLock;
use rand::Rng;
use serde::Deserialize;
use tokio::task::JoinHandle;
use tokio::time::Interval;

use super::strategy::ServerSelectionStrategy;

#[derive(Debug, Clone, Copy, Default)]
struct ServerMetrics {
    memory_current_bytes: f64,
    disk_read_bytes_per_sec: f64,
    timestamp_unix: i64,
}

#[derive(Debug, Clone, Copy, Default)]
struct ServerScore {
    score: f64,
}

#[derive(Debug, Deserialize)]
struct MetricsPayload {
    server_socket: String,
    memory_current_bytes: u64,
    disk_read_bytes_per_sec: f64,
    timestamp_unix: i64,
}

pub struct MemoryMonitoringStrategy {
    metrics: Arc<RwLock<HashMap<String, ServerMetrics>>>,
    scores: Arc<RwLock<HashMap<String, ServerScore>>>,
    _mqtt_handle: JoinHandle<()>,
    _score_handle: JoinHandle<()>,
}

impl MemoryMonitoringStrategy {
    pub fn new(broker_host: String, broker_port: u16) -> Self {
        let metrics = Arc::new(RwLock::new(HashMap::new()));
        let scores = Arc::new(RwLock::new(HashMap::new()));

        let metrics_clone = Arc::clone(&metrics);
        let mqtt_handle = tokio::spawn(async move {
            // Use rumqttc for a simple MQTT client
            let mut mqttoptions = rumqttc::MqttOptions::new(
                format!("lb-{}", rand::thread_rng().gen::<u64>()),
                broker_host,
                broker_port,
            );
            mqttoptions.set_keep_alive(Duration::from_secs(10));

            let (mut client, mut eventloop) = rumqttc::AsyncClient::new(mqttoptions, 10);

            // Connect and subscribe
            if let Err(e) = client.subscribe("loadbalancer/metrics", rumqttc::QoS::AtLeastOnce).await {
                eprintln!("Failed to subscribe to metrics topic: {}", e);
                return;
            } else {
                println!("Subscribed to MQTT topic 'loadbalancer/metrics'");
            }

            loop {
                match eventloop.poll().await {
                    Ok(rumqttc::Event::Incoming(rumqttc::Packet::Publish(p))) => {
                        if let Ok(payload_str) = std::str::from_utf8(&p.payload) {
                            if let Ok(payload) = serde_json::from_str::<MetricsPayload>(payload_str) {
                                let mut write_guard = metrics_clone.write();
                                write_guard.insert(
                                    payload.server_socket.clone(),
                                    ServerMetrics {
                                        memory_current_bytes: payload.memory_current_bytes as f64,
                                        disk_read_bytes_per_sec: payload.disk_read_bytes_per_sec,
                                        timestamp_unix: payload.timestamp_unix,
                                    },
                                );
                                // Log a concise message for received metrics
                                let mem_mb = (payload.memory_current_bytes as f64) / (1024.0 * 1024.0);
                                let disk_kb = payload.disk_read_bytes_per_sec / 1024.0;
                                println!(
                                    "Metrics received: server={} mem={:.2}MB disk={:.2}KB/s ts={}",
                                    payload.server_socket,
                                    mem_mb,
                                    disk_kb,
                                    payload.timestamp_unix
                                );
                            }
                        }
                    }
                    Ok(_) => {}
                    Err(e) => {
                        eprintln!("MQTT event loop error: {}", e);
                        // Backoff a bit before retrying
                        tokio::time::sleep(Duration::from_secs(1)).await;
                    }
                }
            }
        });

        let metrics_clone2 = Arc::clone(&metrics);
        let scores_clone = Arc::clone(&scores);
        let score_handle = tokio::spawn(async move {
            let mut ticker: Interval = tokio::time::interval(Duration::from_millis(500));
            loop {
                ticker.tick().await;

                // Compute simple inverse-usage score
                let now_unix = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs() as i64;

                let snapshot: HashMap<String, ServerMetrics> = {
                    let read_guard = metrics_clone2.read();
                    read_guard.clone()
                };

                let mut new_scores: HashMap<String, ServerScore> = HashMap::new();
                // Heuristic: newer samples weigh higher; lower mem and disk => higher score
                for (server, m) in snapshot.into_iter() {
                    let staleness = (now_unix - m.timestamp_unix).max(0) as f64;
                    let freshness_weight = (1.0 / (1.0 + staleness)).clamp(0.0, 1.0);

                    // Avoid division by zero by adding small epsilon; scale to MB and KB/s to keep numbers reasonable
                    let mem_mb = m.memory_current_bytes / (1024.0 * 1024.0);
                    let disk_kb = m.disk_read_bytes_per_sec / 1024.0;

                    let raw = 1000.0 / (1.0 + mem_mb) + 500.0 / (1.0 + disk_kb);
                    let score = raw * freshness_weight;

                    new_scores.insert(server, ServerScore { score });
                }

                let mut write_scores = scores_clone.write();
                *write_scores = new_scores;
            }
        });

        Self {
            metrics,
            scores,
            _mqtt_handle: mqtt_handle,
            _score_handle: score_handle,
        }
    }

    pub fn get_scores_snapshot(&self) -> HashMap<String, f64> {
        let read_guard = self.scores.read();
        read_guard
            .iter()
            .map(|(k, v)| (k.clone(), v.score))
            .collect()
    }
}

impl ServerSelectionStrategy for MemoryMonitoringStrategy {
    fn pick_server(&self, servers: &[String]) -> Option<String> {
        if servers.is_empty() {
            return None;
        }

        // Prefer server with highest score; if missing scores, fallback to random choice among them
        let scores_snapshot = self.get_scores_snapshot();
        let mut best: Option<(String, f64)> = None;

        for s in servers {
            let score = scores_snapshot.get(s).copied().unwrap_or(0.0);
            match best {
                None => best = Some((s.clone(), score)),
                Some((_, best_score)) if score > best_score => best = Some((s.clone(), score)),
                _ => {}
            }
        }

        best.map(|(s, _)| s)
    }

    fn debug_snapshot(&self) -> Option<String> {
        let scores = self.get_scores_snapshot();
        if scores.is_empty() {
            return Some("scores: <empty>".to_string());
        }
        let mut items: Vec<(String, f64)> = scores.into_iter().collect();
        items.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        let s = items
            .into_iter()
            .map(|(k, v)| format!("{}={:.2}", k, v))
            .collect::<Vec<_>>()
            .join(", ");
        Some(format!("scores: [{}]", s))
    }
}


