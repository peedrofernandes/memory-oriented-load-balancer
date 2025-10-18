pub trait ServerSelectionStrategy: Send + Sync {
    fn pick_server(&self, servers: &[String]) -> Option<String>;

    // Optional debug info to be logged per request (e.g., scores)
    fn debug_snapshot(&self) -> Option<String> {
        None
    }
}


