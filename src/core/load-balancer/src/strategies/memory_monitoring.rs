use std::collections::HashMap;
use std::sync::{Arc};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use parking_lot::RwLock;
use rand::Rng;
use serde::Deserialize;
use tokio::task::JoinHandle;

use super::strategy::ServerSelectionStrategy;

#[derive(Debug, Clone, Copy, Default)]
struct ServerInfo {
    // Stores LMi, LDi, Ti for server i
    lmi: f64,
    ldi: f64,
    ti: i64,
}

#[derive(Debug, Clone, Copy, Default, Deserialize)]
struct AbsoluteValues {
    memory_current_bytes: u64,
    disk_read_bytes_per_sec: f64,
}

#[derive(Debug, Clone, Copy, Default, Deserialize)]
struct NormalizedValues {
    #[serde(rename = "memory_current_bytes")] // publisher uses this name for normalized memory
    memory_current_consumption: f64,
    #[serde(rename = "disk_read_bytes_per_sec")] // publisher uses this name for normalized disk
    disk_read_consumption: f64,
}

#[derive(Debug, Deserialize)]
struct MetricsPayload {
    server_socket: String,
    absolute_values: AbsoluteValues,
    normalized_values: NormalizedValues,
    timestamp_unix: i64,
}

pub struct MemoryMonitoringStrategy {
    servers_info_map: Arc<RwLock<HashMap<String, ServerInfo>>>,
    servers_li_map: Arc<RwLock<HashMap<String, f64>>>,
    servers_probability_map: Arc<RwLock<HashMap<String, f64>>>,
    r: Arc<AtomicU64>,
    _mqtt_handle: JoinHandle<()>,
}

