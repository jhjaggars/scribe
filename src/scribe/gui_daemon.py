#!/usr/bin/env python3
"""GUI application for managing Scribe speech-to-text transcription with daemon support."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, GLib
import threading
import time

# Handle both module and script execution
try:
    from .daemon_manager import DaemonManager
    from .ipc import ScribeStreamingClient
except ImportError:
    from scribe.daemon_manager import DaemonManager
    from scribe.ipc import ScribeStreamingClient


class ScribeDaemonGUI:
    def __init__(self):
        # Daemon management
        self.daemon_manager = DaemonManager()
        self.streaming_client = None
        self.is_recording = False
        self.daemon_status_thread = None
        self.daemon_status_running = False
        
        # Process logging flags to prevent repetitive messages
        self.last_status_update = 0
        
        # Build the GUI
        self.build_ui()
        
        # Start daemon status monitoring
        self.start_daemon_status_monitoring()
        
    def build_ui(self):
        # Create main window
        self.window = Gtk.Window(title="Scribe - Speech-to-Text GUI (Daemon Mode)")
        self.window.set_default_size(600, 600)
        self.window.connect("destroy", self.on_window_destroy)
        
        # Create main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_left(10)
        main_box.set_margin_right(10)
        main_box.set_margin_top(10)
        main_box.set_margin_bottom(10)
        self.window.add(main_box)
        
        # Daemon status frame
        daemon_frame = Gtk.Frame(label="Daemon Status")
        daemon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        daemon_box.set_margin_left(10)
        daemon_box.set_margin_right(10)
        daemon_box.set_margin_top(10)
        daemon_box.set_margin_bottom(10)
        daemon_frame.add(daemon_box)
        main_box.pack_start(daemon_frame, False, False, 0)
        
        # Daemon status display
        daemon_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        daemon_status_label = Gtk.Label(label="Daemon Status:")
        daemon_status_label.set_size_request(120, -1)
        daemon_status_label.set_halign(Gtk.Align.START)
        daemon_status_box.pack_start(daemon_status_label, False, False, 0)
        
        self.daemon_status_value = Gtk.Label(label="Checking...")
        self.daemon_status_value.set_halign(Gtk.Align.START)
        daemon_status_box.pack_start(self.daemon_status_value, True, True, 0)
        daemon_box.pack_start(daemon_status_box, False, False, 0)
        
        # Daemon control buttons
        daemon_control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        self.start_daemon_button = Gtk.Button(label="Start Daemon")
        self.start_daemon_button.connect("clicked", self.on_start_daemon_clicked)
        daemon_control_box.pack_start(self.start_daemon_button, False, False, 0)
        
        self.stop_daemon_button = Gtk.Button(label="Stop Daemon")
        self.stop_daemon_button.connect("clicked", self.on_stop_daemon_clicked)
        daemon_control_box.pack_start(self.stop_daemon_button, False, False, 0)
        
        self.restart_daemon_button = Gtk.Button(label="Restart Daemon")
        self.restart_daemon_button.connect("clicked", self.on_restart_daemon_clicked)
        daemon_control_box.pack_start(self.restart_daemon_button, False, False, 0)
        
        daemon_box.pack_start(daemon_control_box, False, False, 0)
        
        # Settings frame
        settings_frame = Gtk.Frame(label="Settings")
        settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        settings_box.set_margin_left(10)
        settings_box.set_margin_right(10)
        settings_box.set_margin_top(10)
        settings_box.set_margin_bottom(10)
        settings_frame.add(settings_box)
        main_box.pack_start(settings_frame, False, False, 0)
        
        # Model selection
        model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        model_label = Gtk.Label(label="Whisper Model:")
        model_label.set_size_request(120, -1)
        model_label.set_halign(Gtk.Align.START)
        model_box.pack_start(model_label, False, False, 0)
        
        self.model_combo = Gtk.ComboBoxText()
        models = ["tiny", "base", "small", "medium", "large", "turbo"]
        for model in models:
            self.model_combo.append_text(model)
        self.model_combo.set_active(1)  # Default to "base"
        model_box.pack_start(self.model_combo, False, False, 0)
        settings_box.pack_start(model_box, False, False, 0)
        
        # Language selection
        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        lang_label = Gtk.Label(label="Language (optional):")
        lang_label.set_size_request(120, -1)
        lang_label.set_halign(Gtk.Align.START)
        lang_box.pack_start(lang_label, False, False, 0)
        
        self.language_entry = Gtk.Entry()
        self.language_entry.set_placeholder_text("e.g., en, es, fr")
        lang_box.pack_start(self.language_entry, True, True, 0)
        settings_box.pack_start(lang_box, False, False, 0)
        
        # Silence threshold
        threshold_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        threshold_label = Gtk.Label(label="Silence Threshold:")
        threshold_label.set_size_request(120, -1)
        threshold_label.set_halign(Gtk.Align.START)
        threshold_label.set_tooltip_text("Lower values = more sensitive to quiet sounds (0.001-0.1)")
        threshold_box.pack_start(threshold_label, False, False, 0)
        
        self.threshold_entry = Gtk.Entry()
        self.threshold_entry.set_text("0.002")
        self.threshold_entry.set_max_width_chars(10)
        self.threshold_entry.set_placeholder_text("0.002")
        threshold_box.pack_start(self.threshold_entry, False, False, 0)
        
        # Add helper text
        threshold_help = Gtk.Label(label="(streaming mode only)")
        threshold_help.set_halign(Gtk.Align.START)
        threshold_help.get_style_context().add_class("dim-label")
        threshold_box.pack_start(threshold_help, False, False, 0)
        
        settings_box.pack_start(threshold_box, False, False, 0)
        
        # Recording control buttons
        control_frame = Gtk.Frame(label="Recording Control")
        control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        control_box.set_margin_left(10)
        control_box.set_margin_right(10)
        control_box.set_margin_top(10)
        control_box.set_margin_bottom(10)
        control_frame.add(control_box)
        main_box.pack_start(control_frame, False, False, 0)
        
        self.start_recording_button = Gtk.Button(label="Start Recording")
        self.start_recording_button.connect("clicked", self.on_start_recording_clicked)
        control_box.pack_start(self.start_recording_button, False, False, 0)
        
        self.stop_recording_button = Gtk.Button(label="Stop Recording")
        self.stop_recording_button.connect("clicked", self.on_stop_recording_clicked)
        self.stop_recording_button.set_sensitive(False)
        control_box.pack_start(self.stop_recording_button, False, False, 0)
        
        # Status
        self.recording_status_label = Gtk.Label(label="Recording Status: Stopped")
        self.recording_status_label.set_halign(Gtk.Align.START)
        control_box.pack_start(self.recording_status_label, True, True, 0)
        
        # Transcription output
        transcription_frame = Gtk.Frame(label="Live Transcription")
        transcription_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        transcription_box.set_margin_left(10)
        transcription_box.set_margin_right(10)
        transcription_box.set_margin_top(10)
        transcription_box.set_margin_bottom(10)
        transcription_frame.add(transcription_box)
        main_box.pack_start(transcription_frame, True, True, 0)
        
        # Transcription text view with scrolling
        transcription_scrolled = Gtk.ScrolledWindow()
        transcription_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        transcription_scrolled.set_min_content_height(150)
        
        self.transcription_textview = Gtk.TextView()
        self.transcription_textview.set_editable(False)
        self.transcription_textview.set_cursor_visible(False)
        self.transcription_textview.set_wrap_mode(Gtk.WrapMode.WORD)
        self.transcription_buffer = self.transcription_textview.get_buffer()
        transcription_scrolled.add(self.transcription_textview)
        transcription_box.pack_start(transcription_scrolled, True, True, 0)
        
        # Clear transcription button
        clear_transcription_button = Gtk.Button(label="Clear Transcription")
        clear_transcription_button.connect("clicked", self.on_clear_transcription_clicked)
        transcription_box.pack_start(clear_transcription_button, False, False, 0)
        
        # Log output
        log_frame = Gtk.Frame(label="Log Output")
        log_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        log_box.set_margin_left(10)
        log_box.set_margin_right(10)
        log_box.set_margin_top(10)
        log_box.set_margin_bottom(10)
        log_frame.add(log_box)
        main_box.pack_start(log_frame, True, True, 0)
        
        # Log text view with scrolling
        log_scrolled = Gtk.ScrolledWindow()
        log_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        log_scrolled.set_min_content_height(100)
        
        self.log_textview = Gtk.TextView()
        self.log_textview.set_editable(False)
        self.log_textview.set_cursor_visible(False)
        self.log_buffer = self.log_textview.get_buffer()
        log_scrolled.add(self.log_textview)
        log_box.pack_start(log_scrolled, True, True, 0)
        
        # Clear log button
        clear_log_button = Gtk.Button(label="Clear Log")
        clear_log_button.connect("clicked", self.on_clear_log_clicked)
        log_box.pack_start(clear_log_button, False, False, 0)
        
        # Show all widgets
        self.window.show_all()
        
    def log_message(self, message):
        """Add a message to the log output."""
        def update_log():
            end_iter = self.log_buffer.get_end_iter()
            self.log_buffer.insert(end_iter, f"{message}\n")
            
            # Auto-scroll to bottom
            mark = self.log_buffer.get_insert()
            self.log_textview.scroll_mark_onscreen(mark)
            
        GLib.idle_add(update_log)
        
    def add_transcription(self, text):
        """Add transcription text to the transcription output."""
        def update_transcription():
            end_iter = self.transcription_buffer.get_end_iter()
            self.transcription_buffer.insert(end_iter, f"{text} ")
            
            # Auto-scroll to bottom
            mark = self.transcription_buffer.get_insert()
            self.transcription_textview.scroll_mark_onscreen(mark)
            
        GLib.idle_add(update_transcription)
        
    def on_clear_log_clicked(self, button):
        """Clear the log output."""
        self.log_buffer.set_text("")
        
    def on_clear_transcription_clicked(self, button):
        """Clear the transcription output."""
        self.transcription_buffer.set_text("")
        
    def start_daemon_status_monitoring(self):
        """Start monitoring daemon status."""
        self.daemon_status_running = True
        self.daemon_status_thread = threading.Thread(target=self._daemon_status_worker, daemon=True)
        self.daemon_status_thread.start()
        
    def stop_daemon_status_monitoring(self):
        """Stop monitoring daemon status."""
        self.daemon_status_running = False
        if self.daemon_status_thread:
            self.daemon_status_thread.join(timeout=1)
            
    def _daemon_status_worker(self):
        """Worker thread for monitoring daemon status."""
        while self.daemon_status_running:
            try:
                status = self.daemon_manager.get_daemon_status()
                
                def update_status():
                    if status.get("status") == "not_running":
                        self.daemon_status_value.set_text("Not Running")
                        self.start_daemon_button.set_sensitive(True)
                        self.stop_daemon_button.set_sensitive(False)
                        self.restart_daemon_button.set_sensitive(False)
                        self.start_recording_button.set_sensitive(False)
                        
                        # Stop recording if it was running
                        if self.is_recording:
                            self.is_recording = False
                            self.stop_recording_button.set_sensitive(False)
                            self.recording_status_label.set_text("Recording Status: Stopped (Daemon Down)")
                            
                    elif status.get("status") == "success":
                        model = status.get("model", "unknown")
                        recording = status.get("recording", False)
                        
                        self.daemon_status_value.set_text(f"Running (Model: {model})")
                        self.start_daemon_button.set_sensitive(False)
                        self.stop_daemon_button.set_sensitive(True)
                        self.restart_daemon_button.set_sensitive(True)
                        self.start_recording_button.set_sensitive(not recording)
                        
                        # Update recording status
                        if recording and not self.is_recording:
                            self.is_recording = True
                            self.stop_recording_button.set_sensitive(True)
                            self.recording_status_label.set_text("Recording Status: Recording")
                        elif not recording and self.is_recording:
                            self.is_recording = False
                            self.stop_recording_button.set_sensitive(False)
                            self.recording_status_label.set_text("Recording Status: Stopped")
                            
                    else:
                        self.daemon_status_value.set_text(f"Error: {status.get('message', 'Unknown')}")
                        self.start_daemon_button.set_sensitive(True)
                        self.stop_daemon_button.set_sensitive(False)
                        self.restart_daemon_button.set_sensitive(False)
                        self.start_recording_button.set_sensitive(False)
                        
                GLib.idle_add(update_status)
                
            except Exception as e:
                self.log_message(f"Error monitoring daemon status: {e}")
                
            time.sleep(1)  # Check every second
            
    def on_start_daemon_clicked(self, button):
        """Start the daemon."""
        model = self.model_combo.get_active_text()
        self.log_message(f"Starting daemon with model: {model}")
        
        def start_daemon():
            success = self.daemon_manager.start_daemon(model=model, debug=False)
            if success:
                self.log_message("Daemon started successfully")
            else:
                self.log_message("Failed to start daemon")
                
        threading.Thread(target=start_daemon, daemon=True).start()
        
    def on_stop_daemon_clicked(self, button):
        """Stop the daemon."""
        self.log_message("Stopping daemon...")
        
        def stop_daemon():
            success = self.daemon_manager.stop_daemon()
            if success:
                self.log_message("Daemon stopped successfully")
            else:
                self.log_message("Failed to stop daemon")
                
        threading.Thread(target=stop_daemon, daemon=True).start()
        
    def on_restart_daemon_clicked(self, button):
        """Restart the daemon."""
        model = self.model_combo.get_active_text()
        self.log_message(f"Restarting daemon with model: {model}")
        
        def restart_daemon():
            success = self.daemon_manager.restart_daemon(model=model, debug=False)
            if success:
                self.log_message("Daemon restarted successfully")
            else:
                self.log_message("Failed to restart daemon")
                
        threading.Thread(target=restart_daemon, daemon=True).start()
        
    def on_start_recording_clicked(self, button):
        """Start recording."""
        if self.is_recording:
            return
            
        # Configure daemon with current settings
        model = self.model_combo.get_active_text()
        language = self.language_entry.get_text().strip() or None
        
        threshold_text = self.threshold_entry.get_text().strip()
        silence_threshold = 0.002
        if threshold_text:
            try:
                threshold_value = float(threshold_text)
                if 0.0001 <= threshold_value <= 1.0:
                    silence_threshold = threshold_value
                else:
                    self.log_message(f"Warning: Silence threshold {threshold_value} outside range, using default")
            except ValueError:
                self.log_message(f"Warning: Invalid silence threshold '{threshold_text}', using default")
        
        config = {
            "model": model,
            "language": language,
            "silence_threshold": silence_threshold,
            "debug": False
        }
        
        self.log_message(f"Starting recording with config: {config}")
        
        def start_recording():
            # Configure daemon
            if not self.daemon_manager.configure_daemon(**config):
                self.log_message("Failed to configure daemon")
                return
            
            # Create streaming client
            self.streaming_client = ScribeStreamingClient()
            
            if not self.streaming_client.connect():
                self.log_message("Failed to connect to daemon for streaming")
                return
                
            # Start streaming
            self.streaming_client.start_streaming(
                on_transcription=self.add_transcription,
                on_error=self.log_message
            )
            
            self.log_message("Recording started")
            
        threading.Thread(target=start_recording, daemon=True).start()
        
    def on_stop_recording_clicked(self, button):
        """Stop recording."""
        if not self.is_recording:
            return
            
        self.log_message("Stopping recording...")
        
        def stop_recording():
            if self.streaming_client:
                self.streaming_client.stop_streaming()
                self.streaming_client.disconnect()
                self.streaming_client = None
                
            self.log_message("Recording stopped")
            
        threading.Thread(target=stop_recording, daemon=True).start()
        
    def on_window_destroy(self, widget):
        """Handle window closing."""
        self.log_message("Shutting down...")
        
        # Stop status monitoring
        self.stop_daemon_status_monitoring()
        
        # Stop recording if active
        if self.is_recording and self.streaming_client:
            self.streaming_client.stop_streaming()
            self.streaming_client.disconnect()
            
        # Note: We don't automatically stop the daemon when GUI closes
        # This allows the daemon to continue running for other clients
        
        Gtk.main_quit()
        
    def run(self):
        """Start the GUI application."""
        Gtk.main()


def main():
    """Main entry point for the GUI application."""
    app = ScribeDaemonGUI()
    app.run()


if __name__ == "__main__":
    main()