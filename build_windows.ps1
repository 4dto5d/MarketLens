param(
    [switch]$ReuseBuildEnvironment,
    [string]$ExistingPython = ""
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildVenv = Join-Path $ProjectRoot ".build-venv"
$PythonExe = if ($ExistingPython) { $ExistingPython } else { Join-Path $BuildVenv "Scripts\python.exe" }
$DistDir = Join-Path $ProjectRoot "dist\MarketLensLocal"

try {
    Set-Location $ProjectRoot

    if ((Test-Path $BuildVenv) -and -not $ReuseBuildEnvironment -and -not $ExistingPython) {
        throw "The build environment already exists. Use -ReuseBuildEnvironment or supply -ExistingPython."
    }

    if (-not (Test-Path -LiteralPath $PythonExe)) {
        if ($ExistingPython) { throw "ExistingPython does not exist: $ExistingPython" }
        Write-Host "Creating clean build environment..." -ForegroundColor Cyan
        py -3.11 -m venv $BuildVenv
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python build environment." }
        & $PythonExe -m pip install -r requirements-dev.txt
        if ($LASTEXITCODE -ne 0) { throw "Could not install build requirements." }
    }

    Write-Host "Running tests..." -ForegroundColor Cyan
    & $PythonExe -m pytest
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; Windows packaging was stopped." }

    Write-Host "Running Ruff..." -ForegroundColor Cyan
    & $PythonExe -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed; Windows packaging was stopped." }

    Write-Host "Building executable..." -ForegroundColor Cyan
    if (Test-Path -LiteralPath $DistDir) { throw "Generated output already exists; preserve or remove it explicitly: $DistDir" }

    & $PythonExe -m PyInstaller `
        --noconfirm `
        --windowed `
        --name MarketLensLocal `
        --icon "local_presence_miner\assets\app-icon.ico" `
        --version-file "packaging\windows\version_info.txt" `
        --collect-all playwright `
        --distpath dist `
        --add-data "local_presence_miner\templates;local_presence_miner\templates" `
        --add-data "local_presence_miner\assets;local_presence_miner\assets" `
        --add-data "sample_data;sample_data" `
        app.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    Copy-Item -LiteralPath "packaging\windows\README.md" -Destination (Join-Path $DistDir "README.md") -Force
    Copy-Item -LiteralPath "README.md" -Destination (Join-Path $DistDir "FULL_README.md") -Force
    Copy-Item -LiteralPath "V0112_PASS1_INTEGRITY.md" -Destination $DistDir -Force
    Copy-Item -LiteralPath "V0113_STATE_WORKFLOW_HARDENING.md" -Destination $DistDir -Force
    Copy-Item -LiteralPath "KNOWN_DEFERRED_ISSUES.md" -Destination $DistDir -Force
    Copy-Item -LiteralPath "packaging\release_identity.json" -Destination (Join-Path $DistDir "RELEASE_IDENTITY.json") -Force
    Copy-Item -LiteralPath "packaging\windows\START_MARKETLENS_LOCAL.bat" -Destination $DistDir -Force
    Copy-Item -LiteralPath "packaging\windows\TROUBLESHOOTING.txt" -Destination $DistDir -Force
    Copy-Item -LiteralPath "CHANGELOG.md" -Destination $DistDir -Force
    Write-Host "Build complete: $DistDir" -ForegroundColor Green
    Write-Host "Run: $(Join-Path $DistDir 'MarketLensLocal.exe')" -ForegroundColor Green
}
catch {
    Write-Host "Build failed." -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host "Press any key to close..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}