impl MemoryMonitoringStrategy {
    pub fn new(broker_host: String, broker_port: u16) -> Self {
        let servers_info_map = Arc::new(RwLock::new(HashMap::new()));
        let servers_li_map = Arc::new(RwLock::new(HashMap::new()));
        let servers_probability_map = Arc::new(RwLock::new(HashMap::new()));
        let r = Arc::new(AtomicU64::new(0));

        let servers_info_map_clone = Arc::clone(&servers_info_map);
        let servers_li_map_clone = Arc::clone(&servers_li_map);
        let servers_probability_map_clone = Arc::clone(&servers_probability_map);
        let r_clone = Arc::clone(&r);

        let mqtt_handle = tokio::spawn(async move {
            let mut mqttoptions = rumqttc::MqttOptions::new(
                format!("lb-{}", rand::thread_rng().gen::<u64>()),
                broker_host,
                broker_port,
            );
            mqttoptions.set_keep_alive(Duration::from_secs(10));

            let (client, mut eventloop) = rumqttc::AsyncClient::new(mqttoptions, 10);

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
                                // Update servers_info_map with new LMi, LDi, Ti
                                {
                                    let mut info_guard = servers_info_map_clone.write();
                                    info_guard.insert(
                                        payload.server_socket.clone(),
                                        ServerInfo {
                                            lmi: payload.normalized_values.memory_current_consumption,
                                            ldi: payload.normalized_values.disk_read_consumption,
                                            ti: payload.timestamp_unix,
                                        },
                                    );
                                }

                                // Compute global aggregates and update Li and Pi
                                let (t_m, t_d, n, t): (f64, f64, usize, f64) = {
                                    let read_guard = servers_info_map_clone.read();
                                    let n = read_guard.len();
                                    if n == 0 {
                                        (0.0, 0.0, 0, 0.0)
                                    } else {
                                        let mut sum_lmi = 0.0f64;
                                        let mut sum_ldi = 0.0f64;
                                        let mut sum_time = 0.0f64;
                                        let now_ts: i64 = SystemTime::now()
                                            .duration_since(UNIX_EPOCH)
                                            .unwrap_or_default()
                                            .as_secs() as i64;
                                        for (_k, v) in read_guard.iter() {
                                            sum_lmi += v.lmi;
                                            sum_ldi += v.ldi;
                                            let delta = (now_ts - v.ti) as f64;
                                            sum_time += delta.max(0.0);
                                        }
                                        let t_m = sum_lmi / n as f64;
                                        let t_d = sum_ldi / n as f64;
                                        let t = sum_time / n as f64;
                                        (t_m, t_d, n, t)
                                    }
                                };

                                // CM and CD with safe fallback if TM + TD == 0
                                let denom = t_m + t_d;
                                let (c_m, c_d) = if denom > 0.0 {
                                    (t_m / denom, t_d / denom)
                                } else {
                                    (0.5, 0.5)
                                };

                                // Compute Li for each server and update servers_li_map
                                let l_tot: f64 = {
                                    let info_guard = servers_info_map_clone.read();
                                    let mut li_guard = servers_li_map_clone.write();
                                    let mut sum = 0.0f64;
                                    for (k, v) in info_guard.iter() {
                                        let l_i = c_m * v.lmi + c_d * v.ldi; // Li = CM * LMi + CD * LDi
                                        li_guard.insert(k.clone(), l_i);
                                        sum += l_i;
                                    }
                                    sum
                                };

                                // Compute arriveT and Pi per server
                                let r = r_clone.load(Ordering::Relaxed) as f64;
                                let arrive_t = (r / t / l_tot);
                                {
                                    let li_guard = servers_li_map_clone.read();
                                    let mut pi_guard = servers_probability_map_clone.write();

                                    // If no servers tracked or non-positive arriveT, fall back to uniform
                                    if li_guard.is_empty() || arrive_t <= 0.0 {
                                        let uniform = 1.0 / n as f64;
                                        for k in li_guard.keys() {
                                            pi_guard.insert(k.clone(), uniform);
                                        }
                                    } else {
                                        // Choose alpha >= max(alpha0, alpha1) so that 0 <= Pi <= 1 holds
                                        // alpha0 ensures non-negativity: alpha0 = n * (Lmax - Lavg)
                                        // alpha1 ensures Pi <= 1:      alpha1 = n * (Lavg - Lmin) / (n - 1)
                                        // let mut lmax = f64::NEG_INFINITY;
                                        // let mut lmin = f64::INFINITY;
                                        // for (_, li) in li_guard.iter() {
                                        //     if *li > lmax { lmax = *li; }
                                        //     if *li < lmin { lmin = *li; }
                                        // }
                                        // let lavg = l_tot / n as f64;
                                        // let alpha0 = (n as f64 * (lmax - lavg)).max(0.0);
                                        // let alpha1 = if n > 1 {
                                        //     (n as f64 * (lavg - lmin) / (n as f64 - 1.0)).max(0.0)
                                        // } else { 0.0 };
                                        // let alpha = arrive_t.max(alpha0.max(alpha1)).max(1e-9);

                                        for (k, l_i) in li_guard.iter() {
                                            let mut Pi = (((l_tot + arrive_t) / n as f64) - *l_i) / arrive_t;
                                            if !Pi.is_finite() { Pi = 0.0; }
                                            pi_guard.insert(k.clone(), Pi);
                                        }
                                    }
                                }

                                // Print all Pi
                                let pi_guard = servers_probability_map_clone.read();
                                let mut pi_items: Vec<_> = pi_guard.iter().collect();
                                pi_items.sort_by(|a, b| a.0.partial_cmp(b.0).unwrap_or(std::cmp::Ordering::Equal));
                                let pi_list = pi_items
                                    .iter()
                                    .map(|(k, v)| format!("{}: {:.4}", k, v))
                                    .collect::<Vec<_>>()
                                    .join(", ");
                                println!("Pi = [{}]", pi_list);

                                // if payload.server_socket == "mpeg-dash-processor-1:8080" {
                                //     // Print everything related to li
                                //     println!("c_m = {:.2}", c_m);
                                //     println!("c_d = {:.2}", c_d);
                                //     // lmi, ldi
                                //     println!("lmi = {:.2}", payload.normalized_values.memory_current_consumption);
                                //     println!("ldi = {:.2}", payload.normalized_values.disk_read_consumption);
                                // }

                                // // Print all Li
                                // let li_guard = servers_li_map_clone.read();
                                // let mut li_items: Vec<_> = li_guard.iter().collect();
                                // li_items.sort_by(|a, b| a.0.partial_cmp(b.0).unwrap_or(std::cmp::Ordering::Equal));
                                // let li_list = li_items
                                //     .iter()
                                //     .map(|(k, v)| format!("{}: {:.2}", k, v))
                                //     .collect::<Vec<_>>()
                                //     .join(", ");
                                // println!("Li = [{}]", li_list);
                                
                                // print a list of this below
                                // [TM, TD, N, T, CM, CD, Ltot, R, arriveT]
                                // println!("[TM = {}, TD = {}, N = {}, T = {}, CM = {}, CD = {}, Ltot = {}, R = {}, arriveT = {}]", t_m, t_d, n, t, c_m, c_d, l_tot, r, arrive_t);

                                // // Optional concise log using absolute values for visibility
                                // let mem_mb = payload.absolute_values.memory_current_bytes as f64 / (1024.0 * 1024.0);
                                // let disk_kbps = payload.absolute_values.disk_read_bytes_per_sec as f64 / (1024.0 * 1024.0);
                                // let mem_rel = (payload.normalized_values.memory_current_consumption);
                                // let disk_rel = (payload.normalized_values.disk_read_consumption);
                                // println!(
                                //     "Metrics received: server={} mem={:.2}MB disk={:.2}KB/s mem_rel={:.2} disk_rel={:.2} ts={}",
                                //     payload.server_socket,
                                //     mem_mb,
                                //     disk_kbps,
                                //     mem_rel,
                                //     disk_rel,
                                //     payload.timestamp_unix
                                // );
                            }
                        }
                    }
                    Ok(_) => {}
                    Err(e) => {
                        eprintln!("MQTT event loop error: {}", e);
                        tokio::time::sleep(Duration::from_secs(1)).await;
                    }
                }
            }
        });

        Self {
            servers_info_map,
            servers_li_map,
            servers_probability_map,
            r,
            _mqtt_handle: mqtt_handle,
        }
    }

    fn get_probabilities_snapshot(&self) -> HashMap<String, f64> {
        let read_guard = self.servers_probability_map.read();
        read_guard.iter().map(|(k, v)| (k.clone(), *v)).collect()
    }
}

