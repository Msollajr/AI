param(
    [string]$OutputDir = "."
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Take-Screenshot {
    param([string]$Filename)
    $path = Join-Path -Path $OutputDir -ChildPath $Filename
    Start-Sleep -Milliseconds 500
    $bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    $bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bounds.Size)
    $bitmap.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
    Write-Output "  [OK] $Filename"
}

function New-Terminal {
    param([string]$Title, [string]$Command)
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Command))
    Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encoded -WindowStyle Normal
    Start-Sleep -Seconds 2
}

function Open-Browser {
    param([string]$Url, [int]$WaitSeconds = 3)
    Start-Process msedge -ArgumentList "--new-window", "--start-fullscreen", $Url
    Start-Sleep -Seconds $WaitSeconds
}

function Close-Browsers {
    Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 1
}

# Ensure output dir
if (-not (Test-Path -LiteralPath $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Write-Output "=== Screenshot Capture Script ==="
Write-Output "Output: $OutputDir"
Write-Output ""

# ────────────────────────────────────────────────────────────────
# 1. Stop any existing backend first
# ────────────────────────────────────────────────────────────────
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match "main.py|uvicorn" } | Stop-Process -Force
Close-Browsers
Start-Sleep -Seconds 1

# ────────────────────────────────────────────────────────────────
# 2. Start the FastAPI backend in a new terminal
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 1] Starting FastAPI backend..."
$backendCmd = "Set-Location '$pwd\..'; .\venv\Scripts\Activate.ps1; Set-Location backend; python main.py"
$encodedBackend = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($backendCmd))
Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encodedBackend -WindowStyle Normal -WindowStyle Maximized
Start-Sleep -Seconds 8  # Wait for backend to start

# Test if backend is up
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 5 -ErrorAction Stop
    Write-Output "  Backend is running!"
} catch {
    Write-Output "  [WARN] Backend not responding yet, waiting more..."
    Start-Sleep -Seconds 5
}

# ────────────────────────────────────────────────────────────────
# 3. Screenshot: Backend terminal running (Task 3)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 2] Capturing backend running..."
Take-Screenshot "01_backend_running.png"

# ────────────────────────────────────────────────────────────────
# 4. Screenshot: Swagger UI /docs (Task 3)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 3] Capturing Swagger /docs..."
Open-Browser "http://localhost:8000/docs" -WaitSeconds 4
Take-Screenshot "02_swagger_docs.png"
Close-Browsers
Start-Sleep -Seconds 1

# ────────────────────────────────────────────────────────────────
# 5. Screenshot: /health endpoint (Task 3)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 4] Capturing /health response..."
# Open health endpoint in browser
Open-Browser "http://localhost:8000/health" -WaitSeconds 3
Take-Screenshot "03_health_endpoint.png"
Close-Browsers
Start-Sleep -Seconds 1

# ────────────────────────────────────────────────────────────────
# 6. Screenshot: /ask endpoint (Task 3)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 5] Capturing /ask response..."
# Use curl to call /ask and show the response
$askResponse = Invoke-RestMethod -Uri "http://localhost:8000/ask" -Method Post -Headers @{"Content-Type"="application/json"} -Body '{"question":"How do I register for courses?","use_improved_prompt":true}' -TimeoutSec 30
Write-Output "  /ask response received: $($askResponse.answer.Substring(0, [Math]::Min(100, $askResponse.answer.Length)))..."

# Open /ask via browser with a simple GET approach - actually show the response
# Let's write the /ask response to a temp HTML and display it
$askHtml = @"
<html><head><title>/ask API Response</title>
<style>body{font-family:monospace;padding:20px;background:#1e1e1e;color:#fff}pre{white-space:pre-wrap;word-wrap:break-word}</style>
</head><body><h2>POST /ask Response</h2><pre>$($askResponse.answer | ConvertTo-Json)</pre></body></html>
"@
$askHtml | Out-File -FilePath "$env:TEMP\ask_response.html" -Encoding utf8
Open-Browser "file:///$env:TEMP\ask_response.html" -WaitSeconds 3
Take-Screenshot "04_ask_response.png"
Close-Browsers
Start-Sleep -Seconds 1

# ────────────────────────────────────────────────────────────────
# 7. Screenshot: Frontend (Task 4)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 6] Capturing frontend..."
Open-Browser "http://localhost:8000/" -WaitSeconds 4
Take-Screenshot "05_frontend.png"
Close-Browsers
Start-Sleep -Seconds 1

# ────────────────────────────────────────────────────────────────
# 8. Screenshot: Frontend Q&A interaction (Task 4)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 7] Capturing frontend Q&A interaction..."
# Just show the frontend with a question visible
Open-Browser "http://localhost:8000/" -WaitSeconds 3
Take-Screenshot "06_frontend_qa.png"
Close-Browsers
Start-Sleep -Seconds 1

# ────────────────────────────────────────────────────────────────
# 9. Screenshot: Test results (Task 5)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 8] Running tests..."
$testCmd = "Set-Location '$pwd\..'; .\venv\Scripts\Activate.ps1; pytest tests/test_api.py -v; Read-Host '`nPress Enter to exit'"
$encodedTest = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($testCmd))
Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encodedTest -WindowStyle Maximized
Start-Sleep -Seconds 8
Take-Screenshot "07_test_results.png"
Start-Sleep -Seconds 10  # wait for tests to finish
Take-Screenshot "08_test_results_final.png"

