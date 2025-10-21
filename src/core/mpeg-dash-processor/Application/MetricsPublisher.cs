using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using MQTTnet;
using MQTTnet.Client;
using MQTTnet.Extensions.ManagedClient;

public sealed class MetricsPublisher : BackgroundService
{
    private readonly ILogger<MetricsPublisher> _logger;
    private readonly IManagedMqttClient _managedClient;
    private readonly RequestCounter _requestCounter;

    private readonly string _mqttBrokerHost;
    private readonly int _mqttBrokerPort;
    private readonly TimeSpan _publishInterval;
    private readonly string _serverSocket;

    private readonly ulong _memoryLimitMb;
    private readonly ulong _readDiskLimitMbps;

    // cgroup v2 file paths inside container namespace
    private const string CgroupIoStatPath = "/sys/fs/cgroup/io.stat";
    private const string CgroupMemoryCurrentPath = "/sys/fs/cgroup/memory.current";

    // Rolling state to compute read/s
    private ulong _lastTotalReadBytes;
    private DateTimeOffset _lastSampleTime;

    public MetricsPublisher(ILogger<MetricsPublisher> logger, RequestCounter requestCounter)
    {
        _logger = logger;
        _requestCounter = requestCounter;

        _memoryLimitMb = ulong.Parse(Environment.GetEnvironmentVariable("MEMORY_LIMIT_MB") ?? throw new Exception("MEMORY_LIMIT_MB environment variable is required"));
        _readDiskLimitMbps = ulong.Parse(Environment.GetEnvironmentVariable("READ_DISK_LIMIT_MBPS") ?? throw new Exception("READ_DISK_LIMIT_MBPS environment variable is required"));

        // Prefer single env var for broker to minimize parameters
        // Default connects to host machine broker via host.docker.internal
        var brokerUrl = Environment.GetEnvironmentVariable("MQTT_BROKER_URL") ?? "mqtt://host.docker.internal:1883";
        ParseBrokerUrl(brokerUrl, out _mqttBrokerHost, out _mqttBrokerPort);

        // Publishing interval (seconds)
        if (!int.TryParse(Environment.GetEnvironmentVariable("METRICS_PUBLISH_INTERVAL_SECONDS"), out var intervalSeconds))
        {
            intervalSeconds = 10;
        }
        _publishInterval = TimeSpan.FromSeconds(Math.Max(1, intervalSeconds));

        // Prefer reusing container identity and known internal port for the server socket
        // Default will be "<container_name>:8080"
        var defaultSocket = $"{Environment.MachineName}:8080";
        _serverSocket = Environment.GetEnvironmentVariable("SERVER_SOCKET") ?? defaultSocket;

        // Setup managed MQTT client (auto-reconnect, queueing)
        var mqttFactory = new MqttFactory();
        _managedClient = mqttFactory.CreateManagedMqttClient();

        _managedClient.ConnectedAsync += args =>
        {
            _logger.LogInformation("Connected to MQTT broker {Host}:{Port}", _mqttBrokerHost, _mqttBrokerPort);
            return Task.CompletedTask;
        };

        _managedClient.DisconnectedAsync += args =>
        {
            _logger.LogWarning("Disconnected from MQTT broker: {Reason}", args.Reason);
            return Task.CompletedTask;
        };
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var clientOptions = new MqttClientOptionsBuilder()
            .WithClientId($"dash-processor-{Environment.MachineName}")
            .WithTcpServer(_mqttBrokerHost, _mqttBrokerPort)
            .Build();

        var managedOptions = new ManagedMqttClientOptionsBuilder()
            .WithClientOptions(clientOptions)
            .WithAutoReconnectDelay(TimeSpan.FromSeconds(5))
            .Build();

        await _managedClient.StartAsync(managedOptions);

        // Initialize baseline for rate computation
        _lastTotalReadBytes = await ReadTotalReadBytesAsync();
        _lastSampleTime = DateTimeOffset.UtcNow;

        while (!stoppingToken.IsCancellationRequested)
        {
            try
            {
                var now = DateTimeOffset.UtcNow;
                var totalReadBytes = await ReadTotalReadBytesAsync();
                var memoryCurrentBytes = await ReadMemoryCurrentAsync();

                var elapsed = (now - _lastSampleTime).TotalSeconds;
                double readBytesPerSec = 0;
                if (elapsed > 0)
                {
                    var delta = (long)totalReadBytes - (long)_lastTotalReadBytes;
                    if (delta < 0) delta = 0; // handle counter reset
                    readBytesPerSec = delta / elapsed;
                }

                _lastTotalReadBytes = totalReadBytes;
                _lastSampleTime = now;

                var normalized_memory_current_bytes = Math.Clamp((double)memoryCurrentBytes / (_memoryLimitMb * 1024 * 1024), 0.0, 1.0);
                var normalized_read_bytes_per_sec = Math.Clamp(readBytesPerSec / (_readDiskLimitMbps * 1024 * 1024), 0.0, 1.0);

                var payload = new
                {
                    server_socket = _serverSocket,
                    memory_current = normalized_memory_current_bytes,
                    disk_read = normalized_read_bytes_per_sec,
                    active_request_count = _requestCounter.Get(),
                    timestamp_unix = now.ToUnixTimeSeconds(),
                };

                var json = JsonSerializer.Serialize(payload);
                var message = new MqttApplicationMessageBuilder()
                    .WithTopic("loadbalancer/metrics")
                    .WithPayload(json)
                    .WithQualityOfServiceLevel(MQTTnet.Protocol.MqttQualityOfServiceLevel.AtLeastOnce)
                    .Build();

                await _managedClient.EnqueueAsync(message);
                _logger.LogDebug("Published metrics: {Json}", json);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to collect/publish metrics");
            }

            try
            {
                await Task.Delay(_publishInterval, stoppingToken);
            }
            catch (TaskCanceledException)
            {
                break;
            }
        }

        await _managedClient.StopAsync();
    }

