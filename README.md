# Scribe

A simple CLI tool for real-time speech-to-text transcription using OpenAI Whisper and FFmpeg.

## Features

- **Real-time streaming transcription** with Voice Activity Detection (VAD)
- Speech-to-text transcription using faster-whisper
- Multiple Whisper model sizes (tiny, base, small, medium, large, turbo)
- Cross-platform support (Linux, macOS, Windows)
- Space-separated output by default (optimal for piping to other tools)
- Language detection or manual language specification
- Batch recording mode for traditional record-then-transcribe workflow

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

### Basic usage (streaming mode with VAD)
```bash
# Default: real-time streaming with Voice Activity Detection
uv run scribe
```

### Batch recording mode
```bash
# Record once, then transcribe (like the old behavior)
uv run scribe --batch
```

### Output formatting
```bash
# Default: space-separated output (good for piping)
uv run scribe

# Output with newlines (each segment on separate line)
uv run scribe --newlines
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

### Advanced streaming options
```bash
# Adjust VAD sensitivity
uv run scribe --vad-silence-duration 1.0  # Require 1s of silence to end chunk
uv run scribe --vad-max-duration 60.0     # Force chunk end after 60s

# Debug mode to see what's happening
uv run scribe --debug
```

## How it works

### Streaming Mode (Default)
1. **Continuous Recording**: Uses FFmpeg to capture audio from your microphone in real-time
2. **Voice Activity Detection**: Automatically detects speech and silence to create natural chunks
3. **Real-time Transcription**: Processes audio chunks as they're spoken using faster-whisper
4. **Immediate Output**: Prints transcribed text to stdout as it's processed

### Batch Mode
1. **Single Recording**: Records audio until you press Ctrl+C
2. **Format**: Records in 16kHz mono WAV format (optimal for Whisper)
3. **Transcription**: Processes the entire recording with faster-whisper
4. **Output**: Prints the complete transcribed text to stdout

## Platform-specific notes

- **Linux**: Uses PulseAudio (`pulse`) for audio input
- **macOS**: Uses AVFoundation (`avfoundation`) for audio input  
- **Windows**: Uses DirectShow (`dshow`) for audio input

## Controls

### Streaming Mode (Default)
- Start the tool with `uv run scribe`
- Speak into your microphone
- Transcribed text appears in real-time as you speak
- Press **Ctrl+C** to stop streaming

### Batch Mode
- Start the tool with `uv run scribe --batch`
- Speak into your microphone
- Press **Ctrl+C** to stop recording and get the transcription
- The complete transcribed text will be printed to stdout

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

## Examples

### Streaming Mode Example
```bash
$ uv run scribe --model base --verbose
Loading Whisper model: base
Starting VAD streaming mode (silence: 0.5s, max: 30.0s)
Press Ctrl+C to stop streaming...
Hello, this is a test of the real-time speech to text functionality. It processes audio as you speak and outputs text immediately.
```

### Batch Mode Example
```bash
$ uv run scribe --batch --model base --verbose
Loading Whisper model: base
Press Ctrl+C to stop recording and transcribe...
Processing audio with Whisper...
This is a complete sentence recorded in batch mode.
```

### Piping Output Example
```bash
# Space-separated output is great for piping to other tools
$ uv run scribe | grep -i "important"
$ uv run scribe > transcript.txt
```