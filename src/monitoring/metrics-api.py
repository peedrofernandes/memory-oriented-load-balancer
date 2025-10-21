#!/usr/bin/env python3
"""
Simplified metrics API for container IO and memory monitoring
Uses host machine io.stat and memory.stat files via bind mounts
"""

from flask import Flask, jsonify
from flask_cors import CORS
import subprocess
import os
import time
import logging
import threading

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global storage for metrics
metrics_data = {}
data_lock = threading.Lock()
background_thread = None
stop_background = False

# Update frequency
UPDATE_INTERVAL = 0.5  # 500ms

# Container limits from docker-compose.yml (parametrized)
CONTAINER_LIMITS = {
    "mpeg-dash-processor-1": {
        "memory_mb": 4096,
        "io_rate_mbps": 128
    },
    "mpeg-dash-processor-2": {
        "memory_mb": 2048,
        "io_rate_mbps": 64
    },
    "mpeg-dash-processor-3": {
        "memory_mb": 1024,
        "io_rate_mbps": 32
    },
    "mpeg-dash-processor-4": {
        "memory_mb": 512,
        "io_rate_mbps": 16
    },
    "mpeg-dash-processor-5": {
        "memory_mb": 256,
        "io_rate_mbps": 8
    },
    "mpeg-dash-processor-6": {
        "memory_mb": 128,
        "io_rate_mbps": 4
    },
    "mpeg-dash-processor-7": {
        "memory_mb": 64,
        "io_rate_mbps": 2
    },
    "mpeg-dash-processor-8": {
        "memory_mb": 32,
        "io_rate_mbps": 1
    },
    "load-balancer": {
        "memory_mb": 256,
        "io_rate_mbps": 256
    }
}

# Hardware sector size (will be read at startup)
HW_SECTOR_SIZE = 512  # Default value, will be updated from /sys/block/sda/queue/hw_sector_size

def read_hw_sector_size():
    """Read hardware sector size from /sys/block/sda/queue/hw_sector_size"""
    global HW_SECTOR_SIZE
    try:
        with open('/sys/block/sda/queue/hw_sector_size', 'r') as f:
            sector_size = int(f.read().strip())
            HW_SECTOR_SIZE = sector_size
            logger.info(f"Hardware sector size: {HW_SECTOR_SIZE} bytes")
            return sector_size
    except Exception as e:
        logger.warning(f"Failed to read hw_sector_size, using default {HW_SECTOR_SIZE}: {e}")
        return HW_SECTOR_SIZE

def get_container_mapping():
    """Get mapping between container names and container IDs"""
    try:
        result = subprocess.run([
            'docker', 'ps', '--format', '{{.ID}} {{.Names}}', '--no-trunc'
        ], capture_output=True, text=True, timeout=5)
        
        if result.returncode != 0:
            logger.error(f"Failed to get container mapping: {result.stderr}")
            return {}
        
        mapping = {}
        for line in result.stdout.strip().split('\n'):
            if line and 'mpeg-dash-processor' in line:
                parts = line.split(' ', 1)
                if len(parts) == 2:
                    container_id, container_name = parts
                    mapping[container_name] = container_id
        
        return mapping
            
    except Exception as e:
        logger.error(f"Error getting container mapping: {e}")
        return {}

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

