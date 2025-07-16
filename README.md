# Scribe

A speech-to-text transcription tool with both CLI and GUI interfaces, using OpenAI Whisper and FFmpeg for real-time transcription.

## Features

- **Real-time streaming transcription** with Voice Activity Detection (VAD)
- **GTK GUI interface** for easy management and configuration
- Speech-to-text transcription using faster-whisper
- Multiple Whisper model sizes (tiny, base, small, medium, large, turbo)
- Cross-platform support (Linux, macOS, Windows)
- Space-separated output by default (optimal for piping to other tools)
- Language detection or manual language specification
- Batch recording mode for traditional record-then-transcribe workflow
- **Configurable silence threshold** for fine-tuned voice detection
- **Output piping** to external commands (e.g., xvkbd for virtual keyboard input)

## Requirements

- Python 3.8 or higher (but less than 3.10)
- FFmpeg installed on your system
- A working microphone
- **For GUI**: GTK 3.0 development libraries (see installation notes below)

## Installation

1. Clone or download this project
2. **For GUI users**: Install GTK development libraries:

```bash
# Ubuntu/Debian
sudo apt install libgtk-3-dev libcairo2-dev libgirepository1.0-dev

# Fedora/RHEL
sudo dnf install gtk3-devel cairo-devel gobject-introspection-devel

# macOS
brew install gtk+3 pygobject3
```

3. Install using uv:

```bash
uv sync
```

### Desktop Integration (Optional)

For easy GUI access, you can install the desktop file to your system:

```bash
# Install for current user only (recommended)
cp scribe.desktop ~/.local/share/applications/
chmod +x ~/.local/share/applications/scribe.desktop

# Update desktop database to make it appear in application menus
update-desktop-database ~/.local/share/applications/

# Alternative: Install system-wide (requires sudo)
sudo cp scribe.desktop /usr/share/applications/
sudo chmod +x /usr/share/applications/scribe.desktop
sudo update-desktop-database /usr/share/applications/
```

**Note**: Before installing the desktop file, you may need to edit the `Path=` line in `scribe.desktop` to match your installation directory if it's not in `/home/jhjaggars/code/scribe`.

After installation, you can launch the GUI from your application menu by searching for "Scribe" or find it in the Audio/Office category.

## Usage

### GUI Application

For users who prefer a graphical interface:

```bash
# Launch the GUI
uv run scribe-gui
```

**GUI Features:**
- **Model Selection**: Choose from tiny, base, small, medium, large, or turbo models
- **Language Configuration**: Optional language specification (e.g., "en", "es", "fr")
- **Output Command**: Configure where transcribed text gets sent (default: `xvkbd -file -`)
- **Silence Threshold**: Adjust voice detection sensitivity (default: 0.002, lower = more sensitive)
- **Mode Selection**: Choose between Streaming (VAD) or Batch mode
- **Real-time Log**: Monitor Scribe output and process status
- **Start/Stop Controls**: Easy process management with visual feedback

**Common Output Commands:**
- `xvkbd -file -` - Send text to virtual keyboard (types transcribed text)
- `cat > output.txt` - Save transcription to a file
- `espeak` - Text-to-speech playback
- Leave empty to display output in the log only

### Command Line Interface

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

# Adjust silence threshold for voice detection
uv run scribe --silence-threshold 0.002   # More sensitive (lower values detect quieter sounds)
uv run scribe --silence-threshold 0.01    # Less sensitive (default)

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

### GUI not starting
- Ensure GTK development libraries are installed (see Installation section)
- Check that PyGObject is properly installed: `python -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk"`
- On some systems, you may need to install additional packages:
  ```bash
  # Ubuntu/Debian
  sudo apt install python3-gi-cairo
  
  # Fedora/RHEL
  sudo dnf install python3-cairo
  ```

### Output command not working
- Ensure the output command is installed and available in PATH
- For `xvkbd`: Install with `sudo apt install xvkbd` (Ubuntu/Debian)
- Test output commands manually before using in the GUI
- Check the log output for specific error messages

## Examples

### GUI Example
```bash
$ uv run scribe-gui
# Opens GTK window with:
# - Model: base (selected)
# - Language: (empty, auto-detect)
# - Output Command: xvkbd -file -
# - Silence Threshold: 0.002
# - Mode: Streaming (VAD) selected
# Click "Start" to begin transcription, "Stop" to end
```

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