FROM python:3.11-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the script and config
COPY stalls_per_frame.py .
COPY config.json .

# Set the entrypoint to run the script with config
ENTRYPOINT ["python", "stalls_per_frame.py", "--config", "config.json"]