def read_io_stat(container_id):
    """Read cumulative read bytes using best-effort across cgroup variants or docker stats."""
    # Try cgroup v2 paths first
    possible_paths = [
        f"/sys/fs/cgroup/docker/{container_id}/io.stat",
        f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/io.stat",
        f"/sys/fs/cgroup/{container_id}/io.stat",
    ]
    for path in possible_paths:
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read().strip()
                if content:
                    total_rbytes = 0
                    for line in content.split('\n'):
                        if 'rbytes=' in line:
                            for part in line.split():
                                if part.startswith('rbytes='):
                                    total_rbytes += int(part.split('=')[1])
                                    break
                    return total_rbytes
        except Exception as e:
            logger.debug(f"Failed reading {path}: {e}")

    # Fallback: parse docker stats --no-stream BlockIO (read/ write cumulative)
    try:
        result = subprocess.run([
            'docker', 'stats', '--no-stream', '--format', '{{.BlockIO}}', container_id
        ], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout:
            blockio = result.stdout.strip()
            # Format like: "12.3MB / 4.5MB" -> take read part
            read_part = blockio.split('/')[0].strip()
            return parse_size_to_bytes_cli(read_part)
    except Exception as e:
        logger.debug(f"docker stats fallback failed for {container_id}: {e}")
    return 0
            
def read_memory_current(container_id):
    """Read memory.current file for a container (cgroup v2)"""
    try:
        # Try different cgroup paths (v1 and v2)
        paths = [
            f"/sys/fs/cgroup/docker/{container_id}/memory.current",  # cgroup v2 primary
            f"/sys/fs/cgroup/memory/docker/{container_id}/memory.usage_in_bytes",
            f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/memory.current"
        ]
        
        for path in paths:
            try:
                with open(path, 'r') as f:
                    content = f.read().strip()
                    if content:
                        return content
            except Exception as e:
                logger.debug(f"Failed to read {path}: {e}")
                continue
        
        logger.warning(f"Could not read memory.current for container {container_id}")
        return None
        
    except Exception as e:
        logger.error(f"Error reading memory.current for {container_id}: {e}")
        return None

def parse_memory_current(memory_current_content):
    """Parse memory.current content and extract current usage (cgroup v2)"""
    if not memory_current_content:
        return 0
    try:
        memory_bytes = int(memory_current_content.strip())
        return memory_bytes
    except Exception as e:
        logger.error(f"Error parsing memory.current: {e}")
        return 0

def read_memory_limit_bytes(container_id):
    """Read memory.limit_in_bytes or memory.max; return integer bytes or None."""
    paths = [
        f"/sys/fs/cgroup/docker/{container_id}/memory.max",
        f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/memory.max",
        f"/sys/fs/cgroup/memory/docker/{container_id}/memory.limit_in_bytes",
    ]
    for path in paths:
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    content = f.read().strip()
                if content and content != 'max':
                    return int(content)
        except Exception:
            continue
    # Fallback to docker inspect
    try:
        result = subprocess.run([
            'docker', 'inspect', '-f', '{{.HostConfig.Memory}}', container_id
        ], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            val = result.stdout.strip()
            if val.isdigit():
                return int(val)
    except Exception:
        pass
    return None

def parse_size_to_bytes_cli(size_str: str) -> int:
    try:
        s = size_str.strip().upper()
        if s.endswith('GB'):
            return int(float(s[:-2]) * 1024 * 1024 * 1024)
        if s.endswith('MB'):
            return int(float(s[:-2]) * 1024 * 1024)
        if s.endswith('KB'):
            return int(float(s[:-2]) * 1024)
        if s.endswith('B'):
            return int(float(s[:-1]))
        return int(float(s))
    except Exception:
        return 0
    

def metrics_background_thread():
    """Background thread to collect metrics at high frequency"""
    global metrics_data, stop_background
    
    while not stop_background:
        try:
            current_time = time.time()
            container_mapping = get_container_mapping()

            desired_names = set(CONTAINER_LIMITS.keys())

            with data_lock:
                for container_name in desired_names:
                    container_id = container_mapping.get(container_name)

                    if container_id:
                        current_io_bytes = read_io_stat(container_id)
                        memory_current_content = read_memory_current(container_id)
                        current_memory_bytes = parse_memory_current(memory_current_content)

                        container_limits = CONTAINER_LIMITS.get(container_name, {})
                        memory_limit_bytes_dynamic = read_memory_limit_bytes(container_id)
                        if memory_limit_bytes_dynamic and memory_limit_bytes_dynamic > 0:
                            memory_limit_mb = int(memory_limit_bytes_dynamic / (1024 * 1024))
                        else:
                            memory_limit_mb = container_limits.get('memory_mb', 0)
                        io_limit_mbps = container_limits.get('io_rate_mbps', 0)

                        memory_percent = 0
                        if memory_limit_mb > 0:
                            memory_limit_bytes = memory_limit_mb * 1024 * 1024
                            memory_percent = min(100, (current_memory_bytes / memory_limit_bytes) * 100)

                        metrics_data[container_name] = {
                            'status': 'running',
                            'io_bytes_total': current_io_bytes,
                            'memory_bytes': current_memory_bytes,
                            'memory_human': bytes_to_human(current_memory_bytes),
                            'memory_percent': round(memory_percent, 1),
                            'memory_limit_mb': memory_limit_mb,
                            'io_limit_mbps': io_limit_mbps,
                            'timestamp': current_time
                        }
                    else:
                        if container_name != "load-balancer":
                            logger.error(f"Container {container_name} not found")
        except Exception as e:
            logger.error(f"Error in background metrics collection: {e}")
        
        time.sleep(UPDATE_INTERVAL)

def start_background_thread():
    """Start the background metrics collection thread"""
    global background_thread, stop_background
    
    if background_thread is None or not background_thread.is_alive():
        stop_background = False
        background_thread = threading.Thread(target=metrics_background_thread, daemon=True)
        background_thread.start()

def get_current_metrics():
    """Get current metrics from the background thread data"""
    current_time = int(time.time())
    
    with data_lock:
        containers_data = []
        
        for container_name, data in metrics_data.items():
            containers_data.append({
                "name": container_name,
                "status": data.get('status', 'running'),
                "timestamp": current_time,
                "metrics": {
                    # Memory metrics (absolute and relative)
                    "memory": {
                        "absolute": {
                            "bytes": data['memory_bytes'],
                            "human": data['memory_human']
                        },
                        "relative": {
                            "percent": data['memory_percent'],
                            "limit_mb": data['memory_limit_mb']
                        }
                    },
                    # IO metrics (raw values for frontend calculation)
                    "io": {
                        "absolute": {
                            "bytes_total": data['io_bytes_total'],
                            "human": bytes_to_human(data['io_bytes_total'])
                        },
                        "relative": {
                            "limit_mbps": data['io_limit_mbps']
                        }
                    },
                    "last_updated": data['timestamp']
                }
            })
        
        return {
            "timestamp": current_time,
            "containers": containers_data,
            "update_interval_ms": int(UPDATE_INTERVAL * 1000)
        }


# Flask API endpoints
@app.route('/metrics', methods=['GET', 'POST'])
def metrics():
    """Return container metrics from background thread data"""
    return jsonify(get_current_metrics())

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy", 
        "service": "simplified-metrics-api",
        "background_thread_active": background_thread is not None and background_thread.is_alive(),
        "update_interval_ms": int(UPDATE_INTERVAL * 1000)
    })

