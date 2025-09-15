#!/bin/bash

# Container Metrics Collection Script
# Collects memory usage and disk IOps for dashboard display
# Output format: JSON for easy consumption by dashboard

# Container list - these are the containers we want to monitor
CONTAINERS=(
    "mpeg-dash-processor-1"
    "mpeg-dash-processor-2" 
    "mpeg-dash-processor-3"
    "mpeg-dash-processor-4"
    "mpeg-dash-processor-5"
    "mpeg-dash-processor-6"
    "mpeg-dash-processor-7"
    "mpeg-dash-processor-8"
    "load-balancer"
)

# Function to convert bytes to human readable format
bytes_to_human() {
    local bytes=$1
    if (( bytes >= 1073741824 )); then
        printf "%.1fGB" $(echo "$bytes / 1073741824" | bc -l)
    elif (( bytes >= 1048576 )); then
        printf "%.1fMB" $(echo "$bytes / 1048576" | bc -l)
    elif (( bytes >= 1024 )); then
        printf "%.1fKB" $(echo "$bytes / 1024" | bc -l)
    else
        printf "%dB" $bytes
    fi
}

# Function to parse size string to bytes
parse_size_to_bytes() {
    local size_str="$1"
    local number=$(echo "$size_str" | sed 's/[^0-9.]//g')
    local unit=$(echo "$size_str" | sed 's/[0-9.]//g' | tr '[:lower:]' '[:upper:]')
    
    case "$unit" in
        "GB"|"G") echo $(echo "$number * 1073741824" | bc) | cut -d'.' -f1 ;;
        "MB"|"M") echo $(echo "$number * 1048576" | bc) | cut -d'.' -f1 ;;
        "KB"|"K") echo $(echo "$number * 1024" | bc) | cut -d'.' -f1 ;;
        "B"|"") echo "$number" | cut -d'.' -f1 ;;
        *) echo "0" ;;
    esac
}

# Function to get container metrics
get_container_metrics() {
    local container_name="$1"
    local timestamp=$(date +%s)
    
    # Check if container is running
    if ! docker ps --format "{{.Names}}" | grep -q "^${container_name}$"; then
        echo "{\"name\":\"$container_name\",\"status\":\"stopped\",\"timestamp\":$timestamp}"
        return
    fi
    
    # Get container stats (single sample)
    # Note: This works because we mounted /var/run/docker.sock into the metrics-collector container
    local stats=$(docker stats --no-stream --format "{{.MemUsage}}\t{{.MemPerc}}\t{{.BlockIO}}" "$container_name" 2>/dev/null)
    
    if [ -z "$stats" ]; then
        echo "{\"name\":\"$container_name\",\"status\":\"error\",\"timestamp\":$timestamp}"
        return
    fi
    
    # Parse stats
    local mem_usage=$(echo "$stats" | cut -f1 | cut -d'/' -f1 | xargs)
    local mem_limit=$(echo "$stats" | cut -f1 | cut -d'/' -f2 | xargs)
    local mem_percent=$(echo "$stats" | cut -f2 | sed 's/%//')
    local block_io=$(echo "$stats" | cut -f3)
    
    # Parse memory values
    local mem_usage_bytes=$(parse_size_to_bytes "$mem_usage")
    local mem_limit_bytes=$(parse_size_to_bytes "$mem_limit")
    local mem_usage_human=$(bytes_to_human "$mem_usage_bytes")
    local mem_limit_human=$(bytes_to_human "$mem_limit_bytes")
    
    # Parse block I/O values
    local read_bytes_str=$(echo "$block_io" | cut -d'/' -f1 | xargs)
    local write_bytes_str=$(echo "$block_io" | cut -d'/' -f2 | xargs)
    local read_bytes=$(parse_size_to_bytes "$read_bytes_str")
    local write_bytes=$(parse_size_to_bytes "$write_bytes_str")
    local read_human=$(bytes_to_human "$read_bytes")
    local write_human=$(bytes_to_human "$write_bytes")
    
    # Calculate I/O rates if previous data exists
    local state_file="/tmp/metrics_${container_name}.state"
    local read_rate_human="0B/s"
    local write_rate_human="0B/s"
    local read_iops="0"
    local write_iops="0"
    
    if [ -f "$state_file" ]; then
        local prev_data=$(cat "$state_file")
        local prev_timestamp=$(echo "$prev_data" | jq -r '.timestamp // 0' 2>/dev/null || echo "0")
        local prev_read=$(echo "$prev_data" | jq -r '.read_bytes // 0' 2>/dev/null || echo "0")
        local prev_write=$(echo "$prev_data" | jq -r '.write_bytes // 0' 2>/dev/null || echo "0")
        
        if [ "$prev_timestamp" != "0" ] && [ "$timestamp" -gt "$prev_timestamp" ]; then
            local time_diff=$((timestamp - prev_timestamp))
            if [ "$time_diff" -gt 0 ]; then
                local read_rate=$(( (read_bytes - prev_read) / time_diff ))
                local write_rate=$(( (write_bytes - prev_write) / time_diff ))
                
                # Calculate approximate IOPS (assuming 4KB average I/O size)
                read_iops=$(( read_rate / 4096 ))
                write_iops=$(( write_rate / 4096 ))
                
                read_rate_human=$(bytes_to_human "$read_rate")/s
                write_rate_human=$(bytes_to_human "$write_rate")/s
                
                # Ensure non-negative values
                [ "$read_iops" -lt 0 ] && read_iops=0
                [ "$write_iops" -lt 0 ] && write_iops=0
            fi
        fi
    fi
    
    # Output JSON
    cat << EOF
{
    "name": "$container_name",
    "status": "running",
    "timestamp": $timestamp,
    "memory": {
        "usage_bytes": $mem_usage_bytes,
        "limit_bytes": $mem_limit_bytes,
        "usage_human": "$mem_usage_human",
        "limit_human": "$mem_limit_human",
        "percent": ${mem_percent:-0}
    },
    "disk_io": {
        "read_bytes": $read_bytes,
        "write_bytes": $write_bytes,
        "read_human": "$read_human",
        "write_human": "$write_human",
        "read_rate_human": "$read_rate_human",
        "write_rate_human": "$write_rate_human",
        "read_iops": $read_iops,
        "write_iops": $write_iops
    }
}
EOF
    
    # Save current state for next calculation
    cat << EOF > "$state_file"
{
    "timestamp": $timestamp,
    "read_bytes": $read_bytes,
    "write_bytes": $write_bytes
}
EOF
}

# Main execution
case "${1:-json}" in
    "json")
        echo "{"
        echo "\"timestamp\": $(date +%s),"
        echo "\"containers\": ["
        
        for i in "${!CONTAINERS[@]}"; do
            get_container_metrics "${CONTAINERS[$i]}"
            if [ $i -lt $((${#CONTAINERS[@]} - 1)) ]; then
                echo ","
            fi
        done
        
        echo "]"
        echo "}"
        ;;
    "clean")
        # Clean up state files
        rm -f /tmp/metrics_*.state
        echo "State files cleaned"
        ;;
    "help")
        echo "Usage: $0 [json|clean|help]"
        echo "  json  - Output container metrics in JSON format (default)"
        echo "  clean - Clean up temporary state files"
        echo "  help  - Show this help message"
        ;;
    *)
        echo "Unknown option: $1"
        echo "Use '$0 help' for usage information"
        exit 1
        ;;
esac
