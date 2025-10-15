Write-Host "🌍 Starting MPEG-DASH Processor Server..." -ForegroundColor Green
Write-Host ""
Write-Host "Server will be available at:" -ForegroundColor Yellow
Write-Host "  • Main: http://localhost:5073" -ForegroundColor Cyan
Write-Host "  • Health: http://localhost:5073/health" -ForegroundColor Cyan
Write-Host "  • Test Page: http://localhost:5073/test" -ForegroundColor Cyan
Write-Host "  • Advanced Test: http://localhost:5073/test-dash.html" -ForegroundColor Cyan
Write-Host "  • File Browser: http://localhost:5073/earth" -ForegroundColor Cyan
Write-Host "  • DASH Info: http://localhost:5073/dash-info" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop the server" -ForegroundColor Red
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location (Join-Path $ScriptDir "..")
dotnet run
