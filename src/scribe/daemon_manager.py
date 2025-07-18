"""Daemon process management utilities."""

import os
import sys
import time
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

# Handle both module and script execution
try:
    from .ipc import ScribeIPCClient
except ImportError:
    from scribe.ipc import ScribeIPCClient


class DaemonManager:
    """Manages daemon process lifecycle."""
    
    def __init__(self, socket_path: Optional[str] = None):
        self.socket_path = socket_path
        self.client = ScribeIPCClient(socket_path)
        self.pid_file = Path(tempfile.gettempdir()) / "scribe_daemon.pid"
        
    def is_daemon_running(self) -> bool:
        """Check if daemon is running."""
        # Check if socket exists
        if not self.client.is_daemon_running():
            return False
            
        # Try to connect
        if not self.client.connect(timeout=1):
            return False
            
        # Check if daemon responds
        try:
            response = self.client.send_command("get_status")
            return response.get("status") == "success"
        except (ConnectionError, TimeoutError, OSError):
            # Connection issues indicate daemon not responding properly
            return False
        finally:
            self.client.disconnect()
            
    def start_daemon(self, model: str = "base", debug: bool = False, 
                    background: bool = True) -> bool:
        """Start daemon process."""
        if self.is_daemon_running():
            print("Daemon already running", file=sys.stderr)
            return True
            
        print("Starting Scribe daemon...", file=sys.stderr)
        
        try:
            cmd = [sys.executable, "-m", "scribe.daemon", "--model", model]
            if debug:
                cmd.append("--debug")
            if self.socket_path:
                cmd.extend(["--socket-path", self.socket_path])
                
            if background:
                # Start daemon in background
                # Security: Use start_new_session instead of preexec_fn to avoid potential vulnerabilities
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True  # Create new process group (safer than preexec_fn)
                )
                
                # Save PID with secure permissions (0600 - owner read/write only)
                # Create the file with secure permissions before writing
                fd = os.open(self.pid_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
                try:
                    with os.fdopen(fd, 'w') as f:
                        f.write(str(process.pid))
                except (OSError, IOError) as e:
                    os.close(fd)  # Close if fdopen fails
                    raise OSError(f"Failed to write PID file: {e}")
                    
            else:
                # Start daemon in foreground
                process = subprocess.Popen(cmd)
                
            # Wait for daemon to be ready
            max_wait = 15  # seconds
            start_time = time.time()
            
            while time.time() - start_time < max_wait:
                if self.is_daemon_running():
                    print("Daemon started successfully", file=sys.stderr)
                    return True
                time.sleep(0.1)
                
            print("Daemon failed to start within timeout", file=sys.stderr)
            return False
            
        except Exception as e:
            print(f"Error starting daemon: {e}", file=sys.stderr)
            return False
            
    def stop_daemon(self, force: bool = False) -> bool:
        """Stop daemon process."""
        if not self.is_daemon_running():
            print("Daemon not running", file=sys.stderr)
            return True
            
        print("Stopping daemon...", file=sys.stderr)
        
        try:
            if not force:
                # Try graceful shutdown first
                if self.client.connect(timeout=2):
                    response = self.client.send_command("shutdown")
                    if response.get("status") == "success":
                        # Wait for daemon to stop
                        max_wait = 5
                        start_time = time.time()
                        
                        while time.time() - start_time < max_wait:
                            if not self.is_daemon_running():
                                print("Daemon stopped gracefully", file=sys.stderr)
                                self._cleanup_pid_file()
                                return True
                            time.sleep(0.1)
                            
            # Force shutdown using PID file
            if self.pid_file.exists():
                try:
                    with open(self.pid_file, 'r') as f:
                        pid = int(f.read().strip())
                        
                    # Send SIGTERM
                    os.kill(pid, signal.SIGTERM)
                    
                    # Wait for process to stop
                    max_wait = 5
                    start_time = time.time()
                    
                    while time.time() - start_time < max_wait:
                        try:
                            os.kill(pid, 0)  # Check if process exists
                            time.sleep(0.1)
                        except ProcessLookupError:
                            print("Daemon stopped", file=sys.stderr)
                            self._cleanup_pid_file()
                            return True
                            
                    # Force kill if still running
                    try:
                        os.kill(pid, signal.SIGKILL)
                        print("Daemon force killed", file=sys.stderr)
                    except ProcessLookupError:
                        pass
                        
                    self._cleanup_pid_file()
                    return True
                    
                except (ValueError, ProcessLookupError):
                    # PID file is stale
                    self._cleanup_pid_file()
                    return True
                    
            print("Failed to stop daemon", file=sys.stderr)
            return False
            
        except Exception as e:
            print(f"Error stopping daemon: {e}", file=sys.stderr)
            return False
        finally:
            self.client.disconnect()
            
    def restart_daemon(self, model: str = "base", debug: bool = False) -> bool:
        """Restart daemon process."""
        print("Restarting daemon...", file=sys.stderr)
        
        if not self.stop_daemon():
            return False
            
        time.sleep(1)  # Give some time for cleanup
        
        return self.start_daemon(model=model, debug=debug)
        
    def get_daemon_status(self) -> Dict[str, Any]:
        """Get daemon status information."""
        if not self.is_daemon_running():
            return {"status": "not_running"}
            
        try:
            if self.client.connect(timeout=2):
                response = self.client.send_command("get_status")
                return response
            else:
                return {"status": "error", "message": "Failed to connect"}
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            self.client.disconnect()
            
    def configure_daemon(self, **config) -> bool:
        """Configure running daemon."""
        if not self.is_daemon_running():
            return False
            
        try:
            if self.client.connect(timeout=2):
                response = self.client.send_command("configure", **config)
                return response.get("status") == "success"
            else:
                return False
        except Exception as e:
            print(f"Error configuring daemon: {e}", file=sys.stderr)
            return False
        finally:
            self.client.disconnect()
            
    def _cleanup_pid_file(self):
        """Clean up PID file."""
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
        except (PermissionError, OSError) as e:
            print(f"Warning: Could not remove PID file {self.pid_file}: {e}", file=sys.stderr)


def main():
    """Command line interface for daemon management."""
    import click
    
    @click.command()
    @click.option('--socket-path', default=None, help='Path to IPC socket')
    @click.option('--model', default='base', 
                  type=click.Choice(['tiny', 'base', 'small', 'medium', 'large', 'turbo']),
                  help='Whisper model to use')
    @click.option('--debug', is_flag=True, help='Enable debug output')
    @click.option('--foreground', is_flag=True, help='Run daemon in foreground')
    @click.argument('action', type=click.Choice(['start', 'stop', 'restart', 'status', 'force-stop']))
    def cli(socket_path, model, debug, foreground, action):
        """Manage Scribe daemon process."""
        manager = DaemonManager(socket_path)
        
        if action == 'start':
            success = manager.start_daemon(model=model, debug=debug, background=not foreground)
            sys.exit(0 if success else 1)
            
        elif action == 'stop':
            success = manager.stop_daemon()
            sys.exit(0 if success else 1)
            
        elif action == 'force-stop':
            success = manager.stop_daemon(force=True)
            sys.exit(0 if success else 1)
            
        elif action == 'restart':
            success = manager.restart_daemon(model=model, debug=debug)
            sys.exit(0 if success else 1)
            
        elif action == 'status':
            status = manager.get_daemon_status()
            if status.get("status") == "not_running":
                print("Daemon not running")
            elif status.get("status") == "success":
                print("Daemon running")
                print(f"  Recording: {status.get('recording', False)}")
                print(f"  Model: {status.get('model', 'unknown')}")
                config = status.get('config', {})
                if config:
                    print("  Configuration:")
                    for key, value in config.items():
                        print(f"    {key}: {value}")
            else:
                print(f"Error: {status.get('message', 'unknown')}")
                sys.exit(1)
                
    cli()


if __name__ == '__main__':
    main()