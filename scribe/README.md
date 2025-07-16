# Scribe

A simple CLI tool for real-time speech-to-text transcription using OpenAI Whisper and FFmpeg.

## Features

- Real-time microphone recording using FFmpeg
- Speech-to-text transcription using faster-whisper
- Multiple Whisper model sizes (tiny, base, small, medium, large, turbo)
- Cross-platform support (Linux, macOS, Windows)
- Output transcription to stdout
- Language detection or manual language specification

## Requirements

- Python 3.8 or higher (but less than 3.10)
- FFmpeg installed on your system
- A working microphone

## Installation

1. Clone or download this project
2. Install using uv:

```bash
uv sync
```

## Usage

### Basic usage
```bash
uv run scribe
```

### With different model sizes
```bash
# Faster, less accurate
uv run scribe --model tiny

# Slower, more accurate
uv run scribe --model large
```

### With language specification
```bash
uv run scribe --language en  # English
uv run scribe --language es  # Spanish
uv run scribe --language fr  # French
```

### With verbose output
```bash
uv run scribe --verbose
```

## How it works

1. **Recording**: Uses FFmpeg to capture audio from your system's default microphone
2. **Format**: Records in 16kHz mono WAV format (optimal for Whisper)
3. **Transcription**: Uses faster-whisper for efficient speech-to-text conversion
4. **Output**: Prints the transcribed text to stdout

## Platform-specific notes

- **Linux**: Uses PulseAudio (`pulse`) for audio input
- **macOS**: Uses AVFoundation (`avfoundation`) for audio input  
- **Windows**: Uses DirectShow (`dshow`) for audio input

## Controls

- Start the tool with `uv run scribe`
- Speak into your microphone
- Press **Ctrl+C** to stop recording and get the transcription
- The transcribed text will be printed to stdout

## Model sizes

| Model  | Speed | Accuracy | Memory |
|--------|-------|----------|--------|
| tiny   | Fast  | Low      | ~1GB   |
| base   |      |         | ~1GB   |
| small  | -     | Good     | ~2GB   |
| medium | -     | Better   | ~5GB   |
| large  | Slow  | Best     | ~10GB  |
| turbo  | Fast  | Good     | ~6GB   |

## Troubleshooting

### FFmpeg not found
Make sure FFmpeg is installed and available in your PATH:
```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

### No audio input detected
- Check that your microphone is working
- Ensure microphone permissions are granted
- Try running with `--verbose` to see detailed error messages

### Model loading errors
- Make sure you have an internet connection for initial model download
- Models are cached locally after first download
- Try starting with the `tiny` model first to test functionality

## Example

```bash
$ uv run scribe --model base --verbose
Loading Whisper model: base
Press Ctrl+C to stop recording and transcribe...
Processing audio with Whisper...
Hello, this is a test of the speech to text functionality.
```