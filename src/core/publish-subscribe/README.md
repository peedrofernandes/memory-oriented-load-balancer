# NanoMQ MQTT Broker Setup

This folder contains a Docker setup for NanoMQ, an ultra-fast, lightweight MQTT broker designed for edge computing.

## Quick Start

### 1. Build and Run the Broker

```bash
# Build and start the broker
docker-compose up --build -d

# Check if it's running
docker-compose ps
```

### 2. Test with Terminal Commands

**Subscribe to a topic (run in one terminal):**
```bash
# Using Docker exec with NanoMQ client
docker exec -it nanomq-broker nanomq sub -h localhost -p 1883 -t "test/topic"

# Or using mosquitto_sub (if installed on host)
mosquitto_sub -h localhost -p 1883 -t "test/topic"
```

**Publish a message (run in another terminal):**
```bash
# Using Docker exec with NanoMQ client
docker exec -it nanomq-broker nanomq pub -h localhost -p 1883 -t "test/topic" -m "Hello, NanoMQ!"

# Or using mosquitto_pub (if installed on host)
mosquitto_pub -h localhost -p 1883 -t "test/topic" -m "Hello, NanoMQ!"
```

### 3. Interactive Shell

```bash
# Enter the container
docker exec -it nanomq-broker sh

# Inside container, you can use NanoMQ commands:
nanomq pub -h localhost -p 1883 -t "sensors/temperature" -m "23.5"
nanomq sub -h localhost -p 1883 -t "sensors/#"
```

### 4. NanoMQ Specific Features

**Check broker status via HTTP API:**
```bash
# Get broker information
curl http://localhost:8081/api/v4/brokers

# Get connections
curl http://localhost:8081/api/v4/connections

# Get subscription information
curl http://localhost:8081/api/v4/subscriptions
```

**Advanced NanoMQ commands:**
```bash
# Publish with QoS
docker exec -it nanomq-broker nanomq pub -h localhost -p 1883 -t "test/qos" -m "QoS Test" -q 1

# Subscribe with specific client ID
docker exec -it nanomq-broker nanomq sub -h localhost -p 1883 -t "test/#" -i "my-client-id"

# Publish retained message
docker exec -it nanomq-broker nanomq pub -h localhost -p 1883 -t "status/online" -m "broker_online" -r
```

## Available Ports

- **1883**: MQTT TCP port
- **8083**: MQTT WebSocket port
- **8081**: HTTP REST API port

## Configuration

The broker uses configuration in `nanomq.conf` which is mounted into the container at `/etc/nanomq.conf`.

### Key Configuration Features:
- **High Performance**: Optimized for low latency and high throughput
- **Low Memory**: Minimal memory footprint
- **HTTP API**: RESTful API for management and monitoring
- **WebSocket Support**: Built-in WebSocket support for web clients

## Logs

View logs with:
```bash
# Docker compose logs
docker-compose logs nanomq

# Follow logs in real-time
docker-compose logs -f nanomq

# Check NanoMQ log file inside container
docker exec -it nanomq-broker tail -f /tmp/nanomq.log
```

## Performance Testing

**Load Testing with NanoMQ:**
```bash
# High-frequency publishing
for i in {1..1000}; do
  docker exec nanomq-broker nanomq pub -h localhost -p 1883 -t "load/test" -m "message_$i"
done

# Multiple subscribers
docker exec -d nanomq-broker nanomq sub -h localhost -p 1883 -t "load/#" -i "subscriber_1"
docker exec -d nanomq-broker nanomq sub -h localhost -p 1883 -t "load/#" -i "subscriber_2"
```

## HTTP API Examples

```bash
# Get broker statistics
curl -s http://localhost:8081/api/v4/stats | jq

# Get all active connections
curl -s http://localhost:8081/api/v4/connections | jq

# Get subscription count
curl -s http://localhost:8081/api/v4/subscriptions/count
```

## Why NanoMQ?

- ⚡ **Ultra Fast**: Designed for microsecond-level latency
- 🪶 **Lightweight**: Minimal resource usage perfect for edge/IoT
- 🔧 **HTTP API**: Built-in REST API for monitoring and management
- 📊 **Real-time Stats**: Live broker and connection statistics
- 🌐 **Modern**: Built with modern C/C++ for optimal performance

## Stop the Broker

```bash
docker-compose down
```

## Clean Up Volumes

```bash
# Remove all data and logs
docker-compose down -v
```