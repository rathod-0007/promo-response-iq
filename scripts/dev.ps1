# Starts the API (port 8000) and the web UI (port 5173) in two terminal windows. Run from the project root:
#   powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
$root = Split-Path -Parent $PSScriptRoot
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
Write-Host "API: http://localhost:8000/docs   UI: http://localhost:5173"
