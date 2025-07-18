"""IPC protocol implementation for scribe daemon communication."""

import json
import socket
import threading
import time
import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Callable


class ScribeIPCProtocol:
    """Handles IPC communication between daemon and clients."""
    
    def __init__(self, socket_path: Optional[str] = None):
        if socket_path is None:
            # Use a default socket path in temp directory
            self.socket_path = Path(tempfile.gettempdir()) / "scribe_daemon.sock"
        else:
            self.socket_path = Path(socket_path)
        
    def ensure_socket_dir(self):
        """Ensure socket directory exists."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
    
    def cleanup_socket(self):
        """Remove socket file if it exists.
        
        Security Note: Use exception handling to avoid TOCTOU (Time-of-Check-Time-of-Use)
        race condition vulnerabilities.
        """
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            # Socket file doesn't exist, which is fine
            pass
        except PermissionError:
            # Permission denied - log the error but continue
            print(f"Warning: Permission denied removing socket {self.socket_path}", file=sys.stderr)
        except OSError as e:
            # Other OS errors
            print(f"Warning: Error removing socket {self.socket_path}: {e}", file=sys.stderr)


class ScribeIPCServer:
    """IPC server for daemon process."""
    
    def __init__(self, socket_path: Optional[str] = None):
        self.protocol = ScribeIPCProtocol(socket_path)
        self.socket = None
        self.running = False
        self.clients = []
        self.handlers = {}
        self.server_thread = None
        
    def register_handler(self, command: str, handler: Callable[[Dict[str, Any]], Dict[str, Any]]):
        """Register a command handler."""
        self.handlers[command] = handler
        
    def start(self):
        """Start the IPC server."""
        if self.running:
            return
            
        self.protocol.ensure_socket_dir()
        self.protocol.cleanup_socket()
        
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.protocol.socket_path))
        
        # Set secure permissions on socket file (0600 - owner read/write only)
        try:
            os.chmod(self.protocol.socket_path, 0o600)
        except OSError as e:
            print(f"Warning: Could not set secure permissions on socket: {e}", file=sys.stderr)
        
        self.socket.listen(5)
        
        self.running = True
        self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self.server_thread.start()
        
    def stop(self):
        """Stop the IPC server."""
        if not self.running:
            return
            
        self.running = False
        
        # Close all client connections
        for client in self.clients[:]:
            try:
                client.close()
            except (OSError, socket.error):
                # Socket already closed or error closing
                pass
        self.clients.clear()
        
        # Close server socket
        if self.socket:
            try:
                self.socket.close()
            except (OSError, socket.error):
                # Socket already closed or error closing
                pass
            
        # Clean up socket file
        self.protocol.cleanup_socket()
        
        # Wait for server thread to finish
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2)
            
    def _server_loop(self):
        """Main server loop to accept connections."""
        while self.running:
            try:
                client_socket, address = self.socket.accept()
                self.clients.append(client_socket)
                
                # Handle client in separate thread
                client_thread = threading.Thread(
                    target=self._handle_client,
                    args=(client_socket,),
                    daemon=True
                )
                client_thread.start()
                
            except OSError:
                # Socket closed, exit loop
                break
            except Exception as e:
                print(f"Server error: {e}")
                
    def _handle_client(self, client_socket):
        """Handle a client connection."""
        try:
            while self.running:
                # Receive message
                data = client_socket.recv(4096)
                if not data:
                    break
                    
                try:
                    message = json.loads(data.decode('utf-8'))
                    response = self._process_message(message)
                    
                    # Send response
                    response_data = json.dumps(response).encode('utf-8')
                    client_socket.send(response_data)
                    
                except json.JSONDecodeError:
                    error_response = {
                        "status": "error",
                        "message": "Invalid JSON"
                    }
                    client_socket.send(json.dumps(error_response).encode('utf-8'))
                    
                except Exception as e:
                    error_response = {
                        "status": "error",
                        "message": str(e)
                    }
                    client_socket.send(json.dumps(error_response).encode('utf-8'))
                    
        except Exception as e:
            print(f"Client handler error: {e}")
        finally:
            try:
                client_socket.close()
            except:
                pass
            if client_socket in self.clients:
                self.clients.remove(client_socket)
                
    def _process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Process a message from client."""
        command = message.get("command")
        if not command:
            return {"status": "error", "message": "Missing command"}
            
        handler = self.handlers.get(command)
        if not handler:
            return {"status": "error", "message": f"Unknown command: {command}"}
            
        try:
            return handler(message)
        except Exception as e:
            return {"status": "error", "message": f"Handler error: {e}"}
    
    def broadcast_message(self, message: Dict[str, Any]):
        """Send a message to all connected clients."""
        message_data = json.dumps(message).encode('utf-8')
        
        for client in self.clients[:]:  # Copy list to avoid modification during iteration
            try:
                client.send(message_data)
            except:
                # Client disconnected, remove it
                try:
                    client.close()
                except:
                    pass
                if client in self.clients:
                    self.clients.remove(client)


