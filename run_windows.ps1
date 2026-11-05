$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

try {
    Set-Location $ProjectRoot

    if (-not (Test-Path $PythonExe)) {
        Write-Host "Creating virtual environment..." -ForegroundColor Cyan
        py -3.11 -m venv $VenvPath
    }

    Write-Host "Installing requirements..." -ForegroundColor Cyan
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -r requirements.txt

    Write-Host "Launching Local Presence Miner..." -ForegroundColor Green
    Write-Host "Runtime data: $env:LOCALAPPDATA\LocalPresenceMiner" -ForegroundColor DarkCyan
    & $PythonExe app.py
}
catch {
    Write-Host "Local Presence Miner failed to start." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Press any key to close..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}
