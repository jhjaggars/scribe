#!/usr/bin/env python3
"""Main CLI script for scribe - real-time speech-to-text transcription."""

import os
import tempfile
import subprocess
import sys
import platform
import time
import threading
import queue
import wave
import numpy as np
from pathlib import Path

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

# Import Windows-specific audio support
try:
    import sounddevice as sd
    SOUNDDEVICE_AVAILABLE = True
except (ImportError, OSError):
    # OSError occurs when PortAudio is not available
    SOUNDDEVICE_AVAILABLE = False
    sd = None


class FFmpegRecorder:
    """Handles microphone recording using FFmpeg subprocess."""
    
    def __init__(self, sample_rate=16000, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.process = None
        self.temp_file = None
        self.platform = platform.system().lower()
        
    def get_audio_input_args(self):
        """Get platform-specific FFmpeg audio input arguments."""
        if self.platform == "linux":
            # Try ALSA first, then PulseAudio
            try:
                # Test if ALSA is available
                subprocess.run(["arecord", "-l"], capture_output=True, check=True)
                return ["-f", "alsa", "-i", "default"]
            except:
                # Fallback to PulseAudio
                return ["-f", "pulse", "-i", "default"]
        elif self.platform == "darwin":  # macOS
            return ["-f", "avfoundation", "-i", ":0"]
        elif self.platform == "windows":
            return ["-f", "dshow", "-i", "audio="]
        else:
            # Fallback - might work on some systems
            return ["-f", "pulse", "-i", "default"]
    
    def start_recording(self):
        """Start recording audio from microphone using FFmpeg."""
        # Create temporary file for recording
        self.temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_filename = self.temp_file.name
        self.temp_file.close()
        
        # Build FFmpeg command
        cmd = ["ffmpeg", "-y"]  # -y to overwrite output files
        cmd.extend(self.get_audio_input_args())
        cmd.extend([
            "-acodec", "pcm_s16le",  # 16-bit PCM
            "-ar", str(self.sample_rate),  # Sample rate
            "-ac", str(self.channels),  # Channels (mono)
            temp_filename
        ])
        
        try:
            # Start FFmpeg process
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE
            )
            return temp_filename
        except FileNotFoundError:
            raise RuntimeError("FFmpeg not found. Please install FFmpeg to use this tool.")
        except Exception as e:
            raise RuntimeError(f"Error starting audio recording: {e}")
    
    def stop_recording(self):
        """Stop recording and return the temporary file path."""
        if self.process:
            # Send 'q' to FFmpeg to gracefully stop
            try:
                self.process.stdin.write(b'q\n')
                self.process.stdin.flush()
            except:
                pass
            
            # Wait for process to finish
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait()
            
            self.process = None
        
        return self.temp_file.name if self.temp_file else None
    
    def cleanup(self):
        """Clean up resources and temporary files."""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait()
            except:
                pass
        
        if self.temp_file and os.path.exists(self.temp_file.name):
            try:
                os.unlink(self.temp_file.name)
            except:
                pass