class ScribeIPCClient:
    """IPC client for communicating with daemon."""
    
    def __init__(self, socket_path: Optional[str] = None):
        self.protocol = ScribeIPCProtocol(socket_path)
        self.socket = None
        self.connected = False
        
    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to daemon."""
        if self.connected:
            return True
            
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.socket.connect(str(self.protocol.socket_path))
                self.connected = True
                return True
            except (FileNotFoundError, ConnectionRefusedError):
                # Daemon not running, wait and retry
                time.sleep(0.1)
            except Exception as e:
                print(f"Connection error: {e}")
                return False
                
        return False
        
    def disconnect(self):
        """Disconnect from daemon."""
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.connected = False
        
    def send_command(self, command: str, **kwargs) -> Dict[str, Any]:
        """Send a command to daemon and return response."""
        if not self.connected:
            return {"status": "error", "message": "Not connected to daemon"}
            
        message = {"command": command, **kwargs}
        
        try:
            # Send message
            message_data = json.dumps(message).encode('utf-8')
            self.socket.send(message_data)
            
            # Receive response
            response_data = self.socket.recv(4096)
            if not response_data:
                return {"status": "error", "message": "Connection closed"}
                
            response = json.loads(response_data.decode('utf-8'))
            return response
            
        except json.JSONDecodeError:
            return {"status": "error", "message": "Invalid response from daemon"}
        except Exception as e:
            return {"status": "error", "message": f"Communication error: {e}"}
    
    def receive_message(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Receive a message from daemon (non-blocking)."""
        if not self.connected:
            return None
            
        try:
            self.socket.settimeout(timeout)
            data = self.socket.recv(4096)
            if not data:
                return None
                
            message = json.loads(data.decode('utf-8'))
            return message
            
        except socket.timeout:
            return None
        except json.JSONDecodeError:
            return {"status": "error", "message": "Invalid message from daemon"}
        except Exception as e:
            return {"status": "error", "message": f"Receive error: {e}"}
        finally:
            self.socket.settimeout(None)
            
    def is_daemon_running(self) -> bool:
        """Check if daemon is running."""
        return self.protocol.socket_path.exists()


class ScribeStreamingClient:
    """Streaming client for real-time transcription."""
    
    def __init__(self, socket_path: Optional[str] = None):
        self.client = ScribeIPCClient(socket_path)
        self.streaming = False
        self.stream_thread = None
        self.on_transcription = None
        self.on_error = None
        
    def connect(self, timeout: float = 5.0) -> bool:
        """Connect to daemon."""
        return self.client.connect(timeout)
        
    def disconnect(self):
        """Disconnect from daemon."""
        self.stop_streaming()
        self.client.disconnect()
        
    def start_streaming(self, on_transcription: Callable[[str], None], 
                       on_error: Callable[[str], None] = None):
        """Start streaming transcription."""
        if self.streaming:
            return
            
        self.on_transcription = on_transcription
        self.on_error = on_error
        
        # Send start command
        response = self.client.send_command("start_recording")
        if response.get("status") != "success":
            if self.on_error:
                self.on_error(f"Failed to start recording: {response.get('message', 'Unknown error')}")
            return
            
        self.streaming = True
        self.stream_thread = threading.Thread(target=self._stream_loop, daemon=True)
        self.stream_thread.start()
        
    def stop_streaming(self):
        """Stop streaming transcription."""
        if not self.streaming:
            return
            
        self.streaming = False
        
        # Send stop command
        self.client.send_command("stop_recording")
        
        # Wait for stream thread to finish
        if self.stream_thread and self.stream_thread.is_alive():
            self.stream_thread.join(timeout=2)
            
    def _stream_loop(self):
        """Stream transcription messages."""
        while self.streaming:
            message = self.client.receive_message(timeout=0.1)
            if message is None:
                continue
                
            if message.get("type") == "transcription":
                text = message.get("text", "")
                if text and self.on_transcription:
                    self.on_transcription(text)
                    
            elif message.get("status") == "error":
                error_msg = message.get("message", "Unknown error")
                if self.on_error:
                    self.on_error(error_msg)
                break
                
            elif message.get("type") == "recording_stopped":
                break