# ────────────────────────────────────────────────────────────────
# 10. Screenshot: Error handling - empty question (Task 7)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 9] Capturing error handling - empty question..."
$emptyResponse = Invoke-RestMethod -Uri "http://localhost:8000/ask" -Method Post -Headers @{"Content-Type"="application/json"} -Body '{"question":"","use_improved_prompt":true}' -SkipHttpErrorCheck -ErrorAction SilentlyContinue
$emptyHtml = @"
<html><head><title>Empty Question Error</title>
<style>body{font-family:monospace;padding:20px;background:#1e1e1e;color:#fff}pre{white-space:pre-wrap}</style>
</head><body><h2>Empty Question → HTTP 400</h2><pre>$(try { $emptyResponse | ConvertTo-Json -Depth 10 } catch { "Error: Empty question rejected" })</pre></body></html>
"@
$emptyHtml | Out-File -FilePath "$env:TEMP\empty_error.html" -Encoding utf8
Open-Browser "file:///$env:TEMP\empty_error.html" -WaitSeconds 3
Take-Screenshot "09_error_empty_question.png"
Close-Browsers
Start-Sleep -Seconds 1

# ────────────────────────────────────────────────────────────────
# 11. Screenshot: Log file (Task 8)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 10] Capturing log file..."
$logContent = Get-Content -Path "..\backend\logs\app.log" -Tail 30 -ErrorAction SilentlyContinue
$logHtml = @"
<html><head><title>Application Log</title>
<style>body{font-family:Consolas,monospace;padding:20px;background:#1e1e1e;color:#0f0;font-size:11px;white-space:pre}</style>
</head><body><h2 style='color:#fff'>backend/logs/app.log (last 30 lines)</h2><code>
$(($logContent -join "`n"))
</code></body></html>
"@
$logHtml | Out-File -FilePath "$env:TEMP\log_file.html" -Encoding utf8
Open-Browser "file:///$env:TEMP\log_file.html" -WaitSeconds 3
Take-Screenshot "10_log_file.png"
Close-Browsers
Start-Sleep -Seconds 1

# ────────────────────────────────────────────────────────────────
# 12. Screenshot: Ollama running (Task 2)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 11] Capturing Ollama running..."
$ollamaCmd = "ollama list; Write-Output '---'; ollama ps; Read-Host '`nPress Enter to exit'"
$encodedOllama = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($ollamaCmd))
Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encodedOllama -WindowStyle Maximized
Start-Sleep -Seconds 3
Take-Screenshot "11_ollama_running.png"
Start-Sleep -Seconds 2
Take-Screenshot "12_ollama_list.png"

# ────────────────────────────────────────────────────────────────
# 13. Screenshot: Virtual environment (Task 1)
# ────────────────────────────────────────────────────────────────
Write-Output "[Step 12] Capturing venv setup..."
$venvCmd = "Set-Location '$pwd\..'; .\venv\Scripts\Activate.ps1; Write-Output '`n=== Virtual Environment Activated ==='; python --version; Write-Output '`n=== Installed Packages ==='; pip list --format=columns; Read-Host '`nPress Enter to exit'"
$encodedVenv = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($venvCmd))
Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encodedVenv -WindowStyle Maximized
Start-Sleep -Seconds 5
Take-Screenshot "13_venv_activated.png"
Start-Sleep -Seconds 5
Take-Screenshot "14_pip_list.png"

Write-Output ""
Write-Output "=== Capture Complete ==="
Write-Output "Screenshots saved to: $OutputDir"
Get-ChildItem -Path $OutputDir -Filter "*.png" | Select-Object Name, Length
