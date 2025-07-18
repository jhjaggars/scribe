#!/usr/bin/env python3
"""Scribe daemon process - handles model loading and transcription."""

import os
import sys
import time
import signal
import threading
import tempfile
import subprocess
import platform
import queue
import wave
import numpy as np
from pathlib import Path
from typing import Dict, Any, Optional
import click

# Set up cuDNN library path for NVIDIA GPU support
def setup_cudnn_path():
    """Automatically detect and set cuDNN library path."""
    try:
        import nvidia.cudnn
        cudnn_lib_path = Path(nvidia.cudnn.__file__).parent / "lib"
        if cudnn_lib_path.exists():
            current_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
            if str(cudnn_lib_path) not in current_ld_path:
                new_ld_path = f"{cudnn_lib_path}:{current_ld_path}" if current_ld_path else str(cudnn_lib_path)
                # Re-exec with the new environment variable
                os.environ["LD_LIBRARY_PATH"] = new_ld_path
                os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)
    except ImportError:
        # nvidia.cudnn not available, skip
        pass

# Set up cuDNN path before importing faster_whisper
if "SCRIBE_CUDNN_SETUP" not in os.environ:
    os.environ["SCRIBE_CUDNN_SETUP"] = "1"
    setup_cudnn_path()

from faster_whisper import WhisperModel

# Handle both module and script execution
try:
    from .ipc import ScribeIPCServer
except ImportError:
    from scribe.ipc import ScribeIPCServer