class WindowsAudioRecorder:
    """Handles continuous microphone recording using sounddevice for Windows."""
    
    def __init__(self, sample_rate=16000, channels=1, chunk_duration=5.0, 
                 overlap_duration=1.0, silence_threshold=0.01, debug=False,
                 vad_mode=False, vad_silence_duration=0.5, vad_max_duration=30.0):
        if not SOUNDDEVICE_AVAILABLE:
            raise RuntimeError("sounddevice library not available. Install with: pip install sounddevice")
        
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration = chunk_duration
        self.overlap_duration = overlap_duration
        self.silence_threshold = silence_threshold
        self.debug = debug
        
        # VAD mode settings
        self.vad_mode = vad_mode
        self.vad_silence_duration = vad_silence_duration
        self.vad_max_duration = vad_max_duration
        
        self.audio_queue = queue.Queue()  # For raw audio data
        self.chunk_queue = queue.Queue()  # For ready chunk filenames
        self.stop_event = threading.Event()
        self.recording_thread = None
        self.stream = None
        
        # Calculate samples for chunks and overlap
        self.chunk_samples = int(sample_rate * chunk_duration)
        self.overlap_samples = int(sample_rate * overlap_duration)
        self.buffer = np.array([], dtype=np.float32)
        
        # VAD state tracking
        self.vad_silence_samples = int(sample_rate * vad_silence_duration)
        self.vad_max_samples = int(sample_rate * vad_max_duration)
        self.vad_frame_size = int(sample_rate * 0.1)  # 100ms frames for VAD analysis
        self.vad_consecutive_silence_frames = 0
        self.vad_current_chunk_samples = 0
        self.vad_in_speech = False
        self.vad_speech_buffer = np.array([], dtype=np.float32)
        
        # Debug counters
        self.debug_stats = {
            'total_chunks_processed': 0,
            'chunks_with_audio': 0,
            'chunks_skipped_silence': 0,
            'processing_errors': 0,
            'vad_chunks_by_silence': 0,
            'vad_chunks_by_max_duration': 0
        }
        
        if self.debug:
            self._debug_log(f"WindowsAudioRecorder initialized:")
            self._debug_log(f"  Sample rate: {sample_rate}Hz")
            self._debug_log(f"  Channels: {channels}")
            if self.vad_mode:
                self._debug_log(f"  VAD mode: ENABLED")
                self._debug_log(f"  VAD silence duration: {vad_silence_duration}s")
                self._debug_log(f"  VAD max duration: {vad_max_duration}s")
            else:
                self._debug_log(f"  VAD mode: DISABLED")
                self._debug_log(f"  Chunk duration: {chunk_duration}s")
    
    def _debug_log(self, message):
        """Log debug message to stderr."""
        if self.debug:
            click.echo(f"[DEBUG] {message}", err=True)
    
    def _audio_callback(self, indata, frames, time, status):
        """Callback function for sounddevice stream."""
        if status:
            self._debug_log(f"Audio callback status: {status}")
        
        # Convert to mono if needed and flatten
        if self.channels == 1 and indata.shape[1] > 1:
            audio_data = np.mean(indata, axis=1)
        else:
            audio_data = indata[:, 0]
        
        # Put audio data in queue
        self.audio_queue.put(audio_data.copy())
    
    def start_streaming(self):
        """Start continuous audio streaming using sounddevice."""
        if self.stream is not None:
            return
        
        try:
            # Start audio stream
            self.stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype=np.float32,
                callback=self._audio_callback,
                blocksize=int(self.sample_rate * 0.1)  # 100ms blocks
            )
            self.stream.start()
            
            # Start processing thread
            self.stop_event.clear()
            self.recording_thread = threading.Thread(target=self._process_audio_stream)
            self.recording_thread.start()
            
            self._debug_log("Started Windows audio streaming")
            
        except Exception as e:
            raise RuntimeError(f"Error starting Windows audio recording: {e}")
    
    def stop_streaming(self):
        """Stop continuous audio streaming."""
        self.stop_event.set()
        
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        
        if self.recording_thread and self.recording_thread.is_alive():
            self.recording_thread.join(timeout=2)
        
        self._debug_log("Stopped Windows audio streaming")
    
    def _process_audio_stream(self):
        """Process incoming audio data in streaming mode."""
        while not self.stop_event.is_set():
            try:
                # Get audio data with timeout
                try:
                    audio_chunk = self.audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                # Add to buffer
                self.buffer = np.append(self.buffer, audio_chunk)
                
                # Process based on mode
                if self.vad_mode:
                    self._process_vad_mode()
                else:
                    self._process_fixed_chunks()
                    
            except Exception as e:
                self._debug_log(f"Error in audio processing: {e}")
                self.debug_stats['processing_errors'] += 1
    
    def _process_fixed_chunks(self):
        """Process audio in fixed-duration chunks."""
        if len(self.buffer) >= self.chunk_samples:
            # Extract chunk
            chunk = self.buffer[:self.chunk_samples]
            
            # Keep overlap for next chunk
            if self.overlap_samples > 0:
                self.buffer = self.buffer[self.chunk_samples - self.overlap_samples:]
            else:
                self.buffer = self.buffer[self.chunk_samples:]
            
            # Check if chunk has sufficient audio
            if self._has_audio(chunk):
                # Convert to int16 for Whisper (scale from [-1, 1] to [-32768, 32767])
                chunk_int16 = (chunk * 32767).astype(np.int16)
                self._write_chunk_to_temp_file(chunk_int16)
                self.debug_stats['chunks_with_audio'] += 1
            else:
                self.debug_stats['chunks_skipped_silence'] += 1
            
            self.debug_stats['total_chunks_processed'] += 1
    
    def _process_vad_mode(self):
        """Process audio using Voice Activity Detection."""
        while len(self.buffer) >= self.vad_frame_size:
            frame = self.buffer[:self.vad_frame_size]
            self.buffer = self.buffer[self.vad_frame_size:]
            
            has_speech = self._has_audio(frame)
            
            if has_speech:
                if not self.vad_in_speech:
                    self.vad_in_speech = True
                    self._debug_log("Speech detected - starting recording")
                
                self.vad_speech_buffer = np.append(self.vad_speech_buffer, frame)
                self.vad_current_chunk_samples += len(frame)
                self.vad_consecutive_silence_frames = 0
                
                # Check max duration
                if self.vad_current_chunk_samples >= self.vad_max_samples:
                    self._flush_vad_buffer("max duration reached")
                    self.debug_stats['vad_chunks_by_max_duration'] += 1
            else:
                if self.vad_in_speech:
                    self.vad_speech_buffer = np.append(self.vad_speech_buffer, frame)
                    self.vad_current_chunk_samples += len(frame)
                    self.vad_consecutive_silence_frames += 1
                    
                    # Check if enough silence to end speech
                    silence_samples = self.vad_consecutive_silence_frames * self.vad_frame_size
                    if silence_samples >= self.vad_silence_samples:
                        self._flush_vad_buffer("silence detected")
                        self.debug_stats['vad_chunks_by_silence'] += 1
    
    def _flush_vad_buffer(self, reason):
        """Flush the VAD speech buffer."""
        if len(self.vad_speech_buffer) > 0:
            self._debug_log(f"Flushing VAD buffer: {reason} ({len(self.vad_speech_buffer)} samples)")
            
            # Convert to int16 for Whisper
            chunk_int16 = (self.vad_speech_buffer * 32767).astype(np.int16)
            self._write_chunk_to_temp_file(chunk_int16)
            
            self.debug_stats['chunks_with_audio'] += 1
            self.debug_stats['total_chunks_processed'] += 1
        
        # Reset VAD state
        self.vad_speech_buffer = np.array([], dtype=np.float32)
        self.vad_current_chunk_samples = 0
        self.vad_consecutive_silence_frames = 0
        self.vad_in_speech = False
    
    def _has_audio(self, chunk):
        """Check if audio chunk contains significant audio."""
        rms = np.sqrt(np.mean(chunk ** 2))
        return rms > self.silence_threshold
    
    def _write_chunk_to_temp_file(self, chunk):
        """Write audio chunk to temporary WAV file."""
        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        temp_filename = temp_file.name
        temp_file.close()
        
        # Write WAV file
        with wave.open(temp_filename, 'wb') as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(chunk.tobytes())
        
        # Add to chunk queue for processing
        self.chunk_queue.put(temp_filename)
    
    def get_next_chunk(self):
        """Get the next audio chunk for transcription."""
        try:
            return self.chunk_queue.get(timeout=0.1)
        except queue.Empty:
            return None
    
    def get_next_vad_chunk(self):
        """Get the next VAD chunk for transcription. Compatible with StreamingRecorder interface."""
        return self.get_next_chunk()
    
    def cleanup(self):
        """Clean up resources."""
        self.stop_streaming()


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
        
        if self.debug:
            self._debug_log(f"StreamingRecorder initialized:")
            self._debug_log(f"  Sample rate: {sample_rate}Hz")
            if self.vad_mode:
                self._debug_log(f"  VAD mode: ENABLED")
                self._debug_log(f"  VAD silence duration: {vad_silence_duration}s ({self.vad_silence_samples} samples)")
                self._debug_log(f"  VAD max duration: {vad_max_duration}s ({self.vad_max_samples} samples)")
                self._debug_log(f"  VAD frame size: {self.vad_frame_size} samples")
            else:
                self._debug_log(f"  VAD mode: DISABLED")
                self._debug_log(f"  Chunk duration: {chunk_duration}s ({self.chunk_samples} samples)")
                self._debug_log(f"  Overlap duration: {overlap_duration}s ({self.overlap_samples} samples)")
            self._debug_log(f"  Silence threshold: {silence_threshold}")
            self._debug_log(f"  Platform: {self.platform}")
    
    def _debug_log(self, message):
        """Log debug message to stderr."""
        if self.debug:
            click.echo(f"[DEBUG] {message}", err=True)
        
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
            
            bytes_read_total = 0
            read_count = 0
            
            while not self.stop_event.is_set() and self.process.poll() is None:
                try:
                    data = self.process.stdout.read(read_size)
                    if not data:
                        self._debug_log("No data received from FFmpeg, breaking")
                        break
                    
                    bytes_read_total += len(data)
                    read_count += 1
                    self.debug_stats['bytes_read'] += len(data)
                    
                    # Convert to numpy array
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    self.audio_queue.put(audio_data)
                    
                    if read_count % 50 == 0:  # Log every 5 seconds
                        self._debug_log(f"Read {read_count} chunks, {bytes_read_total} bytes total")
                    
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
        
    def get_next_chunk(self):
        """Get the next audio chunk for processing."""
        start_time = time.time()
        
        while not self.stop_event.is_set():
            try:
                # Collect audio data until we have enough for a chunk
                queue_gets = 0
                while len(self.buffer) < self.chunk_samples and not self.stop_event.is_set():
                    try:
                        audio_data = self.audio_queue.get(timeout=0.1)
                        if audio_data is None:  # Error signal
                            self._debug_log("Received error signal from recording thread")
                            return None
                        self.buffer = np.concatenate([self.buffer, audio_data])
                        queue_gets += 1
                    except queue.Empty:
                        continue
                
                if len(self.buffer) >= self.chunk_samples:
                    # Extract chunk
                    chunk = self.buffer[:self.chunk_samples]
                    
                    # Keep overlap for next chunk
                    if self.overlap_samples > 0:
                        self.buffer = self.buffer[self.chunk_samples - self.overlap_samples:]
                    else:
                        self.buffer = self.buffer[self.chunk_samples:]
                    
                    self.debug_stats['total_chunks_processed'] += 1
                    chunk_time = time.time() - start_time
                    
                    # Check if chunk has enough audio (not just silence)
                    if self._has_audio(chunk):
                        self.debug_stats['chunks_with_audio'] += 1
                        
                        # Save chunk to temporary file
                        temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                        self._save_chunk_to_file(chunk, temp_file.name)
                        temp_file.close()
                        
                        self._debug_log(f"Chunk {self.debug_stats['total_chunks_processed']}: "
                                      f"has audio, saved to {temp_file.name} "
                                      f"(collected from {queue_gets} queue items in {chunk_time:.2f}s)")
                        
                        return temp_file.name
                    else:
                        self.debug_stats['chunks_skipped_silence'] += 1
                        self._debug_log(f"Chunk {self.debug_stats['total_chunks_processed']}: "
                                      f"skipped (silence), RMS below threshold "
                                      f"(collected from {queue_gets} queue items in {chunk_time:.2f}s)")
                        
                        # Continue to next chunk
                        start_time = time.time()
                        continue
                        
            except Exception as e:
                self._debug_log(f"Error in get_next_chunk: {e}")
                self.debug_stats['processing_errors'] += 1
                continue
                
        self._debug_log("get_next_chunk exiting due to stop event")
        return None
    
    def get_next_vad_chunk(self):
        """Get the next audio chunk using Voice Activity Detection."""
        start_time = time.time()
        
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
        
        # Additional statistics for debugging
        max_val = np.max(np.abs(audio_data))
        min_val = np.min(audio_data)
        mean_val = np.mean(audio_data)
        
        has_audio = normalized_rms > self.silence_threshold
        
        self._debug_log(f"Audio analysis: RMS={normalized_rms:.6f}, "
                       f"max={max_val}, min={min_val}, mean={mean_val:.2f}, "
                       f"threshold={self.silence_threshold}, has_audio={has_audio}")
        
        return has_audio
    
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
    
    def print_debug_stats(self):
        """Print debug statistics."""
        if self.debug:
            self._debug_log("=== STREAMING STATISTICS ===")
            self._debug_log(f"Total chunks processed: {self.debug_stats['total_chunks_processed']}")
            self._debug_log(f"Chunks with audio: {self.debug_stats['chunks_with_audio']}")
            self._debug_log(f"Chunks skipped (silence): {self.debug_stats['chunks_skipped_silence']}")
            
            if self.vad_mode:
                self._debug_log(f"VAD chunks by silence: {self.debug_stats['vad_chunks_by_silence']}")
                self._debug_log(f"VAD chunks by max duration: {self.debug_stats['vad_chunks_by_max_duration']}")
                self._debug_log(f"VAD current state: {'Speech' if self.vad_in_speech else 'Silence'}")
                self._debug_log(f"VAD speech buffer size: {len(self.vad_speech_buffer)} samples")
                self._debug_log(f"VAD consecutive silence frames: {self.vad_consecutive_silence_frames}")
            
            self._debug_log(f"Total bytes read: {self.debug_stats['bytes_read']}")
            self._debug_log(f"FFmpeg errors: {self.debug_stats['ffmpeg_errors']}")
            self._debug_log(f"Processing errors: {self.debug_stats['processing_errors']}")
            self._debug_log(f"Buffer size: {len(self.buffer)} samples")
            self._debug_log(f"Queue size: {self.audio_queue.qsize()}")
            self._debug_log("=============================")
    
    def cleanup(self):
        """Clean up resources."""
        self.print_debug_stats()
        self.stop_streaming()


