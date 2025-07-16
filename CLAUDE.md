# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Running the Application
```bash
# Run with default settings (base model)
uv run scribe

# Run with different model sizes
uv run scribe --model tiny    # Fastest, least accurate
uv run scribe --model base    # Default
uv run scribe --model large   # Slowest, most accurate

# Run with language specification
uv run scribe --language en   # English
uv run scribe --language es   # Spanish

# Run with verbose output
uv run scribe --verbose
```

### Development Setup
```bash
# Install dependencies
uv sync

# The project uses uv for dependency management
# No separate build step required - Python package with direct execution
```

## Architecture Overview

This is a CLI tool for real-time speech-to-text transcription using OpenAI Whisper and FFmpeg.

### Core Components

1. **FFmpegRecorder class** (`src/scribe/main.py:39-134`):
   - Handles microphone recording using FFmpeg subprocess
   - Platform-specific audio input detection (Linux/ALSA/PulseAudio, macOS/AVFoundation, Windows/DirectShow)
   - Temporary WAV file management for recording
   - Graceful process termination and cleanup

2. **Main CLI interface** (`src/scribe/main.py:136-199`):
   - Click-based command line interface
   - Whisper model loading and configuration
   - Audio recording orchestration
   - Transcription processing and output

3. **CUDA/cuDNN setup** (`src/scribe/main.py:15-35`):
   - Automatic cuDNN library path detection for NVIDIA GPU support
   - Environment variable management for CUDA acceleration
   - Process re-execution with updated library paths

### Key Technical Details

- **Audio Format**: 16kHz mono WAV (optimal for Whisper)
- **Dependencies**: faster-whisper, click, torch, torchaudio
- **Platform Support**: Cross-platform with platform-specific audio input handling
- **Model Support**: All Whisper model sizes (tiny, base, small, medium, large, turbo)
- **GPU Support**: Automatic CUDA/cuDNN setup for faster processing

### Project Structure
```
src/scribe/
├── __init__.py     # Package initialization with version
└── main.py         # Core CLI implementation with FFmpegRecorder class
```

### Error Handling
- FFmpeg availability checking
- Audio input device validation
- Model loading error handling
- Graceful keyboard interrupt handling (Ctrl+C)
- Temporary file cleanup on exit