class StreamingRecorder:
    """Handles continuous microphone recording with chunked processing."""
    
    def __init__(self, sample_rate=16000, channels=1, chunk_duration=5.0, 
                 overlap_duration=1.0, silence_threshold=0.01, debug=False,
                 vad_mode=False, vad_silence_duration=0.5, vad_max_duration=30.0):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration = chunk_duration
        self.overlap_duration = overlap_duration
        self.silence_threshold = silence_threshold
        self.platform = platform.system().lower()
        self.debug = debug
        
        # VAD mode settings
        self.vad_mode = vad_mode
        self.vad_silence_duration = vad_silence_duration
        self.vad_max_duration = vad_max_duration
        
        self.process = None
        self.audio_queue = queue.Queue()
        self.stop_event = threading.Event()
        self.recording_thread = None
        
        # Calculate samples for chunks and overlap
        self.chunk_samples = int(sample_rate * chunk_duration)
        self.overlap_samples = int(sample_rate * overlap_duration)
        self.buffer = np.array([], dtype=np.int16)
        
        # VAD state tracking
        self.vad_silence_samples = int(sample_rate * vad_silence_duration)
        self.vad_max_samples = int(sample_rate * vad_max_duration)
        self.vad_frame_size = int(sample_rate * 0.1)  # 100ms frames for VAD analysis
        self.vad_consecutive_silence_frames = 0
        self.vad_current_chunk_samples = 0
        self.vad_in_speech = False
        self.vad_speech_buffer = np.array([], dtype=np.int16)
        
        # Debug counters
        self.debug_stats = {
            'total_chunks_processed': 0,
            'chunks_with_audio': 0,
            'chunks_skipped_silence': 0,
            'bytes_read': 0,
            'ffmpeg_errors': 0,
            'processing_errors': 0,
            'vad_chunks_by_silence': 0,
            'vad_chunks_by_max_duration': 0
        }
        
    def _debug_log(self, message):
        """Log debug message."""
        if self.debug:
            print(f"[DEBUG] {message}", file=sys.stderr)
        
    def get_audio_input_args(self):
        """Get platform-specific FFmpeg audio input arguments for streaming."""
        if self.platform == "linux":
            try:
                subprocess.run(["arecord", "-l"], capture_output=True, check=True)
                return ["-f", "alsa", "-i", "default"]
            except:
                return ["-f", "pulse", "-i", "default"]
        elif self.platform == "darwin":  # macOS
            return ["-f", "avfoundation", "-i", ":0"]
        elif self.platform == "windows":
            return ["-f", "dshow", "-i", "audio="]
        else:
            return ["-f", "pulse", "-i", "default"]
    
    def _recording_worker(self):
        """Worker thread for continuous audio recording."""
        cmd = ["ffmpeg", "-y"]
        cmd.extend(self.get_audio_input_args())
        cmd.extend([
            "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate),
            "-ac", str(self.channels),
            "-f", "wav",
            "pipe:1"  # Output to stdout
        ])
        
        self._debug_log(f"Starting FFmpeg with command: {' '.join(cmd)}")
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                bufsize=0
            )
            
            self._debug_log(f"FFmpeg process started with PID: {self.process.pid}")
            
            # Skip WAV header (44 bytes)
            header = self.process.stdout.read(44)
            if len(header) < 44:
                self._debug_log(f"Failed to read WAV header, got {len(header)} bytes")
                return
            
            self._debug_log(f"WAV header read successfully ({len(header)} bytes)")
            
            # Read audio data in small chunks
            read_size = self.sample_rate * 2 // 10  # 0.1 second chunks
            self._debug_log(f"Reading audio in chunks of {read_size} bytes")
            
            while not self.stop_event.is_set() and self.process.poll() is None:
                try:
                    data = self.process.stdout.read(read_size)
                    if not data:
                        self._debug_log("No data received from FFmpeg, breaking")
                        break
                    
                    self.debug_stats['bytes_read'] += len(data)
                    
                    # Convert to numpy array
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    self.audio_queue.put(audio_data)
                    
                except Exception as e:
                    self._debug_log(f"Error reading audio data: {e}")
                    self.debug_stats['ffmpeg_errors'] += 1
                    if not self.stop_event.is_set():
                        self.audio_queue.put(None)  # Signal error
                    break
            
            # Check if FFmpeg process ended with error
            if self.process.poll() is not None:
                stderr_output = self.process.stderr.read().decode('utf-8', errors='ignore')
                if stderr_output:
                    self._debug_log(f"FFmpeg stderr: {stderr_output}")
                    
        except Exception as e:
            self._debug_log(f"Fatal error in recording worker: {e}")
            self.debug_stats['ffmpeg_errors'] += 1
            self.audio_queue.put(None)
    
    def start_streaming(self):
        """Start continuous audio streaming."""
        self.stop_event.clear()
        self.recording_thread = threading.Thread(target=self._recording_worker)
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
    def get_next_vad_chunk(self):
        """Get the next audio chunk using Voice Activity Detection."""
        while not self.stop_event.is_set():
            try:
                # Get audio data from queue
                try:
                    audio_data = self.audio_queue.get(timeout=0.1)
                    if audio_data is None:  # Error signal
                        self._debug_log("Received error signal from recording thread")
                        return None
                    
                    # Add to main buffer for frame-by-frame analysis
                    self.buffer = np.concatenate([self.buffer, audio_data])
                    
                except queue.Empty:
                    continue
                
                # Process audio in frames for VAD analysis
                while len(self.buffer) >= self.vad_frame_size:
                    # Extract frame
                    frame = self.buffer[:self.vad_frame_size]
                    self.buffer = self.buffer[self.vad_frame_size:]
                    
                    # Analyze frame for speech/silence
                    frame_has_speech = self._has_audio(frame)
                    
                    if frame_has_speech:
                        # Speech detected
                        if not self.vad_in_speech:
                            self._debug_log("VAD: Speech started")
                            self.vad_in_speech = True
                        
                        # Add frame to speech buffer
                        self.vad_speech_buffer = np.concatenate([self.vad_speech_buffer, frame])
                        self.vad_current_chunk_samples += len(frame)
                        self.vad_consecutive_silence_frames = 0
                        
                    else:
                        # Silence detected
                        if self.vad_in_speech:
                            # We were in speech, now silence
                            self.vad_consecutive_silence_frames += 1
                            silence_duration = self.vad_consecutive_silence_frames * self.vad_frame_size / self.sample_rate
                            
                            self._debug_log(f"VAD: Silence frame {self.vad_consecutive_silence_frames}, "
                                          f"duration: {silence_duration:.2f}s")
                            
                            # Add silence frame to buffer (we might still be in a pause)
                            self.vad_speech_buffer = np.concatenate([self.vad_speech_buffer, frame])
                            self.vad_current_chunk_samples += len(frame)
                            
                            # Check if silence duration exceeded threshold
                            if silence_duration >= self.vad_silence_duration:
                                self._debug_log("VAD: Silence threshold exceeded, ending chunk")
                                chunk = self._finalize_vad_chunk("silence")
                                if chunk:
                                    return chunk
                        else:
                            # We're in silence, continue
                            pass
                    
                    # Check maximum duration failsafe
                    if self.vad_current_chunk_samples >= self.vad_max_samples:
                        self._debug_log("VAD: Maximum duration reached, ending chunk")
                        chunk = self._finalize_vad_chunk("max_duration")
                        if chunk:
                            return chunk
                    
            except Exception as e:
                self._debug_log(f"Error in get_next_vad_chunk: {e}")
                self.debug_stats['processing_errors'] += 1
                continue
        
        # If we're exiting and have accumulated speech, return it
        if len(self.vad_speech_buffer) > 0:
            self._debug_log("VAD: Returning final chunk on exit")
            chunk = self._finalize_vad_chunk("exit")
            if chunk:
                return chunk
        
        self._debug_log("get_next_vad_chunk exiting due to stop event")
        return None
    
    def _finalize_vad_chunk(self, reason):
        """Finalize and return a VAD chunk."""
        if len(self.vad_speech_buffer) == 0:
            return None
        
        # Determine if chunk has enough audio content
        if self._has_audio(self.vad_speech_buffer):
            self.debug_stats['total_chunks_processed'] += 1
            self.debug_stats['chunks_with_audio'] += 1
            
            if reason == "silence":
                self.debug_stats['vad_chunks_by_silence'] += 1
            elif reason == "max_duration":
                self.debug_stats['vad_chunks_by_max_duration'] += 1
            
            # Save chunk to temporary file
            temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            self._save_chunk_to_file(self.vad_speech_buffer, temp_file.name)
            temp_file.close()
            
            chunk_duration = len(self.vad_speech_buffer) / self.sample_rate
            
            self._debug_log(f"VAD Chunk {self.debug_stats['total_chunks_processed']}: "
                          f"duration={chunk_duration:.2f}s, samples={len(self.vad_speech_buffer)}, "
                          f"reason={reason}, saved to {temp_file.name}")
            
            # Reset VAD state
            self.vad_speech_buffer = np.array([], dtype=np.int16)
            self.vad_current_chunk_samples = 0
            self.vad_consecutive_silence_frames = 0
            self.vad_in_speech = False
            
            return temp_file.name
        else:
            # Chunk doesn't have enough audio, skip it
            self.debug_stats['total_chunks_processed'] += 1
            self.debug_stats['chunks_skipped_silence'] += 1
            
            self._debug_log(f"VAD Chunk {self.debug_stats['total_chunks_processed']}: "
                          f"skipped (insufficient audio), reason={reason}")
            
            # Reset VAD state
            self.vad_speech_buffer = np.array([], dtype=np.int16)
            self.vad_current_chunk_samples = 0
            self.vad_consecutive_silence_frames = 0
            self.vad_in_speech = False
            
            return None
    
    def _has_audio(self, audio_data):
        """Check if audio chunk contains significant audio (not just silence)."""
        # Calculate RMS (root mean square) to detect audio
        rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
        normalized_rms = rms / 32768.0  # Normalize to 0-1 range
        
        return normalized_rms > self.silence_threshold
    
    def _save_chunk_to_file(self, audio_data, filename):
        """Save audio chunk to WAV file."""
        with wave.open(filename, 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(audio_data.tobytes())
    
    def stop_streaming(self):
        """Stop continuous audio streaming."""
        self.stop_event.set()
        
        if self.process:
            try:
                self.process.stdin.write(b'q\n')
                self.process.stdin.flush()
            except:
                pass
            
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait()
        
        if self.recording_thread:
            self.recording_thread.join(timeout=2)
    
    def cleanup(self):
        """Clean up resources."""
        self.stop_streaming()


class ScribeDaemon:
    """Main daemon class that handles model loading and transcription."""
    
    def __init__(self, socket_path: Optional[str] = None):
        self.ipc_server = ScribeIPCServer(socket_path)
        self.whisper_model = None
        self.recorder = None
        self.recording = False
        self.running = False
        self.config = {
            "model": "base",
            "language": None,
            "chunk_duration": 5.0,
            "overlap_duration": 1.0,
            "silence_threshold": 0.01,
            "vad_silence_duration": 0.5,
            "vad_max_duration": 30.0,
            "debug": False
        }
        
        # Register IPC handlers
        self.ipc_server.register_handler("configure", self._handle_configure)
        self.ipc_server.register_handler("start_recording", self._handle_start_recording)
        self.ipc_server.register_handler("stop_recording", self._handle_stop_recording)
        self.ipc_server.register_handler("get_status", self._handle_get_status)
        self.ipc_server.register_handler("shutdown", self._handle_shutdown)
        
        # Transcription processing thread
        self.transcription_thread = None
        self.transcription_stop_event = threading.Event()
        
    def start(self):
        """Start the daemon."""
        print("Starting Scribe daemon...", file=sys.stderr)
        
        # Start IPC server
        self.ipc_server.start()
        print(f"IPC server started on {self.ipc_server.protocol.socket_path}", file=sys.stderr)
        
        # Load default model
        self._load_model(self.config["model"])
        
        self.running = True
        print("Scribe daemon ready", file=sys.stderr)
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Main daemon loop
        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
            
    def stop(self):
        """Stop the daemon."""
        print("Stopping Scribe daemon...", file=sys.stderr)
        
        self.running = False
        
        # Stop recording if active
        if self.recording:
            self._stop_recording()
        
        # Stop IPC server
        self.ipc_server.stop()
        
        print("Scribe daemon stopped", file=sys.stderr)
        
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        print(f"Received signal {signum}, shutting down...", file=sys.stderr)
        self.running = False
        
    def _load_model(self, model_name: str):
        """Load Whisper model."""
        print(f"Loading Whisper model: {model_name}", file=sys.stderr)
        start_time = time.time()
        
        try:
            self.whisper_model = WhisperModel(model_name, device="auto")
            load_time = time.time() - start_time
            print(f"Model loaded in {load_time:.2f}s", file=sys.stderr)
        except Exception as e:
            print(f"Error loading model: {e}", file=sys.stderr)
            raise
            
    def _handle_configure(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle configuration command."""
        try:
            # Update configuration
            for key, value in message.items():
                if key != "command" and key in self.config:
                    self.config[key] = value
            
            # Reload model if changed
            if "model" in message and message["model"] != self.config.get("model"):
                self._load_model(message["model"])
                self.config["model"] = message["model"]
            
            return {"status": "success", "message": "Configuration updated"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    def _handle_start_recording(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle start recording command."""
        if self.recording:
            return {"status": "error", "message": "Already recording"}
            
        try:
            self._start_recording()
            return {"status": "success", "message": "Recording started"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    def _handle_stop_recording(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle stop recording command."""
        if not self.recording:
            return {"status": "error", "message": "Not recording"}
            
        try:
            self._stop_recording()
            return {"status": "success", "message": "Recording stopped"}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    def _handle_get_status(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle get status command."""
        return {
            "status": "success",
            "recording": self.recording,
            "model": self.config["model"],
            "config": self.config
        }
        
    def _handle_shutdown(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Handle shutdown command."""
        self.running = False
        return {"status": "success", "message": "Shutting down"}
        
    def _start_recording(self):
        """Start recording and transcription."""
        if self.recording:
            return
            
        print("Starting recording...", file=sys.stderr)
        
        # Create recorder
        self.recorder = StreamingRecorder(
            chunk_duration=self.config["chunk_duration"],
            overlap_duration=self.config["overlap_duration"],
            silence_threshold=self.config["silence_threshold"],
            debug=self.config["debug"],
            vad_mode=True,
            vad_silence_duration=self.config["vad_silence_duration"],
            vad_max_duration=self.config["vad_max_duration"]
        )
        
        # Start recording
        self.recorder.start_streaming()
        
        # Start transcription processing thread
        self.transcription_stop_event.clear()
        self.transcription_thread = threading.Thread(target=self._transcription_worker, daemon=True)
        self.transcription_thread.start()
        
        self.recording = True
        print("Recording started", file=sys.stderr)
        
    def _stop_recording(self):
        """Stop recording and transcription."""
        if not self.recording:
            return
            
        print("Stopping recording...", file=sys.stderr)
        
        self.recording = False
        
        # Stop transcription thread
        self.transcription_stop_event.set()
        if self.transcription_thread:
            self.transcription_thread.join(timeout=2)
        
        # Stop recorder
        if self.recorder:
            self.recorder.cleanup()
            self.recorder = None
        
        # Notify clients
        self.ipc_server.broadcast_message({
            "type": "recording_stopped",
            "message": "Recording stopped"
        })
        
        print("Recording stopped", file=sys.stderr)
        
    def _transcription_worker(self):
        """Process audio chunks and transcribe them."""
        print("Starting transcription worker...", file=sys.stderr)
        
        while not self.transcription_stop_event.is_set() and self.recording:
            try:
                # Get next audio chunk
                chunk_file = self.recorder.get_next_vad_chunk()
                if chunk_file is None:
                    continue
                
                # Transcribe chunk
                start_time = time.time()
                segments, info = self.whisper_model.transcribe(
                    chunk_file, 
                    language=self.config["language"]
                )
                
                transcription_time = time.time() - start_time
                
                # Send transcription to clients
                for segment in segments:
                    if segment.text.strip():
                        self.ipc_server.broadcast_message({
                            "type": "transcription",
                            "text": segment.text.strip(),
                            "transcription_time": transcription_time
                        })
                
                # Clean up chunk file
                try:
                    os.unlink(chunk_file)
                except:
                    pass
                    
            except Exception as e:
                print(f"Transcription error: {e}", file=sys.stderr)
                self.ipc_server.broadcast_message({
                    "type": "error",
                    "message": f"Transcription error: {e}"
                })
                continue
                
        print("Transcription worker stopped", file=sys.stderr)


@click.command()
@click.option('--socket-path', default=None, help='Path to IPC socket')
@click.option('--model', default='base', 
              type=click.Choice(['tiny', 'base', 'small', 'medium', 'large', 'turbo']),
              help='Default Whisper model to load')
@click.option('--debug', is_flag=True, help='Enable debug output')
def main(socket_path, model, debug):
    """Start the Scribe daemon."""
    daemon = ScribeDaemon(socket_path)
    daemon.config["model"] = model
    daemon.config["debug"] = debug
    
    try:
        daemon.start()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Daemon error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()