FROM python:3.11-alpine

# Set working directory
WORKDIR /app

# Install system dependencies needed for lxml
RUN apk add --no-cache \
    gcc \
    musl-dev \
    libxml2-dev \
    libxslt-dev

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the load generator script
COPY load_generator.py .

# Create directory for output files
RUN mkdir -p /app/results

# Set the entrypoint
ENTRYPOINT ["python3", "load_generator.py"]

# Default command (can be overridden)
CMD ["--help"]
