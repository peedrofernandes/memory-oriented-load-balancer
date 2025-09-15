#!/usr/bin/env python3
"""
Optimized Flask API to serve Docker container metrics
High-frequency monitoring with caching and batch operations
"""

from flask import Flask, jsonify
from flask_cors import CORS
import subprocess
import json
import time
import logging
import re
import threading
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Set up logging
logging.basicConfig(level=logging.WARNING)  # Reduced logging for performance
logger = logging.getLogger(__name__)

# Global cache and threading
metrics_cache = {}
cache_lock = threading.Lock()
last_update = 0
CACHE_DURATION = 2  # Cache for 2 seconds
background_thread = None
stop_background = False

# Container list
CONTAINERS = [
    "mpeg-dash-processor-1", "mpeg-dash-processor-2", "mpeg-dash-processor-3", "mpeg-dash-processor-4",
    "mpeg-dash-processor-5", "mpeg-dash-processor-6", "mpeg-dash-processor-7", "mpeg-dash-processor-8",
    "load-balancer"
]

def bytes_to_human(bytes_val):
    """Convert bytes to human readable format"""
    if bytes_val >= 1073741824:
        return f"{bytes_val / 1073741824:.1f}GB"
    elif bytes_val >= 1048576:
        return f"{bytes_val / 1048576:.1f}MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.1f}KB"
    else:
        return f"{bytes_val}B"

def parse_size_to_bytes(size_str):
    """Parse size string to bytes"""
    try:
        number = float(re.findall(r'[\d.]+', size_str)[0])
        unit = re.findall(r'[a-zA-Z]+', size_str.upper())
        unit = unit[0] if unit else 'B'
        
        multipliers = {'B': 1, 'KB': 1024, 'MB': 1048576, 'GB': 1073741824, 'K': 1024, 'M': 1048576, 'G': 1073741824}
        return int(number * multipliers.get(unit, 1))
    except:
        return 0

def get_container_linux_metrics(container_name):
    """Get simplified metrics from Linux APIs using docker exec"""
    try:
        # Combine multiple commands into a single docker exec call for efficiency
        commands = [
            # Memory info
            "cat /proc/meminfo",
            "echo '---SEPARATOR---'",
            # Memory usage from cgroup
            "cat /sys/fs/cgroup/memory/memory.usage_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.current 2>/dev/null || echo '0'",
            "echo '---SEPARATOR---'",
            # Memory limit from cgroup
            "cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null || cat /sys/fs/cgroup/memory.max 2>/dev/null || echo '0'",
            "echo '---SEPARATOR---'",
            # Disk I/O stats for all devices
            "cat /proc/diskstats",
            "echo '---SEPARATOR---'",
            # Get I/O statistics from /proc/stat for overall system disk activity
            "grep '^cpu\\|^disk\\|^io' /proc/stat 2>/dev/null || echo 'cpu 0 0 0 0 0 0 0'",
        ]
        
        # Execute all commands in one docker exec call
        full_command = " && ".join(commands)
        result = subprocess.run([
            'docker', 'exec', container_name, 'sh', '-c', full_command
        ], capture_output=True, text=True, timeout=3)
        
        if result.returncode != 0:
            return None
            
        # Parse the combined output
        sections = result.stdout.split('---SEPARATOR---')
        if len(sections) < 5:
            return None
            
        meminfo_raw = sections[0].strip()
        mem_usage_raw = sections[1].strip()
        mem_limit_raw = sections[2].strip()
        diskstats_raw = sections[3].strip()
        stat_raw = sections[4].strip()
        
        # Parse memory info from /proc/meminfo
        mem_total = 0
        for line in meminfo_raw.split('\n'):
            if line.startswith('MemTotal:'):
                mem_total = int(line.split()[1]) * 1024  # Convert KB to bytes
                break
        
        # Parse cgroup memory usage and limit
        try:
            mem_usage_bytes = int(mem_usage_raw)
        except:
            mem_usage_bytes = 0
            
        try:
            mem_limit_bytes = int(mem_limit_raw)
            # If limit is very large (like 9223372036854775807), use system memory
            if mem_limit_bytes > mem_total * 2:
                mem_limit_bytes = mem_total
        except:
            mem_limit_bytes = mem_total
            
        # Calculate memory percentage
        mem_percent = (mem_usage_bytes / mem_limit_bytes * 100) if mem_limit_bytes > 0 else 0
        
        # Parse disk stats from /proc/diskstats
        # Focus on actual storage devices (not loop, ram, etc.)
        total_read_sectors = 0
        total_read_ios = 0
        for line in diskstats_raw.split('\n'):
            if line.strip():
                parts = line.split()
                if len(parts) >= 14:
                    device_name = parts[2]
                    # Focus on real storage devices (exclude loop, ram, sr, etc.)
                    if (device_name.startswith(('sd', 'nvme', 'vd', 'xvd', 'hd')) and 
                        not device_name[-1].isdigit()):  # Exclude partitions
                        # Read I/Os completed (field 3) and sectors read (field 5)
                        read_ios = int(parts[3])
                        read_sectors = int(parts[5])
                        total_read_sectors += read_sectors
                        total_read_ios += read_ios
        
        # Convert sectors to bytes (1 sector = 512 bytes)
        read_bytes = total_read_sectors * 512
        
        return {
            'mem_usage_bytes': mem_usage_bytes,
            'mem_limit_bytes': mem_limit_bytes,
            'mem_percent': mem_percent,
            'read_bytes': read_bytes,
            'read_ios': total_read_ios,
        }
        
    except Exception as e:
        logger.warning(f"Failed to get Linux metrics for {container_name}: {e}")
        return None

