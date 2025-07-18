# Scribe Daemon Architecture

## Overview

The Scribe daemon architecture separates the heavy initialization costs (model loading, CUDA setup, module imports) from the actual recording and transcription operations. This provides near-instantaneous start/stop operations while maintaining full compatibility with existing workflows.

## Architecture Components

### 1. Core Components

#### Scribe Daemon (`scribe.daemon`)
- **Purpose**: Long-running background process that manages models and transcription
- **Key Features**:
  - Loads Whisper models once at startup
  - Handles CUDA/GPU initialization
  - Manages audio recording and transcription
  - Exposes IPC interface for client commands
  - Supports hot-swapping models via configuration

#### Scribe Client (`scribe.client`)
- **Purpose**: Lightweight CLI interface for user interactions
- **Key Features**:
  - Compatible with existing CLI arguments
  - Automatic daemon lifecycle management
  - Real-time transcription streaming
  - Backward compatibility with legacy mode

#### IPC Protocol (`scribe.ipc`)
- **Purpose**: Inter-process communication between daemon and clients
- **Key Features**:
  - Unix domain socket communication
  - JSON message protocol
  - Streaming transcription support
  - Robust error handling

#### Daemon Manager (`scribe.daemon_manager`)
- **Purpose**: Daemon process lifecycle management
- **Key Features**:
  - Start/stop/restart daemon processes
  - Status monitoring
  - Configuration management
  - PID file management

#### GUI with Daemon Support (`scribe.gui_daemon`)
- **Purpose**: Enhanced GUI that communicates with daemon
- **Key Features**:
  - Real-time daemon status monitoring
  - Live transcription display
  - Daemon configuration interface
  - Automatic daemon startup

### 2. Communication Flow

```
┌─────────────┐    IPC     ┌──────────────┐    Audio    ┌─────────────┐
│   Client/   │◄──────────►│    Daemon    │◄───────────►│  Microphone │
│    GUI      │   Socket   │   Process    │   FFmpeg    │             │
└─────────────┘            └──────────────┘             └─────────────┘
                                  │
                                  ▼
                           ┌──────────────┐
                           │    Whisper   │
                           │    Model     │
                           └──────────────┘
```

## Performance Benefits

### Startup Time Comparison

| Component | Legacy Mode | Daemon Mode | Improvement |
|-----------|-------------|-------------|-------------|
| Module imports | ~0.87s | One-time | 100% |
| Model loading | ~0.28s (tiny) | One-time | 100% |
| CUDA setup | ~0.001s | One-time | 100% |
| Audio setup | ~0.002s | ~0.002s | 0% |
| **Total** | **~1.14s** | **~0.05s** | **95%** |

### Resource Efficiency
- **Memory**: Model stays loaded between sessions
- **GPU**: Shared CUDA context across recordings
- **CPU**: No repeated process creation/destruction
- **I/O**: Reduced file system operations

## Usage Examples

### Basic Usage

```bash
# Start daemon and begin recording (traditional interface)
scribe-client --model base

# Start daemon only (for GUI use)
scribe-client --model base --daemon-only

# Check daemon status
scribe-client --status

# Shutdown daemon
scribe-client --shutdown-daemon
```

### Daemon Management

```bash
# Start daemon in background
scribe-daemon --model base

# Start daemon with debug output
scribe-daemon --model base --debug

# Use daemon manager for lifecycle operations
python -m scribe.daemon_manager start --model base
python -m scribe.daemon_manager status
python -m scribe.daemon_manager stop
```

### GUI Usage

```bash
# Start daemon-enabled GUI
scribe-gui-daemon
```

## IPC Protocol

### Message Format

All messages are JSON objects sent over Unix domain sockets.

#### Commands

```json
{
  "command": "configure",
  "model": "base",
  "language": "en",
  "silence_threshold": 0.01
}
```

#### Responses

```json
{
  "status": "success",
  "message": "Configuration updated"
}
```

#### Streaming Messages

```json
{
  "type": "transcription",
  "text": "Hello world",
  "transcription_time": 0.234
}
```

### Available Commands