impl ServerSelectionStrategy for MemoryMonitoringStrategy {
    fn pick_server(&self, servers: &[String]) -> Option<String> {
        if servers.is_empty() {
            return None;
        }

        // Increment R: total requests arrived since start
        let _ = self.r.fetch_add(1, Ordering::Relaxed);

        // Weighted random by Pi for provided servers
        let mut probabilities = self.get_probabilities_snapshot();
        if probabilities.is_empty() {
            // Initialize uniform probabilities to avoid empty snapshots before metrics arrive
            let uniform = 1.0 / (servers.len() as f64);
            {
                let mut guard = self.servers_probability_map.write();
                for s in servers {
                    guard.insert(s.clone(), uniform);
                    probabilities.insert(s.clone(), uniform);
                }
            }
        }
        let mut weights: Vec<(String, f64)> = Vec::with_capacity(servers.len());
        for s in servers {
            let w = probabilities.get(s).copied().unwrap_or(0.0).max(0.0);
            weights.push((s.clone(), w));
        }
        let total_weight: f64 = weights.iter().map(|(_, w)| *w).sum();

        let chosen = if total_weight > 0.0 {
            let mut rng = rand::thread_rng();
            let mut threshold = rng.gen::<f64>() * total_weight;
            for (s, w) in &weights {
                if *w <= 0.0 { continue; }
                if threshold <= *w {
                    return Some(s.clone());
                }
                threshold -= *w;
            }
            // Fallback in case of numerical issues
            Some(weights.last().map(|(s, _)| s.clone()).unwrap_or_else(|| servers[0].clone()))
        } else {
            // No weights yet: pick uniformly at random
            let mut rng = rand::thread_rng();
            let idx = rng.gen_range(0..servers.len());
            Some(servers[idx].clone())
        };

        chosen
    }

    fn debug_snapshot(&self) -> Option<String> {
        let probs = self.get_probabilities_snapshot();
        if probs.is_empty() {
            return Some("probabilities: <empty>".to_string());
        }
        let mut items: Vec<(String, f64)> = probs.into_iter().collect();
        items.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        let s = items
            .into_iter()
            .map(|(k, v)| format!("{}={:.4}", k, v))
            .collect::<Vec<_>>()
            .join(", ");
        Some(format!("probabilities: [{}]", s))
    }
}
