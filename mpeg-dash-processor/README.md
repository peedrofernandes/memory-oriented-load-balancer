# MPEG-DASH Processor Server

A .NET 8 web application that serves MPEG-DASH video streams with proper HTTP headers, CORS support, and caching optimizations.

## Features

- ✅ MPEG-DASH manifest (.mpd) serving with correct MIME types
- ✅ Video/audio segment (.m4s) serving with aggressive caching
- ✅ HTTP Range request support for adaptive streaming
- ✅ CORS headers for cross-origin requests
- ✅ Directory browsing for easy file inspection
- ✅ Built-in test pages with dash.js player
- ✅ Comprehensive logging and debugging
- ✅ Docker support

## Quick Start

### Prerequisites

- .NET 8 SDK
- Docker (optional)

### Running the Application

1. **Using .NET CLI:**
   ```bash
   cd Application
   dotnet run
   ```

2. **Using Docker:**
   ```bash
   docker build -t mpeg-dash-processor .
   docker run -p 8080:8080 mpeg-dash-processor
   ```

The server will start on `http://localhost:5073` (or the configured port).

## Available Endpoints

### Core DASH Endpoints

- **Manifest:** `http://localhost:5073/Static/Earth/manifest.mpd`
- **Video Segments:** `http://localhost:5073/Static/Earth/chunk-0-00001.m4s` (and others)
- **Audio Segments:** `http://localhost:5073/Static/Earth/chunk-1-00001.m4s` (and others)
- **Initialization Files:** `http://localhost:5073/Static/Earth/init-0.mp4`, `init-1.mp4`

### Utility Endpoints

- **Health Check:** `http://localhost:5073/health`
- **DASH Info:** `http://localhost:5073/dash-info`
- **File Browser:** `http://localhost:5073/earth`
- **Simple Test Page:** `http://localhost:5073/test`
- **Advanced Test Page:** `http://localhost:5073/test-dash.html`

## Testing the DASH Stream

### 1. Using the Built-in Test Pages

Visit `http://localhost:5073/test-dash.html` for the most comprehensive testing experience. This page includes:

- Real-time logging of DASH events
- Player statistics and metrics
- Error handling and debugging
- Quality switching information

### 2. Using External Players

#### VLC Media Player
```
Open VLC → Media → Open Network Stream → Enter: http://localhost:5073/Static/Earth/manifest.mpd
```

#### FFmpeg
```bash
ffplay http://localhost:5073/Static/Earth/manifest.mpd
```

#### Browser Native Support
Some modern browsers support DASH natively. Visit `http://localhost:5073/test` for a simple test.

### 3. Using dash.js in Your Own Application

```html
<!DOCTYPE html>
<html>
<head>
    <script src="https://cdn.dashjs.org/latest/dash.all.min.js"></script>
</head>
<body>
    <video id="videoPlayer" controls></video>
    <script>
        const player = dashjs.MediaPlayer().create();
        player.initialize(document.getElementById('videoPlayer'), 
                         'http://localhost:5073/Static/Earth/manifest.mpd', false);
    </script>
</body>
</html>
```

## Earth Video Specifications

The included Earth video is a 30-second sample with the following characteristics:

- **Duration:** 30 seconds
- **Video:** 1920x1080 H.264 (AVC) at ~936 kbps
- **Audio:** 48kHz Stereo AAC at 128 kbps
- **Segments:** 7 video segments, 8 audio segments
- **Segment Duration:** ~4 seconds each

## Configuration

### MIME Types
The server automatically serves the correct MIME types:
- `.mpd` → `application/dash+xml`
- `.m4s` → `video/iso.segment`
- `.mp4` → `video/mp4`
- `.m4a` → `audio/mp4`

### Caching Strategy
- **Manifest (.mpd):** No caching (always fresh)
- **Segments (.m4s, .mp4, .m4a):** 1 year cache with immutable flag

### CORS Headers
The server includes CORS headers to allow cross-origin requests:
- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Headers: *`
- `Access-Control-Allow-Methods: *`
- `Access-Control-Expose-Headers: Content-Length, Content-Range, Accept-Ranges`

## Troubleshooting

### Common Issues

1. **CORS Errors:** Ensure your client is making requests to the correct origin
2. **404 Errors:** Verify the file paths in the manifest match the actual file locations
3. **Playback Issues:** Check the browser console for DASH-related errors
4. **Range Request Issues:** Ensure your client supports HTTP Range requests

### Debugging

1. **Check Server Logs:** The application logs all requests and errors
2. **Use the Test Pages:** The built-in test pages provide detailed logging
3. **Verify File Access:** Use the `/earth` endpoint to browse available files
4. **Test Individual Files:** Try accessing segments directly to verify they're accessible

### Performance Optimization

- The server is configured for optimal DASH streaming performance
- Segments are cached aggressively to reduce server load
- HTTP Range requests are supported for efficient streaming
- CORS headers are optimized for web-based players

## Development

### Project Structure
```
Application/
├── Program.cs              # Main application configuration
├── wwwroot/
│   ├── Static/
│   │   └── Earth/          # DASH video files
│   │       ├── manifest.mpd
│   │       ├── init-*.mp4
│   │       └── chunk-*.m4s
│   └── test-dash.html      # Advanced test page
└── Properties/
    └── launchSettings.json # Development configuration
```

### Adding New DASH Content

1. Place your DASH files in `wwwroot/Static/`
2. Ensure the manifest (.mpd) file references correct paths
3. Verify all segments and initialization files are accessible
4. Test using the built-in test pages

## License

This project is part of a TCC-II research project at UDESC.
