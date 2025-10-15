# Load Generator

A Python-based load generator for testing the TCP/HTTP load balancer performance. This tool generates configurable concurrent load to test distribution capabilities and measure performance metrics.

## Features

- **Concurrent Load Generation**: Configurable number of concurrent users/connections
- **Flexible Test Configuration**: Control requests count, duration, delays, and timeouts
- **Comprehensive Metrics**: Response times, throughput, error rates, and percentile analysis
- **Async HTTP Requests**: Uses aiohttp for efficient concurrent HTTP requests
- **Graceful Shutdown**: Handles interruption signals properly
- **JSON Export**: Save detailed results to JSON files for analysis
- **Real-time Progress**: Monitor test progress and results

## Installation

### Option 1: Local Python Installation
```bash
pip install -r requirements.txt
```

### Option 2: Docker (Recommended)
Build the Docker image:
```bash
docker build -t load-generator .
```

## Usage

### Docker Usage (Recommended)

Basic load test:
```bash
docker run --rm load-generator --url http://host.docker.internal:8080 --concurrent 10 --requests 100
```

With output file (save results to host):
```bash
docker run --rm -v $(pwd)/results:/app/results load-generator \
  --url http://host.docker.internal:8080 \
  --concurrent 25 --requests 500 \
  --output /app/results/test_results.json
```

Interactive mode with custom parameters:
```bash
docker run --rm -it load-generator \
  --url http://host.docker.internal:8080 \
  --concurrent 50 --duration 60 \
  --timeout 10
```

### Local Python Usage

### Basic Usage

Test with default settings (10 concurrent users, 100 total requests):
```bash
python load_generator.py
```

### Advanced Usage

```bash
# Test with 50 concurrent users making 1000 requests
python load_generator.py --concurrent 50 --requests 1000

# Run test for 60 seconds with 20 concurrent users
python load_generator.py --concurrent 20 --duration 60

# Test specific endpoint with custom URL
python load_generator.py --url http://localhost:8080 --endpoint /api/health

# Add delay between requests and save results
python load_generator.py --delay 0.1 --output results.json

# Test with custom timeout
python load_generator.py --timeout 10 --concurrent 100
```

### Command Line Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--url` | `-u` | `http://localhost:8080` | Target URL to load test |
| `--concurrent` | `-c` | `10` | Number of concurrent users/connections |
| `--requests` | `-n` | `100` | Total number of requests to make |
| `--duration` | `-d` | None | Test duration in seconds (overrides --requests) |
| `--delay` | | `0.0` | Delay between requests per user in seconds |
| `--timeout` | `-t` | `30.0` | Request timeout in seconds |
| `--output` | `-o` | None | Output file for JSON results |
| `--endpoint` | | `/` | Endpoint path to append to URL |
| `--log-level` | | `INFO` | Logging level: DEBUG, INFO, WARNING, ERROR |

## Example Test Scenarios

### 1. Basic Load Test
Test the load balancer with moderate load:
```bash
python load_generator.py --concurrent 25 --requests 500
```

### 2. Stress Test
High concurrent load for stress testing:
```bash
python load_generator.py --concurrent 100 --duration 120 --timeout 5
```

### 3. Sustained Load Test
Long-running test with controlled rate:
```bash
python load_generator.py --concurrent 10 --duration 300 --delay 0.5
```

### 4. API Endpoint Testing
Test specific API endpoints:
```bash
# Local
python load_generator.py --endpoint /api/video --concurrent 20 --requests 200

# Docker
docker run --rm load-generator --url http://host.docker.internal:8080 --endpoint /api/video --concurrent 20 --requests 200
```

### 5. Debugging with Enhanced Logging
Enable detailed logging to troubleshoot issues:
```bash
# Debug level logging (shows all requests)
python load_generator.py --log-level DEBUG --concurrent 5 --requests 50

# Docker with debug logging
docker run --rm load-generator --url http://host.docker.internal:8080 --log-level DEBUG --concurrent 10 --requests 100

# Error-only logging for production
python load_generator.py --log-level ERROR --concurrent 100 --duration 300
```

## Output Metrics

The load generator provides comprehensive metrics:

- **Request Statistics**: Total, successful, and failed requests
- **Performance Metrics**: Requests per second, error rate
- **Response Time Analysis**: 
  - Average, minimum, and maximum response times
  - 50th, 95th, and 99th percentile response times
- **Error Breakdown**: Categorized error types and counts

### Sample Output
```
==============================================================
LOAD TEST RESULTS
==============================================================
Test Duration: 12.34 seconds
Total Requests: 100
Successful Requests: 95
Failed Requests: 5
Error Rate: 5.00%
Requests/Second: 8.10

Response Time Statistics:
  Average: 123.45 ms
  Minimum: 45.67 ms
  Maximum: 567.89 ms
  50th Percentile: 112.34 ms
  95th Percentile: 234.56 ms
  99th Percentile: 456.78 ms

Error Breakdown:
  Timeout: 3
  Client Error: 2
==============================================================
```

## JSON Output Format

When using `--output`, results are saved in JSON format:

```json
{
  "total_requests": 100,
  "successful_requests": 95,
  "failed_requests": 5,
  "total_time": 12.34,
  "requests_per_second": 8.10,
  "avg_response_time": 0.12345,
  "error_rate": 5.0,
  "errors": {
    "Timeout": 3,
    "Client Error": 2
  },
  "test_config": {
    "target_url": "http://localhost:8080/",
    "concurrent_users": 10,
    "total_requests": 100,
    "duration": null,
    "request_delay": 0.0,
    "timeout": 30.0
  },
  "timestamp": "2024-01-15T10:30:45.123456"
}
```

## Integration with Load Balancer

This load generator is designed to work with the TCP load balancer in this project:

1. **Start the load balancer and backend services**:
```bash
docker-compose up -d
```

2. **Run load tests against the load balancer**:
```bash
python load_generator.py --url http://localhost:8080
```

3. **Monitor load distribution** using the monitoring dashboard at `http://localhost:3001`

## Tips for Effective Load Testing

1. **Start Small**: Begin with low concurrent users and gradually increase
2. **Monitor Resources**: Watch CPU, memory, and network usage during tests
3. **Test Different Patterns**: Vary request rates and durations
4. **Baseline Testing**: Establish performance baselines before optimization
5. **Real-world Scenarios**: Use realistic request patterns and payloads

## Troubleshooting

### Connection Errors
- Ensure the load balancer is running and accessible
- Check firewall settings and port availability
- Verify the target URL is correct

### High Error Rates
- Increase timeout values for slower responses
- Reduce concurrent users if overwhelming the system
- Check backend service health and capacity

### Performance Issues
- Monitor system resources during testing
- Consider request delays to simulate realistic user behavior
- Ensure adequate network bandwidth

## Contributing

Feel free to enhance the load generator with additional features:
- Custom request headers and payloads
- Different HTTP methods (POST, PUT, DELETE)
- Authentication support
- Custom load patterns (ramp-up, spike testing)
- Real-time graphical output
