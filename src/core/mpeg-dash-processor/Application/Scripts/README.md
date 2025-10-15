# MPEG-DASH Processor Scripts

This folder contains scripts to run the MPEG-DASH Processor server in different ways.

## Available Scripts

### Direct .NET Execution
- **`run-server.bat`** - Windows batch script to run the server using `dotnet run`
- **`run-server.ps1`** - PowerShell script to run the server using `dotnet run`

### Docker Execution
- **`run-server.sh`** - Shell script to build and run the server using Docker
- **`GenerateMpegDash.sh`** - Existing script for MPEG-DASH generation

## Docker Compose

The `docker-compose.yml` file in the parent directory (`../docker-compose.yml`) sets up 8 containers running on different ports:

- Container 1: HTTP 8100, HTTPS 8101
- Container 2: HTTP 8200, HTTPS 8201  
- Container 3: HTTP 8300, HTTPS 8301
- Container 4: HTTP 8400, HTTPS 8401
- Container 5: HTTP 8500, HTTPS 8501
- Container 6: HTTP 8600, HTTPS 8601
- Container 7: HTTP 8700, HTTPS 8701
- Container 8: HTTP 8800, HTTPS 8801

**Port Pattern**: `8X00` for HTTP and `8X01` for HTTPS (where X = container number)

All containers share the same `wwwroot` folder via volume mounting (read-only).

## Usage

### Run single instance with .NET:
```bash
# From anywhere in the project
./Scripts/run-server.bat     # Windows
./Scripts/run-server.ps1     # PowerShell
./Scripts/run-server.sh      # Linux/macOS (using Docker)
```

### Run multiple instances with Docker Compose:
```bash
# From the Application directory
docker-compose up --build
```

### Run specific number of containers:
```bash
# Run only first 3 containers
docker-compose up --build mpeg-dash-processor-1 mpeg-dash-processor-2 mpeg-dash-processor-3
```

## Notes

- All scripts automatically navigate to the correct directory
- The Docker version exposes ports 8080/8081 by default
- Docker Compose version runs 8 instances on ports 8080-8095
- All instances serve the same MPEG-DASH content from the shared `wwwroot` folder
