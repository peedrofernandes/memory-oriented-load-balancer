FROM python:3.11-alpine

WORKDIR /app

RUN apk add --no-cache \
    gcc \
    musl-dev \
    libxml2-dev \
    libxslt-dev

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY load_generator.py .

RUN mkdir -p /app/results

ENTRYPOINT ["python3", "load_generator.py"]

CMD ["--help"]
