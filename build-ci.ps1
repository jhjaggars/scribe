# CI-friendly build script for GitHub Actions
# Simplified version of build-windows.ps1 for automated builds

param(
    [string]$BuildType = "both",  # "cli", "gui", or "both"
    [switch]$GPU = $false,
    [string]$Version = "dev"
)

Write-Host "Scribe CI Build Script" -ForegroundColor Green
Write-Host "======================" -ForegroundColor Green
Write-Host "Build Type: $BuildType" -ForegroundColor Cyan
Write-Host "GPU Support: $GPU" -ForegroundColor Cyan
Write-Host "Version: $Version" -ForegroundColor Cyan

# Function to handle errors
function Test-LastExitCode {
    param([string]$Operation)
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $Operation failed with exit code $LASTEXITCODE" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# Clean previous builds
Write-Host "Cleaning previous builds..." -ForegroundColor Yellow
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

# Verify Python and uv are available
Write-Host "Checking dependencies..." -ForegroundColor Cyan
python --version
Test-LastExitCode "Python check"

uv --version
Test-LastExitCode "uv check"

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
uv sync
Test-LastExitCode "Dependencies installation"

# Install PyInstaller
Write-Host "Installing PyInstaller..." -ForegroundColor Cyan
uv add --dev "pyinstaller>=6.0.0"
Test-LastExitCode "PyInstaller installation"

# Install GPU dependencies if requested
if ($GPU) {
    Write-Host "Installing GPU dependencies..." -ForegroundColor Cyan
    uv add nvidia-cudnn-cu12
    Test-LastExitCode "GPU dependencies installation"
}

# Build CLI if requested
if ($BuildType -eq "cli" -or $BuildType -eq "both") {
    Write-Host "Building CLI executable..." -ForegroundColor Cyan
    uv run pyinstaller scribe-cli.spec --clean --noconfirm
    Test-LastExitCode "CLI build"
    
    if (Test-Path "dist/scribe-cli/scribe-cli.exe") {
        Write-Host "✓ CLI executable built successfully" -ForegroundColor Green
    } else {
        Write-Host "✗ CLI executable not found" -ForegroundColor Red
        exit 1
    }
}

# Build GUI if requested
if ($BuildType -eq "gui" -or $BuildType -eq "both") {
    Write-Host "Building GUI executable..." -ForegroundColor Cyan
    uv run pyinstaller scribe-gui-windows.spec --clean --noconfirm
    Test-LastExitCode "GUI build"
    
    if (Test-Path "dist/scribe-gui-windows/scribe-gui-windows.exe") {
        Write-Host "✓ GUI executable built successfully" -ForegroundColor Green
    } else {
        Write-Host "✗ GUI executable not found" -ForegroundColor Red
        exit 1
    }
}

Write-Host "Build completed successfully!" -ForegroundColor Green

# List built files
Write-Host "Built files:" -ForegroundColor Cyan
Get-ChildItem dist -Recurse -Name "*.exe" | ForEach-Object {
    $size = (Get-Item "dist/$_").Length / 1MB
    Write-Host "  $_ ($([math]::Round($size, 1)) MB)" -ForegroundColor White
}