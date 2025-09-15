#!/bin/bash

echo "🌍 Starting MPEG-DASH Processor Server with Docker..."
echo ""
echo "Building Docker image..."

# Get the script directory and move to Application directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

cd "$APP_DIR"

# Build the Docker image
docker build -t mpeg-dash-processor .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed!"
    exit 1
fi

echo ""
echo "Starting container..."
echo ""

# Run the container
docker run -it --rm \
    --name mpeg-dash-processor \
    -p 8080:8080 \
    -p 8081:8081 \
    -v "$APP_DIR/wwwroot:/app/wwwroot" \
    mpeg-dash-processor

echo ""
echo "Server will be available at:"
echo "  • Main: http://localhost:8080"
echo "  • Health: http://localhost:8080/health"
echo "  • Test Page: http://localhost:8080/test"
echo "  • Advanced Test: http://localhost:8080/test-dash.html"
echo "  • File Browser: http://localhost:8080/earth"
echo "  • DASH Info: http://localhost:8080/dash-info"
echo ""
echo "Press Ctrl+C to stop the server"
