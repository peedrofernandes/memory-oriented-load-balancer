# TCP Load Balancer

A simple TCP load balancer written in Rust that forwards TCP connections to a list of backend servers using a configurable server selection strategy.

## Features

- **Abstracted Server Selection**: Uses a trait-based approach to abstract server selection logic
- **Round-Robin Strategy**: Includes a round-robin implementation that cycles through available servers
- **Async TCP Forwarding**: Uses Tokio for efficient async TCP packet forwarding
- **Bidirectional Communication**: Properly forwards data in both directions between client and server

## Architecture

### Core Components

1. **ServerSelectionStrategy Trait**: Abstracts the server picking logic
   ```rust
   pub trait ServerSelectionStrategy: Send + Sync {
       fn pick_server(&self, servers: &[String]) -> Option<String>;
   }
   ```

2. **RoundRobinStrategy**: Implementation that cycles through servers sequentially

3. **LoadBalancer**: Main struct that handles TCP connections and forwarding

## Configuration

The load balancer is currently configured in `src/main.rs`:

- **Bind Address**: `127.0.0.1:8080` (the port the load balancer listens on)
- **Backend Servers**: 
  - `127.0.0.1:3001`
  - `127.0.0.1:3002`  
  - `127.0.0.1:3003`

## Usage

### Prerequisites

- Rust and Cargo installed
- Backend servers running on the configured ports

### Running the Load Balancer

```bash
cd load-balancer
cargo run
```

### Testing

1. Start some test servers on ports 3001, 3002, and 3003
2. Run the load balancer
3. Connect to `127.0.0.1:8080` - your connections will be distributed across the backend servers

### Example Test Servers

You can use netcat to create simple test servers:

```bash
# Terminal 1
nc -l 3001

# Terminal 2  
nc -l 3002

# Terminal 3
nc -l 3003
```

Then connect to the load balancer:
```bash
nc 127.0.0.1 8080
```

## Extending with Custom Strategies

To implement a custom server selection strategy, create a struct that implements the `ServerSelectionStrategy` trait:

```rust
use load_balancer::ServerSelectionStrategy;

struct CustomStrategy {
    // Your strategy state
}

impl ServerSelectionStrategy for CustomStrategy {
    fn pick_server(&self, servers: &[String]) -> Option<String> {
        // Your custom logic here
        // Return the selected server address
    }
}
```

## Dependencies

- `tokio`: Async runtime for handling TCP connections and I/O operations
