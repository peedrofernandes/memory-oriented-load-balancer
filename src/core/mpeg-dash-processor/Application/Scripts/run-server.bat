@echo off
echo Starting MPEG-DASH Processor Server...
echo.
echo Server will be available at:
echo   - Main: http://localhost:5073
echo   - Health: http://localhost:5073/health
echo   - Test Page: http://localhost:5073/test
echo   - Advanced Test: http://localhost:5073/test-dash.html
echo   - File Browser: http://localhost:5073/earth
echo   - DASH Info: http://localhost:5073/dash-info
echo.
echo Press Ctrl+C to stop the server
echo.
cd /d "%~dp0\.."
dotnet run
