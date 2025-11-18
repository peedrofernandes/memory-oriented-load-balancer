Test scenarios

Global parameters
- Total timeout seconds: 30
- Total catalog videos: 12
- Total distinct resolutions (qualities): 5

================================================================================================================================

# Scenario 1 - Low concurrency, heterogeneous

- Total concurrent users: 100 (10 * 10)
- Server distribution: heterogeneous
  - Server 1: 4096MB RAM, 1024MB/s
  - Server 2: 2048MB RAM, 512MB/s
  - Server 3: 1024MB RAM, 256MB/s
  - Server 4: 512MB RAM, 128MB/s
  - Server 5: 256MB RAM, 64MB/s
  - Server 6: 128MB RAM, 32MB/s
  - Server 7: 64MB RAM, 16MB/s
  - Server 8: 32MB RAM, 8MB/s


================================================================================================================================

# Scenario 2 - Low concurrency, homogeneous

- Total concurrent users: 100 (10 * 10)
- Server distribution: homogeneous
  - Server 1: 1024MB RAM, 256MB/s
  - Server 2: 1024MB RAM, 256MB/s
  - Server 3: 1024MB RAM, 256MB/s
  - Server 4: 1024MB RAM, 256MB/s
  - Server 5: 1024MB RAM, 256MB/s
  - Server 6: 1024MB RAM, 256MB/s
  - Server 7: 1024MB RAM, 256MB/s
  - Server 8: 1024MB RAM, 256MB/s

================================================================================================================================

# Scenario 3 - High concurrency, heterogeneous

- Total concurrent users: 1000 (100 * 10)
- Server distribution: heterogeneous
  - Server 1: 4096MB RAM, 1024MB/s
  - Server 2: 2048MB RAM, 512MB/s
  - Server 3: 1024MB RAM, 256MB/s
  - Server 4: 512MB RAM, 128MB/s
  - Server 5: 256MB RAM, 64MB/s
  - Server 6: 128MB RAM, 32MB/s
  - Server 7: 64MB RAM, 16MB/s
  - Server 8: 32MB RAM, 8MB/s

================================================================================================================================

# Scenario 4

- Total concurrent users: 1000 (100 * 10)
- Server distribution: homogeneous
  - Server 1: 1024MB RAM, 256MB/s
  - Server 2: 1024MB RAM, 256MB/s
  - Server 3: 1024MB RAM, 256MB/s
  - Server 4: 1024MB RAM, 256MB/s
  - Server 5: 1024MB RAM, 256MB/s
  - Server 6: 1024MB RAM, 256MB/s
  - Server 7: 1024MB RAM, 256MB/s
  - Server 8: 1024MB RAM, 256MB/s