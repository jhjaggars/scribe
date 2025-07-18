#!/usr/bin/env python3
"""Startup profiling script for scribe - measures timing of each startup step."""

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

class StartupProfiler:
    """Measures timing of each startup step."""
    
    def __init__(self):
        self.start_time = time.perf_counter()
        self.timings = {}
        self.step_count = 0
        
    def time_step(self, step_name):
        """Record timing for a step."""
        current_time = time.perf_counter()
        elapsed = current_time - self.start_time
        self.timings[step_name] = elapsed
        self.step_count += 1
        click.echo(f"[PROFILE] Step {self.step_count}: {step_name} - {elapsed:.4f}s (cumulative)", err=True)
        return current_time
    
    def print_summary(self):
        """Print summary of all timing measurements."""
        click.echo(f"\n[PROFILE] ===== STARTUP TIMING SUMMARY =====", err=True)
        
        prev_time = 0
        for i, (step, cumulative_time) in enumerate(self.timings.items(), 1):
            step_duration = cumulative_time - prev_time
            click.echo(f"[PROFILE] {i:2d}. {step:<50} {step_duration:8.4f}s", err=True)
            prev_time = cumulative_time
        
        total_time = list(self.timings.values())[-1] if self.timings else 0
        click.echo(f"[PROFILE] {'='*60}", err=True)
        click.echo(f"[PROFILE] {'TOTAL STARTUP TIME':<50} {total_time:8.4f}s", err=True)
        click.echo(f"[PROFILE] {'='*60}", err=True)

# Global profiler instance
profiler = StartupProfiler()

# Step 1: CUDA Setup and Process Re-execution
profiler.time_step("Script start")

def setup_cudnn_path():
    """Automatically detect and set cuDNN library path."""
    setup_start = time.perf_counter()
    try:
        import nvidia.cudnn
        cudnn_lib_path = Path(nvidia.cudnn.__file__).parent / "lib"
        if cudnn_lib_path.exists():
            current_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
            if str(cudnn_lib_path) not in current_ld_path:
                new_ld_path = f"{cudnn_lib_path}:{current_ld_path}" if current_ld_path else str(cudnn_lib_path)
                setup_time = time.perf_counter() - setup_start
                click.echo(f"[PROFILE] CUDA setup detected cuDNN, re-executing process (setup took {setup_time:.4f}s)", err=True)
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

profiler.time_step("CUDA setup completed")

# Step 2: Module Imports
import_start = time.perf_counter()

# Import faster_whisper (heavy import)
from faster_whisper import WhisperModel
profiler.time_step("faster_whisper import completed")

# Import other modules (should be fast)
# (already imported above)

profiler.time_step("All module imports completed")

# Copy the StreamingRecorder class from main.py for profiling
class StreamingRecorder:
    """Handles continuous microphone recording with chunked processing."""
    
    def __init__(self, sample_rate=16000, channels=1, chunk_duration=5.0, 
                 overlap_duration=1.0, silence_threshold=0.01, debug=False,
                 vad_mode=False, vad_silence_duration=0.5, vad_max_duration=30.0):
        init_start = time.perf_counter()
        
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
        
        init_time = time.perf_counter() - init_start
        click.echo(f"[PROFILE] StreamingRecorder initialization took {init_time:.4f}s", err=True)
        
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
        detection_start = time.perf_counter()
        
        if self.platform == "linux":
            try:
                subprocess.run(["arecord", "-l"], capture_output=True, check=True)
                result = ["-f", "alsa", "-i", "default"]
                method = "ALSA"
            except:
                result = ["-f", "pulse", "-i", "default"]
                method = "PulseAudio"
        elif self.platform == "darwin":  # macOS
            result = ["-f", "avfoundation", "-i", ":0"]
            method = "AVFoundation"
        elif self.platform == "windows":
            result = ["-f", "dshow", "-i", "audio="]
            method = "DirectShow"
        else:
            result = ["-f", "pulse", "-i", "default"]
            method = "PulseAudio (fallback)"
        
        detection_time = time.perf_counter() - detection_start
        click.echo(f"[PROFILE] Audio input detection ({method}) took {detection_time:.4f}s", err=True)
        
        return result
    
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
        
        ffmpeg_start = time.perf_counter()
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                bufsize=0
            )
            
            ffmpeg_launch_time = time.perf_counter() - ffmpeg_start
            click.echo(f"[PROFILE] FFmpeg process launch took {ffmpeg_launch_time:.4f}s", err=True)
            
            self._debug_log(f"FFmpeg process started with PID: {self.process.pid}")
            
            # Skip WAV header (44 bytes)
            header_start = time.perf_counter()
            header = self.process.stdout.read(44)
            if len(header) < 44:
                self._debug_log(f"Failed to read WAV header, got {len(header)} bytes")
                return
            
            header_time = time.perf_counter() - header_start
            click.echo(f"[PROFILE] WAV header read took {header_time:.4f}s", err=True)
            
            self._debug_log(f"WAV header read successfully ({len(header)} bytes)")
            
            # Read audio data in small chunks
            read_size = self.sample_rate * 2 // 10  # 0.1 second chunks
            self._debug_log(f"Reading audio in chunks of {read_size} bytes")
            
            bytes_read_total = 0
            read_count = 0
            
            # Signal that we're ready to receive audio
            first_chunk_time = time.perf_counter()
            first_chunk_received = False
            
            while not self.stop_event.is_set() and self.process.poll() is None:
                try:
                    data = self.process.stdout.read(read_size)
                    if not data:
                        self._debug_log("No data received from FFmpeg, breaking")
                        break
                    
                    if not first_chunk_received:
                        chunk_ready_time = time.perf_counter() - first_chunk_time
                        click.echo(f"[PROFILE] First audio chunk ready took {chunk_ready_time:.4f}s", err=True)
                        first_chunk_received = True
                    
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
            ffmpeg_error_time = time.perf_counter() - ffmpeg_start
            click.echo(f"[PROFILE] FFmpeg process failed after {ffmpeg_error_time:.4f}s: {e}", err=True)
            self.debug_stats['ffmpeg_errors'] += 1
            self.audio_queue.put(None)
    
    def start_streaming(self):
        """Start continuous audio streaming."""
        streaming_start = time.perf_counter()
        
        self.stop_event.clear()
        self.recording_thread = threading.Thread(target=self._recording_worker)
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
        streaming_time = time.perf_counter() - streaming_start
        click.echo(f"[PROFILE] Streaming thread start took {streaming_time:.4f}s", err=True)
        
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


