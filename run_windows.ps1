$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11+ from https://www.python.org/downloads/windows/ and enable the Python launcher."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating the DriveLens virtual environment..."
    py -m venv .venv
}

Write-Host "Installing or verifying DriveLens dependencies..."
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt
Write-Host "Starting DriveLens..."
& ".venv\Scripts\python.exe" "main.py"