@click.command()
@click.option('--model', default='base', 
              type=click.Choice(['tiny', 'base', 'small', 'medium', 'large', 'turbo']),
              help='Whisper model to use')
@click.option('--language', default=None, 
              help='Language code (e.g., "en", "es", "fr"). Auto-detect if not specified.')
@click.option('--verbose', is_flag=True, help='Enable verbose output')
@click.option('--batch', is_flag=True, help='Enable batch recording mode (record once, then transcribe)')
@click.option('--chunk-duration', default=5.0, type=float,
              help='Duration of each audio chunk in seconds (streaming mode)')
@click.option('--overlap-duration', default=1.0, type=float,
              help='Overlap between chunks in seconds (streaming mode)')
@click.option('--silence-threshold', default=0.01, type=float,
              help='Silence threshold for detecting empty segments (streaming mode)')
@click.option('--debug', is_flag=True, help='Enable detailed debug output for troubleshooting')
@click.option('--newlines', is_flag=True, help='Output text with newlines (default is space-separated)')
@click.option('--vad-silence-duration', default=0.5, type=float,
              help='Duration of silence required to end a chunk in VAD mode (seconds)')
@click.option('--vad-max-duration', default=30.0, type=float,
              help='Maximum chunk duration in VAD mode (seconds)')