@click.command()
@click.option('--model', default='base', 
              type=click.Choice(['tiny', 'base', 'small', 'medium', 'large', 'turbo']),
              help='Whisper model to use')
@click.option('--language', default=None, 
              help='Language code (e.g., "en", "es", "fr"). Auto-detect if not specified.')
@click.option('--verbose', is_flag=True, help='Enable verbose output')
@click.option('--debug', is_flag=True, help='Enable detailed debug output for troubleshooting')
@click.option('--vad-silence-duration', default=0.5, type=float,
              help='Duration of silence required to end a chunk in VAD mode (seconds)')
@click.option('--vad-max-duration', default=30.0, type=float,
              help='Maximum chunk duration in VAD mode (seconds)')
@click.option('--run-duration', default=10.0, type=float,
              help='How long to run the profiling test (seconds)')
def main(model, language, verbose, debug, vad_silence_duration, vad_max_duration, run_duration):
    """Profile startup performance of scribe streaming mode."""
    
    # Step 3: CLI Argument Processing
    profiler.time_step("CLI argument processing completed")
    
    if verbose:
        click.echo(f"[PROFILE] Profiling Whisper model: {model}", err=True)
    
    # Step 4: Whisper Model Loading
    model_start = time.perf_counter()
    try:
        whisper_model = WhisperModel(model, device="auto")
        model_time = time.perf_counter() - model_start
        click.echo(f"[PROFILE] Whisper model ({model}) loading took {model_time:.4f}s", err=True)
    except Exception as e:
        click.echo(f"[PROFILE] Error loading Whisper model: {e}", err=True)
        sys.exit(1)
    
    profiler.time_step("Whisper model loading completed")
    
    # Step 5: StreamingRecorder Initialization
    recorder_start = time.perf_counter()
    recorder = StreamingRecorder(
        chunk_duration=5.0,
        overlap_duration=1.0,
        silence_threshold=0.01,
        debug=debug,
        vad_mode=True,
        vad_silence_duration=vad_silence_duration,
        vad_max_duration=vad_max_duration
    )
    recorder_time = time.perf_counter() - recorder_start
    click.echo(f"[PROFILE] StreamingRecorder creation took {recorder_time:.4f}s", err=True)
    
    profiler.time_step("StreamingRecorder initialization completed")
    
    # Step 6: Audio Input Detection and FFmpeg Launch
    # This happens when start_streaming is called
    streaming_start = time.perf_counter()
    
    if verbose or debug:
        click.echo(f"[PROFILE] Starting VAD streaming mode (silence: {vad_silence_duration}s, max: {vad_max_duration}s)", err=True)
    
    click.echo("[PROFILE] Starting streaming (press Ctrl+C to stop early)...", err=True)
    
    try:
        recorder.start_streaming()
        streaming_time = time.perf_counter() - streaming_start
        click.echo(f"[PROFILE] Full streaming startup took {streaming_time:.4f}s", err=True)
        
        profiler.time_step("Streaming fully operational")
        
        # Print summary before running
        profiler.print_summary()
        
        # Run for specified duration to test actual operation
        click.echo(f"[PROFILE] Running for {run_duration}s to test operation...", err=True)
        
        start_run = time.perf_counter()
        while time.perf_counter() - start_run < run_duration:
            time.sleep(0.1)
        
        click.echo("[PROFILE] Profiling complete!", err=True)
        
    except KeyboardInterrupt:
        click.echo("\n[PROFILE] Profiling interrupted by user", err=True)
        profiler.print_summary()
    except Exception as e:
        click.echo(f"[PROFILE] Error during streaming: {e}", err=True)
        profiler.print_summary()
        sys.exit(1)
    finally:
        recorder.cleanup()


if __name__ == '__main__':
    main()