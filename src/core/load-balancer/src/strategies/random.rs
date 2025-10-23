use rand::Rng;

use super::strategy::ServerSelectionStrategy;

pub struct RandomStrategy;

impl RandomStrategy {
    pub fn new() -> Self {
        Self
    }
}

impl Default for RandomStrategy {
    fn default() -> Self {
        Self::new()
    }
}

impl ServerSelectionStrategy for RandomStrategy {
    fn pick_server(&self, servers: &[String]) -> Option<String> {
        if servers.is_empty() {
            return None;
        }
        let mut rng = rand::thread_rng();
        let idx = rng.gen_range(0..servers.len());
        Some(servers[idx].clone())
    }
}


