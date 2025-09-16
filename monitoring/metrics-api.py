#!/usr/bin/env python3
"""
Simplified metrics API for container IO and memory monitoring
Uses host machine io.stat and memory.stat files via bind mounts
"""

from flask import Flask, jsonify
from flask_cors import CORS
import subprocess
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
        "memory_mb": 2048,
        "io_rate_mbps": 1024
    },
    "mpeg-dash-processor-2": {
        "memory_mb": 1024,
        "io_rate_mbps": 512
    },
    "mpeg-dash-processor-3": {
        "memory_mb": 512,
        "io_rate_mbps": 256
    },
    "mpeg-dash-processor-4": {
        "memory_mb": 256,
        "io_rate_mbps": 128
    },
    "mpeg-dash-processor-5": {
        "memory_mb": 128,
        "io_rate_mbps": 64
    },
    "mpeg-dash-processor-6": {
        "memory_mb": 64,
        "io_rate_mbps": 32
    },
    "mpeg-dash-processor-7": {
        "memory_mb": 32,
        "io_rate_mbps": 16
    },
    "mpeg-dash-processor-8": {
        "memory_mb": 16,
        "io_rate_mbps": 8
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
                    logger.info(f"Mapped {container_name} -> {container_id}")
        
        logger.info(f"Found {len(mapping)} mpeg-dash-processor containers")
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
    """Read io.stat file for a container"""
    try:
        # Try different cgroup paths (v1 and v2)
        paths = [
            f"/sys/fs/cgroup/docker/{container_id}/io.stat",  # cgroup v2 primary
            f"/sys/fs/cgroup/blkio/docker/{container_id}/blkio.io_service_bytes",
            f"/sys/fs/cgroup/system.slice/docker-{container_id}.scope/io.stat"
        ]
        
        for path in paths:
            try:
                with open(path, 'r') as f:
                    content = f.read().strip()
                    if content:
                        logger.info(f"Successfully read io.stat from {path}: {content}")
                        return content
            except Exception as e:
                logger.debug(f"Failed to read {path}: {e}")
                continue
        
        logger.warning(f"Could not read io.stat for container {container_id}")
        return None
            
    except Exception as e:
        logger.error(f"Error reading io.stat for {container_id}: {e}")
        return None
            
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
                        logger.info(f"Successfully read memory.current from {path}: {content}")
                        return content
            except Exception as e:
                logger.debug(f"Failed to read {path}: {e}")
                continue
        
        logger.warning(f"Could not read memory.current for container {container_id}")
        return None
        
    except Exception as e:
        logger.error(f"Error reading memory.current for {container_id}: {e}")
        return None

def parse_io_stat(io_stat_content):
    """Parse io.stat content and extract read bytes"""
    if not io_stat_content:
        return 0
    
    try:
        total_read_bytes = 0
        logger.info(f"Parsing io.stat content: {io_stat_content}")
        
        # Handle different formats
        for line in io_stat_content.split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # cgroup v2 format: "8:80 rbytes=90112 wbytes=0 rios=3 wios=0 dbytes=0 dios=0"
            if 'rbytes=' in line:
                for part in line.split():
                    if part.startswith('rbytes='):
                        bytes_value = int(part.split('=')[1])
                        total_read_bytes += bytes_value
                        logger.info(f"Found rbytes={bytes_value} in line: {line}")
            
            # cgroup v1 format: "8:0 Read 123456" (bytes)
            elif 'Read' in line:
                parts = line.split()
                if len(parts) >= 3:
                    bytes_value = int(parts[2])
                    total_read_bytes += bytes_value
                    logger.info(f"Found Read {bytes_value} in line: {line}")
            
            # Some systems report sectors instead of bytes
            elif 'sectors' in line.lower() and any(x in line.lower() for x in ['read', 'r']):
                parts = line.split()
                for i, part in enumerate(parts):
                    if 'read' in part.lower() or part.lower() == 'r':
                        if i + 1 < len(parts):
                            sectors = int(parts[i + 1])
                            bytes_value = sectors * HW_SECTOR_SIZE
                            total_read_bytes += bytes_value
                            logger.info(f"Found {sectors} sectors = {bytes_value} bytes")
        
        logger.info(f"Total read bytes parsed: {total_read_bytes}")
        return total_read_bytes
        
    except Exception as e:
        logger.error(f"Error parsing io.stat: {e}")
        logger.error(f"Content was: {io_stat_content}")
        return 0

def parse_memory_current(memory_current_content):
    """Parse memory.current content and extract current usage (cgroup v2)"""
    if not memory_current_content:
        return 0
    
    try:
        # cgroup v2 memory.current is just a single number (bytes)
        memory_bytes = int(memory_current_content.strip())
        logger.info(f"Parsed memory usage: {memory_bytes} bytes")
        return memory_bytes
    except Exception as e:
        logger.error(f"Error parsing memory.current: {e}")
        return 0

def metrics_background_thread():
    """Background thread to collect metrics at high frequency"""
    global metrics_data, stop_background
    
    while not stop_background:
        try:
            current_time = time.time()
            container_mapping = get_container_mapping()
            
            with data_lock:
                for container_name, container_id in container_mapping.items():
                    # Read current stats
                    io_stat_content = read_io_stat(container_id)
                    memory_current_content = read_memory_current(container_id)
                    
                    # Parse current values (raw values, no delta calculation)
                    current_io_bytes = parse_io_stat(io_stat_content)
                    current_memory_bytes = parse_memory_current(memory_current_content)
                    
                    # Get container limits for relative calculations
                    container_limits = CONTAINER_LIMITS.get(container_name, {})
                    memory_limit_mb = container_limits.get('memory_mb', 0)
                    io_limit_mbps = container_limits.get('io_rate_mbps', 0)
                    
                    # Calculate memory percentage (no delta needed for memory)
                    memory_percent = 0
                    if memory_limit_mb > 0:
                        memory_limit_bytes = memory_limit_mb * 1024 * 1024
                        memory_percent = min(100, (current_memory_bytes / memory_limit_bytes) * 100)
                    
                    # Store raw metrics (frontend will handle delta calculations)
                    metrics_data[container_name] = {
                        # Raw IO bytes (cumulative since container start)
                        'io_bytes_total': current_io_bytes,
                        'memory_bytes': current_memory_bytes,
                        'memory_human': bytes_to_human(current_memory_bytes),
                        # Memory percentage (can be calculated immediately)
                        'memory_percent': round(memory_percent, 1),
                        # Limits for reference
                        'memory_limit_mb': memory_limit_mb,
                        'io_limit_mbps': io_limit_mbps,
                        'timestamp': current_time
                    }
            
            logger.info(f"Updated metrics for {len(container_mapping)} containers")
            
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
        logger.info("Started background metrics collection thread")

def get_current_metrics():
    """Get current metrics from the background thread data"""
    current_time = int(time.time())
    
    with data_lock:
        containers_data = []
        
        for container_name, data in metrics_data.items():
            containers_data.append({
                "name": container_name,
                "status": "running",
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