@app.route('/', methods=['GET'])
def index():
    """API information"""
    return jsonify({
        "service": "Simplified Container Metrics API",
        "version": "3.1",
        "description": "High-frequency IO and memory monitoring using host cgroup files with absolute and relative metrics",
        "features": [
            "host_cgroup_access", 
            "500ms_updates", 
            "io_mbps_calculation", 
            "hw_sector_size_aware",
            "absolute_and_relative_metrics",
            "parametrized_container_limits"
        ],
        "endpoints": {
            "/metrics": "Get current container metrics (absolute and relative IO/memory)",
            "/health": "Health check with background thread status"
        },
        "container_limits": CONTAINER_LIMITS,
        "hw_sector_size": HW_SECTOR_SIZE,
        "update_interval_ms": int(UPDATE_INTERVAL * 1000)
    })

if __name__ == '__main__':
    print("🚀 Starting simplified metrics API server...")
    print(f"   • Update interval: {UPDATE_INTERVAL}s ({int(UPDATE_INTERVAL * 1000)}ms)")
    print(f"   • Monitoring mpeg-dash-processor containers")
    print(f"   • Using host cgroup files for IO and memory stats")
    
    # Read hardware sector size for accurate IO calculations
    read_hw_sector_size()
    
    print(f"   • Hardware sector size: {HW_SECTOR_SIZE} bytes")
    print(f"   • Available at: http://0.0.0.0:3002")
    
    # Start background metrics collection
    start_background_thread()
    
    app.run(host='0.0.0.0', port=3002, debug=False, threaded=True)
