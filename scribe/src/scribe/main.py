#!/usr/bin/env python3
"""Main CLI script for scribe - real-time speech-to-text transcription."""

import os
import tempfile
import subprocess
import sys
import platform
import time
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


@click.command()
@click.option('--model', default='base', 
              type=click.Choice(['tiny', 'base', 'small', 'medium', 'large', 'turbo']),
              help='Whisper model to use')
@click.option('--language', default=None, 
              help='Language code (e.g., "en", "es", "fr"). Auto-detect if not specified.')
@click.option('--verbose', is_flag=True, help='Enable verbose output')
def main(model, language, verbose):
    """Record audio from microphone and transcribe it using OpenAI Whisper."""
    
    if verbose:
        click.echo(f"Loading Whisper model: {model}")
    
    # Load Whisper model
    try:
        whisper_model = WhisperModel(model, device="auto")
    except Exception as e:
        click.echo(f"Error loading Whisper model: {e}", err=True)
        sys.exit(1)
    
    # Initialize recorder
    recorder = FFmpegRecorder()
    
    click.echo("Press Ctrl+C to stop recording and transcribe...", err=True)
    
    # Start recording
    try:
        temp_filename = recorder.start_recording()
        
        # Wait for user to stop recording
        try:
            while recorder.process and recorder.process.poll() is None:
                time.sleep(0.1)  # Small delay to prevent busy waiting
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
        text = " ".join(segment.text for segment in segments)
        print(text.strip())
        
    except Exception as e:
        click.echo(f"Error during recording/transcription: {e}", err=True)
        sys.exit(1)
    finally:
        # Clean up
        recorder.cleanup()


if __name__ == '__main__':
    main()