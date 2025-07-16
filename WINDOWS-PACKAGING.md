# Windows Packaging Guide for Scribe

This guide explains how to package Scribe for Windows distribution.

## Overview

Scribe for Windows uses:
- **Native audio recording**: `sounddevice` library (no FFmpeg dependency)
- **Windows-native GUI**: `tkinter` (built into Python)
- **PyInstaller**: For creating standalone executables
- **CUDA support**: Optional GPU acceleration

## Quick Start

### Prerequisites

1. **Windows 10/11**
2. **Python 3.10+** installed and in PATH
3. **uv package manager** (or pip)
4. **Visual Studio C++ Redistributable** (for some dependencies)

### Build Commands

```bash
# Build both CLI and GUI versions
.\build-windows.bat

# Build specific version
.\build-windows.bat cli     # CLI only
.\build-windows.bat gui     # GUI only

# Or use PowerShell (more features)
.\build-windows.ps1 -BuildType both
.\build-windows.ps1 -BuildType cli -GPU  # With GPU support
```

## Detailed Build Process

### 1. Environment Setup

```bash
# Install uv if not present
pip install uv

# Sync dependencies
uv sync

# Install build dependencies
uv add --dev pyinstaller
```

### 2. Build Options

#### CPU-Only Build (Recommended for distribution)
```bash
.\build-windows.bat both
```

#### GPU-Enabled Build
```bash
.\build-windows.ps1 -GPU -BuildType both
```

### 3. Output Structure

```
dist/scribe-windows-package/
├── run-scribe-cli.bat          # Easy CLI launcher
├── run-scribe-gui.bat          # Easy GUI launcher  
├── README.txt                  # User instructions
├── scribe-cli/                 # CLI executable folder
│   ├── scribe-cli.exe         # Main CLI executable
│   └── [dependencies]         # Libraries and data
└── scribe-gui-windows/         # GUI executable folder
    ├── scribe-gui-windows.exe # Main GUI executable
    └── [dependencies]         # Libraries and data
```

## Architecture Changes for Windows

### 1. Audio Recording

**Before (Linux/macOS):**
- FFmpeg subprocess with platform-specific args
- External binary dependency (~50MB)

**After (Windows):**
- `sounddevice` library with native Windows audio APIs
- No external dependencies
- Better Windows integration

### 2. GUI Framework

**Before:**
- GTK3 via PyGObject
- Complex Windows setup required

**After:**
- tkinter (built into Python)
- Native Windows look and feel
- No additional runtime dependencies

### 3. Packaging Benefits

- **Smaller package size**: No FFmpeg binary
- **Simpler installation**: No GTK runtime required
- **Better compatibility**: Native Windows APIs
- **Single executable**: PyInstaller bundle

## Troubleshooting

### Common Issues

1. **"sounddevice not found"**
   ```bash
   uv add sounddevice
   ```

2. **"PyInstaller fails"**
   ```bash
   uv add --dev pyinstaller>=6.0.0
   ```

3. **"CUDA errors"**
   - Install NVIDIA drivers and CUDA runtime
   - Or build without GPU support

4. **"Missing Visual C++ libraries"**
   - Install Visual Studio C++ Redistributable
   - Or use conda environment

### Performance Optimization

1. **Model Selection**:
   - `tiny`: Fastest, least accurate (~39MB)
   - `base`: Good balance (~74MB) 
   - `large`: Best accuracy (~1550MB)

2. **GPU Acceleration**:
   - Requires NVIDIA GPU with CUDA
   - 3-5x faster transcription
   - Larger package size

## Distribution

### For End Users

1. **Simple Distribution**:
   - Zip the `scribe-windows-package` folder
   - Users run `.bat` files to start

2. **Installer** (future):
   - Use NSIS or Inno Setup
   - Create Start Menu shortcuts
   - Register file associations

### System Requirements

**Minimum:**
- Windows 10 (1903) or Windows 11
- 4GB RAM
- 2GB disk space
- Microphone

**Recommended:**
- Windows 11
- 8GB RAM  
- NVIDIA GPU with 4GB VRAM
- USB microphone

## Development Notes

### Code Changes Made

1. **Added `WindowsAudioRecorder` class**:
   - Uses `sounddevice` for real-time audio
   - Compatible with existing `StreamingRecorder` interface
   - Platform detection in main()

2. **Created `gui_windows.py`**:
   - tkinter-based GUI
   - Windows-native styling
   - Same functionality as GTK version

3. **Platform-specific imports**:
   - Graceful fallback if sounddevice unavailable
   - Optional PyGObject import

### Future Improvements

1. **Audio Quality**:
   - Add audio preprocessing options
   - Support for different sample rates
   - Noise reduction filters

2. **GUI Enhancements**:
   - Real-time waveform display
   - Audio device selection
   - Customizable hotkeys

3. **Packaging**:
   - Auto-updater integration
   - Code signing for security
   - MSI installer package

## Testing

### Manual Testing

1. **Audio Recording**:
   ```bash
   # Test CLI
   dist/scribe-windows-package/scribe-cli/scribe-cli.exe --debug

   # Test GUI  
   dist/scribe-windows-package/scribe-gui-windows/scribe-gui-windows.exe
   ```

2. **Model Loading**:
   ```bash
   # Test different models
   scribe-cli.exe --model tiny
   scribe-cli.exe --model base
   scribe-cli.exe --model large
   ```

3. **Platform Features**:
   - Microphone detection
   - Audio device switching
   - System audio integration

### Automated Testing

Create test scripts to verify:
- Audio recording functionality
- Model loading/unloading
- GUI responsiveness
- Memory usage
- Package integrity