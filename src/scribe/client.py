#!/usr/bin/env python3
"""Scribe client - lightweight interface to daemon."""

import sys
import time
import signal
import subprocess
import click
from typing import Optional

# Handle both module and script execution
try:
    from .ipc import ScribeIPCClient, ScribeStreamingClient
except ImportError:
    from scribe.ipc import ScribeIPCClient, ScribeStreamingClient


class ScribeClient:
    """Client for interacting with Scribe daemon."""
    
    def __init__(self, socket_path: Optional[str] = None):
        self.client = ScribeIPCClient(socket_path)
        self.streaming_client = ScribeStreamingClient(socket_path)
        self.daemon_process = None
        
    def ensure_daemon_running(self, model: str = "base", debug: bool = False) -> bool:
        """Ensure daemon is running, start if necessary."""
        if self.client.is_daemon_running():
            # Try to connect to existing daemon
            if self.client.connect(timeout=2):
                return True
            else:
                print("Daemon socket exists but connection failed", file=sys.stderr)
                return False
        
        # Start new daemon
        print("Starting Scribe daemon...", file=sys.stderr)
        
        try:
            cmd = [sys.executable, "-m", "scribe.daemon", "--model", model]
            if debug:
                cmd.append("--debug")
                
            self.daemon_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            # Wait for daemon to be ready
            max_wait = 10  # seconds
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                if self.client.connect(timeout=0.5):
                    print("Daemon started successfully", file=sys.stderr)
                    return True
                time.sleep(0.1)
                
            print("Daemon failed to start within timeout", file=sys.stderr)
            return False
            
        except Exception as e:
            print(f"Error starting daemon: {e}", file=sys.stderr)
            return False
            
    def configure(self, **config) -> bool:
        """Configure the daemon."""
        if not self.client.connected:
            return False
            
        response = self.client.send_command("configure", **config)
        return response.get("status") == "success"
        
    def get_status(self) -> dict:
        """Get daemon status."""
        if not self.client.connected:
            return {"status": "error", "message": "Not connected"}
            
        return self.client.send_command("get_status")
        
    def start_recording(self) -> bool:
        """Start recording session."""
        if not self.client.connected:
            return False
            
        response = self.client.send_command("start_recording")
        return response.get("status") == "success"
        
    def stop_recording(self) -> bool:
        """Stop recording session."""
        if not self.client.connected:
            return False
            
        response = self.client.send_command("stop_recording")
        return response.get("status") == "success"
        
    def shutdown_daemon(self) -> bool:
        """Shutdown the daemon."""
        if not self.client.connected:
            return False
            
        response = self.client.send_command("shutdown")
        success = response.get("status") == "success"
        
        if success:
            self.client.disconnect()
            
        return success
        
    def stream_transcription(self, output_newlines: bool = False):
        """Stream transcription results to stdout."""
        if not self.streaming_client.connect():
            print("Failed to connect to daemon", file=sys.stderr)
            return False
            
        # Set up signal handler for graceful shutdown
        def signal_handler(signum, frame):
            print("\nStopping...", file=sys.stderr)
            self.streaming_client.stop_streaming()
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Define callback functions
        def on_transcription(text):
            if output_newlines:
                print(text.strip(), flush=True)
            else:
                print(text.strip(), end=' ', flush=True)
                
        def on_error(error):
            print(f"Error: {error}", file=sys.stderr)
            
        # Start streaming
        self.streaming_client.start_streaming(
            on_transcription=on_transcription,
            on_error=on_error
        )
        
        # Keep running until stopped
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.streaming_client.stop_streaming()
            self.streaming_client.disconnect()
            
        return True
        
    def cleanup(self):
        """Clean up resources."""
        if self.streaming_client:
            self.streaming_client.disconnect()
        if self.client:
            self.client.disconnect()
        if self.daemon_process:
            try:
                self.daemon_process.terminate()
                self.daemon_process.wait(timeout=5)
            except:
                try:
                    self.daemon_process.kill()
                    self.daemon_process.wait()
                except:
                    pass


def output_text(text, newlines):
    """Output text with proper formatting based on newlines flag."""
    if newlines:
        print(text.strip(), flush=True)
    else:
        print(text.strip(), end=' ', flush=True)


@click.command()
@click.option('--model', default='base', 
              type=click.Choice(['tiny', 'base', 'small', 'medium', 'large', 'turbo']),
              help='Whisper model to use')
@click.option('--language', default=None, 
              help='Language code (e.g., "en", "es", "fr"). Auto-detect if not specified.')
@click.option('--verbose', is_flag=True, help='Enable verbose output')
@click.option('--batch', is_flag=True, help='Enable batch recording mode (not supported in daemon mode)')
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
@click.option('--daemon-only', is_flag=True, help='Only start daemon, do not begin recording')
@click.option('--shutdown-daemon', is_flag=True, help='Shutdown running daemon')
@click.option('--status', is_flag=True, help='Show daemon status')
def main(model, language, verbose, batch, chunk_duration, overlap_duration, 
         silence_threshold, debug, newlines, vad_silence_duration, vad_max_duration,
         daemon_only, shutdown_daemon, status):
    """Record audio from microphone and transcribe it using OpenAI Whisper (daemon mode)."""
    
    client = ScribeClient()
    
    try:
        if shutdown_daemon:
            if not client.client.is_daemon_running():
                click.echo("Daemon not running", err=True)
                return
                
            if not client.client.connect():
                click.echo("Failed to connect to daemon", err=True)
                return
                
            if client.shutdown_daemon():
                click.echo("Daemon shutdown successful", err=True)
            else:
                click.echo("Failed to shutdown daemon", err=True)
            return
            
        if status:
            if not client.client.is_daemon_running():
                click.echo("Daemon not running", err=True)
                return
                
            if not client.client.connect():
                click.echo("Failed to connect to daemon", err=True)
                return
                
            status_info = client.get_status()
            if status_info.get("status") == "success":
                click.echo(f"Daemon Status:", err=True)
                click.echo(f"  Recording: {status_info.get('recording', False)}", err=True)
                click.echo(f"  Model: {status_info.get('model', 'unknown')}", err=True)
                click.echo(f"  Config: {status_info.get('config', {})}", err=True)
            else:
                click.echo(f"Error getting status: {status_info.get('message', 'unknown')}", err=True)
            return
            
        if batch:
            click.echo("Batch mode not supported in daemon mode", err=True)
            return
            
        # Ensure daemon is running
        if not client.ensure_daemon_running(model=model, debug=debug):
            click.echo("Failed to start daemon", err=True)
            return
            
        # Configure daemon
        config = {
            "model": model,
            "language": language,
            "chunk_duration": chunk_duration,
            "overlap_duration": overlap_duration,
            "silence_threshold": silence_threshold,
            "vad_silence_duration": vad_silence_duration,
            "vad_max_duration": vad_max_duration,
            "debug": debug
        }
        
        if not client.configure(**config):
            click.echo("Failed to configure daemon", err=True)
            return
            
        if daemon_only:
            click.echo("Daemon started and configured", err=True)
            return
            
        if verbose:
            click.echo(f"Connected to daemon with model: {model}", err=True)
            
        # Start streaming mode
        if verbose or debug:
            click.echo(f"Starting VAD streaming mode (silence: {vad_silence_duration}s, max: {vad_max_duration}s)", err=True)
            
        click.echo("Press Ctrl+C to stop streaming...", err=True)
        
        # Stream transcription
        client.stream_transcription(output_newlines=newlines)
        
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1
    finally:
        client.cleanup()


if __name__ == '__main__':
    main()