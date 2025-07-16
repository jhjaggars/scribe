# PowerShell script to build Scribe for Windows
# Run with: powershell -ExecutionPolicy Bypass -File build-windows.ps1

param(
    [switch]$GPU = $false,
    [switch]$Clean = $false,
    [string]$BuildType = "both"  # "cli", "gui", or "both"
)

Write-Host "Scribe Windows Build Script" -ForegroundColor Green
Write-Host "===========================" -ForegroundColor Green

# Check if we're on Windows
if ($PSVersionTable.Platform -ne "Win32NT" -and $PSVersionTable.Platform -ne $null) {
    Write-Host "ERROR: This script is designed for Windows only." -ForegroundColor Red
    exit 1
}

# Clean up previous builds if requested
if ($Clean) {
    Write-Host "Cleaning previous builds..." -ForegroundColor Yellow
    if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
    if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
    Write-Host "Cleanup complete." -ForegroundColor Green
}

# Check for Python
Write-Host "Checking Python installation..." -ForegroundColor Cyan
try {
    $pythonVersion = python --version
    Write-Host "Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python not found. Please install Python 3.10+ and add it to PATH." -ForegroundColor Red
    exit 1
}

# Check for uv
Write-Host "Checking uv installation..." -ForegroundColor Cyan
try {
    $uvVersion = uv --version
    Write-Host "Found: $uvVersion" -ForegroundColor Green
} catch {
    Write-Host "ERROR: uv not found. Please install uv package manager." -ForegroundColor Red
    Write-Host "Install with: pip install uv" -ForegroundColor Yellow
    exit 1
}

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Cyan
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install dependencies." -ForegroundColor Red
    exit 1
}

# Install PyInstaller if not present
Write-Host "Installing PyInstaller..." -ForegroundColor Cyan
uv add --dev pyinstaller
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install PyInstaller." -ForegroundColor Red
    exit 1
}

# GPU-specific setup
if ($GPU) {
    Write-Host "Setting up GPU support..." -ForegroundColor Cyan
    # Install CUDA-enabled PyTorch if needed
    Write-Host "Note: Ensure CUDA runtime is installed for GPU support." -ForegroundColor Yellow
}

# Build CLI version
if ($BuildType -eq "cli" -or $BuildType -eq "both") {
    Write-Host "Building CLI version..." -ForegroundColor Cyan
    uv run pyinstaller scribe-cli.spec --clean
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to build CLI version." -ForegroundColor Red
        exit 1
    }
    Write-Host "CLI build complete: dist/scribe-cli/" -ForegroundColor Green
}

# Build GUI version
if ($BuildType -eq "gui" -or $BuildType -eq "both") {
    Write-Host "Building Windows GUI version..." -ForegroundColor Cyan
    uv run pyinstaller scribe-gui-windows.spec --clean
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to build GUI version." -ForegroundColor Red
        exit 1
    }
    Write-Host "GUI build complete: dist/scribe-gui-windows/" -ForegroundColor Green
}

# Create distribution package
Write-Host "Creating distribution package..." -ForegroundColor Cyan
$distDir = "dist/scribe-windows-package"
if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }
New-Item -ItemType Directory -Path $distDir | Out-Null

# Copy built executables
if ($BuildType -eq "cli" -or $BuildType -eq "both") {
    Copy-Item -Recurse "dist/scribe-cli" "$distDir/"
}
if ($BuildType -eq "gui" -or $BuildType -eq "both") {
    Copy-Item -Recurse "dist/scribe-gui-windows" "$distDir/"
}

# Create batch files for easy execution
if ($BuildType -eq "cli" -or $BuildType -eq "both") {
    @"
@echo off
echo Starting Scribe CLI...
cd /d "%~dp0scribe-cli"
scribe-cli.exe %*
pause
"@ | Out-File -FilePath "$distDir/run-scribe-cli.bat" -Encoding ASCII
}

if ($BuildType -eq "gui" -or $BuildType -eq "both") {
    @"
@echo off
echo Starting Scribe Windows GUI...
cd /d "%~dp0scribe-gui-windows"
start scribe-gui-windows.exe
"@ | Out-File -FilePath "$distDir/run-scribe-gui.bat" -Encoding ASCII
}

# Create README
$readmeContent = @"
Scribe - Speech-to-Text for Windows
==================================

This package contains Scribe executables built for Windows.

Contents:
"@

if ($BuildType -eq "cli" -or $BuildType -eq "both") {
    $readmeContent += @"

- scribe-cli/: Command-line version
  - Run with: run-scribe-cli.bat
  - Direct exe: scribe-cli/scribe-cli.exe

"@
}

if ($BuildType -eq "gui" -or $BuildType -eq "both") {
    $readmeContent += @"

- scribe-gui-windows/: Windows GUI version  
  - Run with: run-scribe-gui.bat
  - Direct exe: scribe-gui-windows/scribe-gui-windows.exe

"@
}

$readmeContent += @"

Usage:
- Double-click the .bat files to run
- Or run the .exe files directly from their folders
- For CLI help: scribe-cli.exe --help

Features:
- Real-time speech-to-text transcription
- Voice Activity Detection (VAD)
- Multiple Whisper model sizes (tiny to large)
- Native Windows audio support (no FFmpeg required)
- GPU acceleration support (if CUDA is installed)

Requirements:
- Windows 10/11
- Microphone access
- Optional: NVIDIA GPU with CUDA for faster processing

Build info:
- Build type: $BuildType
- GPU support: $GPU
- Build date: $(Get-Date -Format "yyyy-MM-dd HH:mm")
"@

$readmeContent | Out-File -FilePath "$distDir/README.txt" -Encoding UTF8

Write-Host "" -ForegroundColor Green
Write-Host "Build completed successfully!" -ForegroundColor Green
Write-Host "Package location: $distDir" -ForegroundColor Yellow
Write-Host "" -ForegroundColor Green

# Show package contents
Write-Host "Package contents:" -ForegroundColor Cyan
Get-ChildItem $distDir -Recurse | Select-Object Name, Length, LastWriteTime | Format-Table

Write-Host "To test the build:" -ForegroundColor Yellow
if ($BuildType -eq "cli" -or $BuildType -eq "both") {
    Write-Host "  CLI: $distDir/run-scribe-cli.bat" -ForegroundColor White
}
if ($BuildType -eq "gui" -or $BuildType -eq "both") {
    Write-Host "  GUI: $distDir/run-scribe-gui.bat" -ForegroundColor White
}