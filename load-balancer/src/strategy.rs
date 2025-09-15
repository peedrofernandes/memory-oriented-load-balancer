use std::sync::atomic::{AtomicUsize, Ordering};

/// Trait for abstracting server selection strategies
pub trait ServerSelectionStrategy: Send + Sync {
    fn pick_server(&self, servers: &[String]) -> Option<String>;
}

/// Round-robin implementation of server selection strategy
pub struct RoundRobinStrategy {
    counter: AtomicUsize,
}

impl RoundRobinStrategy {
    pub fn new() -> Self {
        Self {
            counter: AtomicUsize::new(0),
        }
    }
}

impl Default for RoundRobinStrategy {
    fn default() -> Self {
        Self::new()
    }
}

impl ServerSelectionStrategy for RoundRobinStrategy {
    fn pick_server(&self, servers: &[String]) -> Option<String> {
        if servers.is_empty() {
            return None;
        }
        
        let index = self.counter.fetch_add(1, Ordering::Relaxed) % servers.len();
        Some(servers[index].clone())
    }
}