| Command | Purpose | Parameters |
|---------|---------|------------|
| `configure` | Update daemon configuration | `model`, `language`, `silence_threshold`, etc. |
| `start_recording` | Begin audio recording | None |
| `stop_recording` | End audio recording | None |
| `get_status` | Query daemon status | None |
| `shutdown` | Graceful daemon shutdown | None |

## Configuration

### Daemon Configuration

The daemon accepts the following configuration parameters:

```json
{
  "model": "base",
  "language": "en",
  "chunk_duration": 5.0,
  "overlap_duration": 1.0,
  "silence_threshold": 0.01,
  "vad_silence_duration": 0.5,
  "vad_max_duration": 30.0,
  "debug": false
}
```

### Socket Location

- **Default**: `/tmp/scribe_daemon.sock`
- **Custom**: Use `--socket-path` parameter

## Error Handling

### Connection Errors
- Automatic daemon startup if not running
- Graceful fallback to legacy mode
- Connection retry with exponential backoff

### Process Management
- Graceful shutdown with SIGTERM
- Force kill with SIGKILL if unresponsive
- Automatic cleanup of socket files and PID files

### Audio Errors
- Platform-specific audio input detection
- FFmpeg error handling and recovery
- Microphone permission error reporting

## Performance Monitoring

### Built-in Metrics
- Model loading time
- Transcription processing time
- Audio chunk processing statistics
- IPC communication latency

### Debug Output
Enable debug mode for detailed performance information:

```bash
scribe-daemon --debug
scribe-client --debug
```

## Backward Compatibility

### Legacy Mode Support
The original `scribe` command continues to work unchanged:

```bash
# These commands work exactly as before
scribe --model base
scribe --model tiny --language en
scribe --batch
```

### Migration Path
- No breaking changes to existing workflows
- Gradual adoption of daemon mode
- Fallback to legacy mode if daemon unavailable

## Security Considerations

### Socket Security
- Unix domain sockets provide local-only access
- No network exposure
- File system permissions control access

### Process Isolation
- Daemon runs in separate process group
- No shared memory between client and daemon
- Clean process termination

## Troubleshooting

### Common Issues

1. **Daemon won't start**
   - Check audio permissions
   - Verify FFmpeg installation
   - Review error logs with `--debug`

2. **Connection refused**
   - Ensure daemon is running
   - Check socket file permissions
   - Verify socket path configuration

3. **Audio not working**
   - Test microphone with other applications
   - Check audio system (ALSA/PulseAudio)
   - Verify FFmpeg audio input detection

### Debug Commands

```bash
# Check daemon status
scribe-client --status

# Test audio input
ffmpeg -f alsa -i default -t 1 test.wav

# Monitor daemon logs
scribe-daemon --debug

# Test IPC communication
python -c "
from scribe.ipc import ScribeIPCClient
client = ScribeIPCClient()
print(client.connect())
print(client.send_command('get_status'))
"
```

## Future Enhancements

### Planned Features
- Multiple model support (load multiple models simultaneously)
- Distributed daemon support (remote daemon connections)
- Configuration persistence (save/load daemon configurations)
- Systemd service integration
- Docker container support
- API server mode (HTTP/WebSocket interface)

### Performance Optimizations
- Model caching and preloading
- GPU memory optimization
- Streaming audio compression
- Batch transcription mode

## Development

### Running Tests

```bash
# Test daemon architecture
python test_daemon.py

# Performance comparison
python performance_comparison.py

# Manual testing
python -m scribe.daemon --model tiny --debug
python -m scribe.client --model tiny --debug
```

### Code Organization

```
src/scribe/
├── daemon.py           # Main daemon process
├── client.py           # CLI client interface
├── ipc.py              # IPC protocol implementation
├── daemon_manager.py   # Process lifecycle management
├── gui_daemon.py       # Daemon-enabled GUI
├── main.py             # Legacy CLI (preserved)
└── gui.py              # Legacy GUI (preserved)
```

This architecture provides a solid foundation for high-performance, scalable speech-to-text transcription while maintaining full backward compatibility with existing workflows.