def main(model, language, verbose, batch, chunk_duration, overlap_duration, silence_threshold, debug, newlines, vad_silence_duration, vad_max_duration):
    """Record audio from microphone and transcribe it using OpenAI Whisper."""
    
    def output_text(text):
        """Output text with proper formatting based on newlines flag."""
        if newlines:
            print(text.strip(), flush=True)
        else:
            print(text.strip(), end=' ', flush=True)
    
    if verbose:
        click.echo(f"Loading Whisper model: {model}", err=True)
    
    # Load Whisper model
    try:
        whisper_model = WhisperModel(model, device="auto")
    except Exception as e:
        click.echo(f"Error loading Whisper model: {e}", err=True)
        sys.exit(1)
    
    if not batch:
        # Streaming mode (default)
        if verbose or debug:
            click.echo(f"Starting VAD streaming mode (silence: {vad_silence_duration}s, max: {vad_max_duration}s)", err=True)
        
        # Use Windows-specific audio recorder on Windows if available
        current_platform = platform.system().lower()
        if current_platform == "windows" and SOUNDDEVICE_AVAILABLE:
            if debug:
                click.echo("[DEBUG] Using Windows native audio recorder (sounddevice)", err=True)
            recorder = WindowsAudioRecorder(
                chunk_duration=chunk_duration,
                overlap_duration=overlap_duration,
                silence_threshold=silence_threshold,
                debug=debug,
                vad_mode=True,
                vad_silence_duration=vad_silence_duration,
                vad_max_duration=vad_max_duration
            )
        else:
            if debug and current_platform == "windows":
                click.echo("[DEBUG] sounddevice not available, falling back to FFmpeg", err=True)
            recorder = StreamingRecorder(
                chunk_duration=chunk_duration,
                overlap_duration=overlap_duration,
                silence_threshold=silence_threshold,
                debug=debug,
                vad_mode=True,
                vad_silence_duration=vad_silence_duration,
                vad_max_duration=vad_max_duration
            )
        
        click.echo("Press Ctrl+C to stop streaming...", err=True)
        
        try:
            recorder.start_streaming()
            
            if debug:
                click.echo("[DEBUG] Started streaming, beginning chunk processing...", err=True)
            
            chunk_count = 0
            transcription_count = 0
            
            # Process chunks continuously
            while True:
                chunk_file = recorder.get_next_vad_chunk()
                    
                if chunk_file is None:
                    if debug:
                        click.echo(f"[DEBUG] get_next_vad_chunk returned None, exiting loop", err=True)
                    break
                
                chunk_count += 1
                
                try:
                    # Transcribe chunk
                    transcribe_start = time.time()
                    segments, info = whisper_model.transcribe(chunk_file, language=language)
                    transcribe_time = time.time() - transcribe_start
                    
                    if debug:
                        click.echo(f"[DEBUG] Transcribed chunk {chunk_count} in {transcribe_time:.2f}s", err=True)
                    
                    # Output transcription immediately
                    segment_count = 0
                    for segment in segments:
                        if segment.text.strip():
                            output_text(segment.text)
                            segment_count += 1
                            transcription_count += 1
                    
                    if debug:
                        click.echo(f"[DEBUG] Chunk {chunk_count} produced {segment_count} segments", err=True)
                    
                    # Clean up chunk file
                    os.unlink(chunk_file)
                    
                except Exception as e:
                    if verbose or debug:
                        click.echo(f"[ERROR] Error processing chunk {chunk_count}: {e}", err=True)
                    # Clean up chunk file on error
                    try:
                        os.unlink(chunk_file)
                    except:
                        pass
                    continue
                    
        except KeyboardInterrupt:
            if verbose or debug:
                click.echo(f"\n[DEBUG] Stopping streaming... (processed {chunk_count} chunks, {transcription_count} transcriptions)", err=True)
        except Exception as e:
            click.echo(f"Error during streaming: {e}", err=True)
            sys.exit(1)
        finally:
            recorder.cleanup()
    
    else:
        # Batch mode
        recorder = FFmpegRecorder()
        
        click.echo("Press Ctrl+C to stop recording and transcribe...", err=True)
        
        try:
            temp_filename = recorder.start_recording()
            
            # Wait for user to stop recording
            try:
                while recorder.process and recorder.process.poll() is None:
                    time.sleep(0.1)
            except KeyboardInterrupt:
                click.echo("\nStopping recording...", err=True)
            
            # Stop recording and get the recorded file
            recorded_file = recorder.stop_recording()
            
            if not recorded_file or not os.path.exists(recorded_file):
                click.echo("No audio data recorded.", err=True)
                recorder.cleanup()
                sys.exit(1)
            
            if verbose:
                click.echo("Processing audio with Whisper...", err=True)
            
            # Transcribe with Whisper
            segments, info = whisper_model.transcribe(recorded_file, language=language)
            
            # Output transcription to stdout
            if newlines:
                # For newlines mode, output each segment separately
                for segment in segments:
                    if segment.text.strip():
                        output_text(segment.text)
            else:
                # For default mode, output all segments as space-separated text
                text = " ".join(segment.text for segment in segments)
                output_text(text)
            
        except Exception as e:
            click.echo(f"Error during recording/transcription: {e}", err=True)
            sys.exit(1)
        finally:
            recorder.cleanup()


if __name__ == '__main__':
    main()