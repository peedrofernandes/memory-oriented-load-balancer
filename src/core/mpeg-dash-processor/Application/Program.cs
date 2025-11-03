using Microsoft.AspNetCore.StaticFiles;
using Microsoft.Extensions.FileProviders;
using Microsoft.Extensions.DependencyInjection;

var builder = WebApplication.CreateBuilder(args);

// Add logging
builder.Logging.AddConsole();

// Active request counter (singleton)
builder.Services.AddSingleton<RequestCounter>();

// Add background publisher service for metrics
builder.Services.AddHostedService<MetricsPublisher>();

// CORS: allow browsers/players to fetch from anywhere (tighten if needed)
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p
    .AllowAnyOrigin()
    .AllowAnyHeader()
    .AllowAnyMethod()
    .WithExposedHeaders("Content-Length", "Content-Range", "Accept-Ranges")));

// Compute required memory headroom (5% of max capacity) from environment
var memLimitEnv = Environment.GetEnvironmentVariable("MEMORY_LIMIT_MB")
    ?? throw new Exception("MEMORY_LIMIT_MB environment variable is required");
if (!long.TryParse(memLimitEnv, out var memoryLimitMb) || memoryLimitMb <= 0)
{
    throw new Exception("MEMORY_LIMIT_MB must be a positive integer");
}
var requiredHeadroomBytes = (memoryLimitMb * 1024L * 1024L) / 20L; // 5%

var app = builder.Build();

app.UseCors();

// Reject requests if server memory is critically low to avoid OOMs
app.Use(async (context, next) =>
{
    var logger = context.RequestServices.GetRequiredService<ILogger<Program>>();
    var gcInfo = GC.GetGCMemoryInfo();
    var headroom = gcInfo.TotalAvailableMemoryBytes - gcInfo.MemoryLoadBytes;

    if (headroom < requiredHeadroomBytes)
    {
        logger.LogWarning("Rejecting request due to low memory. Headroom={Headroom} bytes, Required={Required} bytes (limitMb={LimitMb})", headroom, requiredHeadroomBytes, memoryLimitMb);
        context.Response.StatusCode = 503; // Service Unavailable
        context.Response.Headers["Retry-After"] = "10"; // seconds
        context.Response.Headers["X-Memory-Headroom-Bytes"] = headroom.ToString();
        context.Response.Headers["X-Memory-Required-Bytes"] = requiredHeadroomBytes.ToString();
        context.Response.ContentType = "text/plain";
        await context.Response.WriteAsync("Service unavailable: insufficient memory, please retry later.");
        return;
    }

    await next();
});

// Count active requests
// Inline active request counting middleware (replaces RequestCountingMiddleware)
app.Use(async (context, next) =>
{
    var requestCounter = context.RequestServices.GetRequiredService<RequestCounter>();
    requestCounter.Increment();
    try
    {
        await next();
    }
    finally
    {
        requestCounter.Decrement();
    }
});

// Add middleware to handle Range requests for DASH segments
app.Use(async (context, next) =>
{
    var logger = context.RequestServices.GetRequiredService<ILogger<Program>>();
    
    // Log Range requests for debugging
    if (context.Request.Headers.ContainsKey("Range"))
    {
        logger.LogInformation("Range request: {Range} for {Path}", 
            context.Request.Headers["Range"], context.Request.Path);
    }
    
    // Add container identification header
    context.Response.Headers["X-Container-ID"] = Environment.MachineName;
    
    await next();
});

// Static files with DASH MIME types + caching rules
var provider = new FileExtensionContentTypeProvider();
// DASH / CMAF common types
provider.Mappings[".mpd"] = "application/dash+xml";
provider.Mappings[".m4s"] = "video/iso.segment";   // many players also accept application/octet-stream
provider.Mappings[".mp4"] = "video/mp4";
provider.Mappings[".m4a"] = "audio/mp4";

// Serve Static folder contents at root path for DASH compatibility
app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = new PhysicalFileProvider(Path.Combine(app.Environment.ContentRootPath, "wwwroot", "Static")),
    RequestPath = "",
    ContentTypeProvider = provider,
    OnPrepareResponse = ctx =>
    {
        var path = ctx.File.PhysicalPath?.ToLowerInvariant() ?? "";
        var logger = ctx.Context.RequestServices.GetRequiredService<ILogger<Program>>();
        
        // Standard DASH content headers
        ctx.Context.Response.Headers["Access-Control-Allow-Origin"] = "*";
        
        // Default HTTP caching behavior based on file type
        if (path.EndsWith(".mpd"))
        {
            ctx.Context.Response.Headers.CacheControl = "no-store, must-revalidate";
        }
        else if (path.EndsWith(".m4s") || path.EndsWith(".mp4") || path.EndsWith(".m4a"))
        {
            ctx.Context.Response.Headers.CacheControl = "public, max-age=31536000, immutable";
        }
    }
});

// Optional: Directory listing for Static folder (accessible via /browse)
app.UseDirectoryBrowser(new DirectoryBrowserOptions
{
    FileProvider = new PhysicalFileProvider(Path.Combine(app.Environment.ContentRootPath, "wwwroot", "Static")),
    RequestPath = "/browse"
});

// Add health check endpoint
app.MapGet("/health", () => "OK");

// Add a simple endpoint to list available videos directories
app.MapGet("/videos", async (HttpContext context) =>
{
    var staticPath = Path.Combine(app.Environment.ContentRootPath, "wwwroot", "Static");
    var directories = Directory.GetDirectories(staticPath)
        .Select(d => Path.GetFileName(d))
        .Where(d => d.StartsWith("video"))
        .OrderBy(d => d)
        .ToList();
    
    var response = $"Available videos directories: {string.Join(", ", directories)}";
    context.Response.ContentType = "text/plain";
    await context.Response.WriteAsync(response);
});

// Note: StaticFileMiddleware + Kestrel support HTTP Range requests out of the box.
app.Run();