def get_batch_container_metrics():
    """Get metrics for all containers using Linux APIs"""
    try:
        timestamp = int(time.time())
        
        # Get running containers
        running_containers = set()
        try:
            result = subprocess.run(['docker', 'ps', '--format', '{{.Names}}'], 
                                  capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                running_containers = {name.strip() for name in result.stdout.split('\n') if name.strip()}
        except:
            pass
        
        containers_data = []
        
        # Process each container
        for container_name in CONTAINERS:
            if container_name not in running_containers:
                containers_data.append({
                    "name": container_name,
                    "status": "stopped",
                    "timestamp": timestamp
                })
                continue
            
            # Get Linux metrics for this container
            linux_metrics = get_container_linux_metrics(container_name)
            
            if linux_metrics is None:
                containers_data.append({
                    "name": container_name,
                    "status": "error",
                    "timestamp": timestamp
                })
                continue
            
            # Calculate disk read rate and percentage
            container_key = f"prev_{container_name}"
            read_rate_bytes_per_sec = 0
            read_rate_percent = 0
            
            # Initialize previous data storage if not exists
            if not hasattr(get_batch_container_metrics, 'prev_data'):
                get_batch_container_metrics.prev_data = {}
            
            # Calculate rate if we have previous data
            if container_key in get_batch_container_metrics.prev_data:
                prev_metrics = get_batch_container_metrics.prev_data[container_key]
                time_diff = timestamp - prev_metrics['timestamp']
                if time_diff > 0:
                    read_diff = linux_metrics['read_bytes'] - prev_metrics['read_bytes']
                    read_rate_bytes_per_sec = max(0, read_diff / time_diff)
                    
                    # Calculate read rate percentage based on a reasonable maximum
                    # Assume max sustainable read rate of 100MB/s as 100%
                    max_read_rate = 100 * 1024 * 1024  # 100 MB/s
                    read_rate_percent = min(100, (read_rate_bytes_per_sec / max_read_rate) * 100)
            
            # Store current data for next calculation
            get_batch_container_metrics.prev_data[container_key] = {
                'timestamp': timestamp,
                'read_bytes': linux_metrics['read_bytes']
            }
            
            # Build simplified container data with only 4 metrics
            containers_data.append({
                "name": container_name,
                "status": "running",
                "timestamp": timestamp,
                "metrics": {
                    # 1. Memory absolute
                    "memory_absolute": {
                        "bytes": linux_metrics['mem_usage_bytes'],
                        "human": bytes_to_human(linux_metrics['mem_usage_bytes'])
                    },
                    # 2. Memory percentage
                    "memory_percent": round(linux_metrics['mem_percent'], 1),
                    # 3. Disk read per second absolute
                    "disk_read_absolute": {
                        "bytes_per_sec": int(read_rate_bytes_per_sec),
                        "human": bytes_to_human(int(read_rate_bytes_per_sec)) + "/s"
                    },
                    # 4. Disk read per second percentage
                    "disk_read_percent": round(read_rate_percent, 1)
                }
            })
        
        return {
            "timestamp": timestamp,
            "containers": containers_data
        }
        
    except Exception as e:
        logger.error(f"Linux metrics collection failed: {e}")
        return {"error": str(e), "timestamp": int(time.time())}


def update_metrics_background():
    """Background thread to update metrics cache"""
    global metrics_cache, last_update, stop_background
    
    while not stop_background:
        try:
            new_metrics = get_batch_container_metrics()
            with cache_lock:
                metrics_cache = new_metrics
                last_update = time.time()
        except Exception as e:
            logger.error(f"Background update failed: {e}")
        
        time.sleep(1)  # Update every second

def get_cached_metrics():
    """Get metrics from cache or update if needed"""
    global metrics_cache, last_update, background_thread
    
    current_time = time.time()
    
    # Start background thread if not running
    if background_thread is None or not background_thread.is_alive():
        background_thread = threading.Thread(target=update_metrics_background, daemon=True)
        background_thread.start()
    
    # Return cached data if recent enough
    with cache_lock:
        if metrics_cache and (current_time - last_update) < CACHE_DURATION:
            return metrics_cache
    
    # If no cache or too old, get fresh data
    fresh_metrics = get_batch_container_metrics()
    with cache_lock:
        metrics_cache = fresh_metrics
        last_update = current_time
    
    return fresh_metrics

@app.route('/metrics', methods=['GET', 'POST'])
def metrics():
    """Return container metrics (optimized with caching)"""
    return jsonify(get_cached_metrics())

@app.route('/metrics/fresh', methods=['GET'])
def metrics_fresh():
    """Force fresh metrics (bypass cache)"""
    return jsonify(get_batch_container_metrics())

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    global last_update
    cache_age = time.time() - last_update if last_update > 0 else 0
    return jsonify({
        "status": "healthy", 
        "service": "metrics-api",
        "cache_age_seconds": round(cache_age, 2),
        "background_thread_active": background_thread is not None and background_thread.is_alive()
    })

@app.route('/', methods=['GET'])
def index():
    """API information"""
    return jsonify({
        "service": "Optimized Container Metrics API",
        "version": "2.0",
        "features": ["batch_operations", "background_caching", "high_frequency"],
        "endpoints": {
            "/metrics": "Get cached container metrics (fast)",
            "/metrics/fresh": "Get fresh container metrics (slower)",
            "/health": "Health check with cache status"
        },
        "cache_duration": f"{CACHE_DURATION}s"
    })

@app.route('/stats', methods=['GET'])
def stats():
    """Performance statistics"""
    global last_update
    return jsonify({
        "cache_duration": CACHE_DURATION,
        "last_update": last_update,
        "cache_age": time.time() - last_update if last_update > 0 else 0,
        "background_active": background_thread is not None and background_thread.is_alive(),
        "containers_monitored": len(CONTAINERS)
    })

if __name__ == '__main__':
    print("🚀 Starting optimized metrics API server...")
    print(f"   • Cache duration: {CACHE_DURATION}s")
    print(f"   • Background updates: Every 1s")
    print(f"   • Monitoring {len(CONTAINERS)} containers")
    print(f"   • Available at: http://0.0.0.0:3002")
    
    app.run(host='0.0.0.0', port=3002, debug=False, threaded=True)
