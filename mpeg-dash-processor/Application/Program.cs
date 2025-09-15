using Microsoft.AspNetCore.StaticFiles;
using Microsoft.Extensions.FileProviders;

var builder = WebApplication.CreateBuilder(args);

// Add logging
builder.Logging.AddConsole();

// CORS: allow browsers/players to fetch from anywhere (tighten if needed)
builder.Services.AddCors(o => o.AddDefaultPolicy(p => p
    .AllowAnyOrigin()
    .AllowAnyHeader()
    .AllowAnyMethod()
    .WithExposedHeaders("Content-Length", "Content-Range", "Accept-Ranges")));

var app = builder.Build();

app.UseCors();

// Add middleware to handle HTTP Range requests for DASH segments
app.Use(async (context, next) =>
{
    var logger = context.RequestServices.GetRequiredService<ILogger<Program>>();
    
    // Log Range requests for debugging
    if (context.Request.Headers.ContainsKey("Range"))
    {
        logger.LogInformation("Range request: {Range} for {Path}", 
            context.Request.Headers["Range"], context.Request.Path);
    }
    
    await next();
});

// Static files with DASH MIME types + caching rules
var provider = new FileExtensionContentTypeProvider();
// DASH / CMAF common types
provider.Mappings[".mpd"] = "application/dash+xml";
provider.Mappings[".m4s"] = "video/iso.segment";   // many players also accept application/octet-stream
provider.Mappings[".mp4"] = "video/mp4";
provider.Mappings[".m4a"] = "audio/mp4";

// Serve Static folder contents at /Static path
app.UseStaticFiles(new StaticFileOptions
{
    FileProvider = new PhysicalFileProvider(Path.Combine(app.Environment.ContentRootPath, "wwwroot", "Static")),
    RequestPath = "/Static",
    ContentTypeProvider = provider,
    OnPrepareResponse = ctx =>
    {
        var path = ctx.File.PhysicalPath?.ToLowerInvariant() ?? "";
        var logger = ctx.Context.RequestServices.GetRequiredService<ILogger<Program>>();
        
        // Log requests for debugging
        logger.LogInformation("Serving Static file: {Path}", ctx.File.Name);
        
        // Cache segments aggressively; keep manifest fresh
        if (path.EndsWith(".mpd"))
        {
            ctx.Context.Response.Headers.CacheControl = "no-store, must-revalidate";
            ctx.Context.Response.Headers["Access-Control-Allow-Origin"] = "*";
        }
        else if (path.EndsWith(".m4s") || path.EndsWith(".mp4") || path.EndsWith(".m4a"))
        {
            ctx.Context.Response.Headers.CacheControl = "public, max-age=31536000, immutable";
            ctx.Context.Response.Headers["Access-Control-Allow-Origin"] = "*";
        }
    }
});

// Optional: Directory listing for Static folder (accessible via /browse)
app.UseDirectoryBrowser(new DirectoryBrowserOptions
{
    FileProvider = new PhysicalFileProvider(Path.Combine(app.Environment.ContentRootPath, "wwwroot", "Static")),
    RequestPath = "/browse"
});

// Note: StaticFileMiddleware + Kestrel support HTTP Range requests out of the box.
app.Run();
