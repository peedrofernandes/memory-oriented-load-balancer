# Multi-stage build for optimized production image
FROM rust:1.82 as builder

# Set the working directory
WORKDIR /app

# Copy dependency files first for better layer caching
COPY Cargo.toml Cargo.lock* ./

# Create a dummy main.rs to build dependencies
RUN mkdir src && echo "fn main() {}" > src/main.rs

# Build dependencies (this layer will be cached unless Cargo.toml changes)
RUN cargo build --release && rm -rf src

# Copy the actual source code
COPY src ./src

# Build the application
RUN cargo build --release

# Runtime stage - use a minimal base image
FROM debian:bookworm-slim

# Install required system dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN useradd -r -s /bin/false appuser

# Set the working directory
WORKDIR /app

# Copy the binary from builder stage
COPY --from=builder /app/target/release/load-balancer /app/load-balancer

# Change ownership to the non-root user
RUN chown appuser:appuser /app/load-balancer

# Switch to non-root user
USER appuser

# Expose the default port (configurable via environment)
EXPOSE 8080

# Health check to ensure the service is running
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD timeout 3 bash -c '</dev/tcp/localhost/8080' || exit 1

# Run the load balancer
CMD ["./load-balancer"]
