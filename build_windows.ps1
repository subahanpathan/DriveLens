$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.11+ from https://www.python.org/downloads/windows/ and enable the Python launcher."
}

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating the DriveLens virtual environment..."
    py -m venv .venv
}

Write-Host "Installing build dependencies..."
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "Building the Windows application..."
& ".venv\Scripts\python.exe" -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name DriveLens `
    --collect-all PySide6 `
    --hidden-import send2trash `
    "main.py"

if (Test-Path "dist\DriveLens.zip") {
    Remove-Item "dist\DriveLens.zip" -Force
}
Compress-Archive -Path "dist\DriveLens\*" -DestinationPath "dist\DriveLens.zip" -Force
Write-Host ""
Write-Host "Build complete:"
Write-Host "  dist\DriveLens\DriveLens.exe"
Write-Host "  dist\DriveLens.zip"