    private static void ParseBrokerUrl(string url, out string host, out int port)
    {
        // Accept formats like: mqtt://host:1883 or host:1883 or just host
        host = "host.docker.internal";
        port = 1883;

        if (string.IsNullOrWhiteSpace(url)) return;

        try
        {
            if (!url.Contains("://"))
            {
                url = $"mqtt://{url}";
            }
            var uri = new Uri(url);
            host = uri.Host;
            if (uri.Port > 0) port = uri.Port;
        }
        catch
        {
            // Fallback to defaults if parsing fails
        }
    }

    private static async Task<ulong> ReadTotalReadBytesAsync()
    {
        // cgroup v2 io.stat example lines per device:
        // 8:0 rbytes=1234 wbytes=5678 rios=10 wios=20 dbytes=0 dios=0
        // Sum rbytes across all lines
        try
        {
            if (!File.Exists(CgroupIoStatPath)) return 0;
            var lines = await File.ReadAllLinesAsync(CgroupIoStatPath);
            ulong total = 0;
            foreach (var line in lines)
            {
                var parts = line.Split(' ', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                foreach (var part in parts)
                {
                    if (part.StartsWith("rbytes="))
                    {
                        var valueStr = part.Substring("rbytes=".Length);
                        if (ulong.TryParse(valueStr, out var v)) total += v;
                    }
                }
            }
            return total;
        }
        catch
        {
            return 0;
        }
    }

    private static async Task<ulong> ReadMemoryCurrentAsync()
    {
        try
        {
            if (!File.Exists(CgroupMemoryCurrentPath)) return 0;
            var text = await File.ReadAllTextAsync(CgroupMemoryCurrentPath, Encoding.UTF8);
            if (ulong.TryParse(text.Trim(), out var value)) return value;
            return 0;
        }
        catch
        {
            return 0;
        }
    }
}


