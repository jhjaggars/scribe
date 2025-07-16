#!/usr/bin/env python3
"""GUI application for managing Scribe speech-to-text transcription."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject, GLib
import subprocess
import threading
import os
import signal
import time


class ScribeGUI:
    def __init__(self):
        # Process management
        self.scribe_process = None
        self.output_process = None
        self.is_running = False
        self.monitor_thread = None
        
        # Process logging flags to prevent repetitive messages
        self.scribe_process_logged = False
        self.output_process_logged = False
        
        # Build the GUI
        self.build_ui()
        
    def build_ui(self):
        # Create main window
        self.window = Gtk.Window(title="Scribe - Speech-to-Text GUI")
        self.window.set_default_size(600, 500)
        self.window.connect("destroy", self.on_window_destroy)
        
        # Create main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        main_box.set_margin_left(10)
        main_box.set_margin_right(10)
        main_box.set_margin_top(10)
        main_box.set_margin_bottom(10)
        self.window.add(main_box)
        
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
        
        # Output command
        output_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        output_label = Gtk.Label(label="Output Command:")
        output_label.set_size_request(120, -1)
        output_label.set_halign(Gtk.Align.START)
        output_box.pack_start(output_label, False, False, 0)
        
        self.output_entry = Gtk.Entry()
        self.output_entry.set_text("xvkbd -file -")
        output_box.pack_start(self.output_entry, True, True, 0)
        settings_box.pack_start(output_box, False, False, 0)
        
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
        
        # Mode selection
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        mode_label = Gtk.Label(label="Mode:")
        mode_label.set_size_request(120, -1)
        mode_label.set_halign(Gtk.Align.START)
        mode_box.pack_start(mode_label, False, False, 0)
        
        self.streaming_radio = Gtk.RadioButton(label="Streaming (VAD)")
        self.batch_radio = Gtk.RadioButton(label="Batch", group=self.streaming_radio)
        mode_box.pack_start(self.streaming_radio, False, False, 0)
        mode_box.pack_start(self.batch_radio, False, False, 0)
        settings_box.pack_start(mode_box, False, False, 0)
        
        # Control buttons
        control_frame = Gtk.Frame(label="Control")
        control_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        control_box.set_margin_left(10)
        control_box.set_margin_right(10)
        control_box.set_margin_top(10)
        control_box.set_margin_bottom(10)
        control_frame.add(control_box)
        main_box.pack_start(control_frame, False, False, 0)
        
        self.start_button = Gtk.Button(label="Start")
        self.start_button.connect("clicked", self.on_start_clicked)
        control_box.pack_start(self.start_button, False, False, 0)
        
        self.stop_button = Gtk.Button(label="Stop")
        self.stop_button.connect("clicked", self.on_stop_clicked)
        self.stop_button.set_sensitive(False)
        control_box.pack_start(self.stop_button, False, False, 0)
        
        # Status
        self.status_label = Gtk.Label(label="Status: Stopped")
        self.status_label.set_halign(Gtk.Align.START)
        control_box.pack_start(self.status_label, True, True, 0)
        
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
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_min_content_height(200)
        
        self.log_textview = Gtk.TextView()
        self.log_textview.set_editable(False)
        self.log_textview.set_cursor_visible(False)
        self.log_buffer = self.log_textview.get_buffer()
        scrolled_window.add(self.log_textview)
        log_box.pack_start(scrolled_window, True, True, 0)
        
        # Clear log button
        clear_button = Gtk.Button(label="Clear Log")
        clear_button.connect("clicked", self.on_clear_log_clicked)
        log_box.pack_start(clear_button, False, False, 0)
        
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
        
    def on_clear_log_clicked(self, button):
        """Clear the log output."""
        self.log_buffer.set_text("")
        
    def on_start_clicked(self, button):
        """Start the Scribe process."""
        if self.is_running:
            return
            
        # Build command
        scribe_cmd = ["uv", "run", "scribe"]
        
        # Add model
        model = self.model_combo.get_active_text()
        scribe_cmd.extend(["--model", model])
        
        # Add language if specified
        language = self.language_entry.get_text().strip()
        if language:
            scribe_cmd.extend(["--language", language])
            
        # Add mode
        if self.batch_radio.get_active():
            scribe_cmd.append("--batch")
        else:
            # Add silence threshold for streaming mode only
            threshold_text = self.threshold_entry.get_text().strip()
            if threshold_text:
                try:
                    threshold_value = float(threshold_text)
                    if 0.0001 <= threshold_value <= 1.0:
                        scribe_cmd.extend(["--silence-threshold", str(threshold_value)])
                    else:
                        self.log_message(f"Warning: Silence threshold {threshold_value} outside recommended range (0.0001-1.0), using default")
                except ValueError:
                    self.log_message(f"Warning: Invalid silence threshold '{threshold_text}', using default")
            
        # Add verbose output
        scribe_cmd.append("--verbose")
        
        # Get output command
        output_cmd = self.output_entry.get_text().strip()
        
        self.log_message(f"Starting Scribe with command: {' '.join(scribe_cmd)}")
        if output_cmd:
            self.log_message(f"Output will be piped to: {output_cmd}")
        
        try:
            # Reset process logging flags
            self.scribe_process_logged = False
            self.output_process_logged = False
            
            # Start the process chain
            self.scribe_process = subprocess.Popen(
                scribe_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Start output process if specified
            if output_cmd:
                self.output_process = subprocess.Popen(
                    output_cmd,
                    shell=True,
                    stdin=self.scribe_process.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                # Allow scribe_process to receive a SIGPIPE if output_process exits
                self.scribe_process.stdout.close()
            
            self.is_running = True
            self.start_button.set_sensitive(False)
            self.stop_button.set_sensitive(True)
            self.status_label.set_text("Status: Running")
            
            # Start monitoring thread
            self.monitor_thread = threading.Thread(target=self.monitor_processes, daemon=True)
            self.monitor_thread.start()
            
        except Exception as e:
            self.log_message(f"Error starting Scribe: {e}")
            self.show_error_dialog("Error", f"Failed to start Scribe: {e}")
            
    def on_stop_clicked(self, button):
        """Stop the Scribe process."""
        if not self.is_running:
            return
            
        self.log_message("Stopping Scribe...")
        
        # Update UI immediately to show stopping state
        self.stop_button.set_sensitive(False)
        self.status_label.set_text("Status: Stopping...")
        
        # Start asynchronous stop process
        stop_thread = threading.Thread(target=self._stop_processes_async, daemon=True)
        stop_thread.start()
        
    def _stop_processes_async(self):
        """Asynchronously stop processes without blocking the UI."""
        try:
            # Send SIGINT to scribe process (equivalent to Ctrl+C)
            if self.scribe_process and self.scribe_process.poll() is None:
                self.scribe_process.send_signal(signal.SIGINT)
                self.log_message("Sent stop signal to Scribe process...")
                
            # Terminate output process
            if self.output_process and self.output_process.poll() is None:
                self.output_process.terminate()
                self.log_message("Terminating output process...")
                
            # Wait for scribe process to finish with progressive escalation
            if self.scribe_process:
                try:
                    self.scribe_process.wait(timeout=3)
                    self.log_message("Scribe process stopped gracefully")
                except subprocess.TimeoutExpired:
                    self.log_message("Scribe process didn't stop gracefully, sending SIGTERM...")
                    self.scribe_process.terminate()
                    try:
                        self.scribe_process.wait(timeout=2)
                        self.log_message("Scribe process terminated")
                    except subprocess.TimeoutExpired:
                        self.log_message("Force killing Scribe process...")
                        self.scribe_process.kill()
                        self.scribe_process.wait()
                        
            # Wait for output process to finish
            if self.output_process:
                try:
                    self.output_process.wait(timeout=1)
                    self.log_message("Output process stopped")
                except subprocess.TimeoutExpired:
                    self.log_message("Force killing output process...")
                    self.output_process.kill()
                    self.output_process.wait()
                    
            # Wait for monitor thread to finish
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=1)
                if self.monitor_thread.is_alive():
                    self.log_message("Monitor thread still running (will be cleaned up)")
                    
        except Exception as e:
            self.log_message(f"Error stopping processes: {e}")
            
        # Clean up and update UI
        GLib.idle_add(self.cleanup_processes)
        
    def cleanup_processes(self):
        """Clean up process state."""
        def update_ui():
            self.is_running = False
            self.scribe_process = None
            self.output_process = None
            self.start_button.set_sensitive(True)
            self.stop_button.set_sensitive(False)
            self.status_label.set_text("Status: Stopped")
            
        GLib.idle_add(update_ui)
        
    def monitor_processes(self):
        """Monitor the running processes."""
        while self.is_running:
            # Monitor scribe process
            if self.scribe_process and not self.scribe_process_logged:
                try:
                    if self.scribe_process.poll() is not None:
                        # Process has terminated
                        return_code = self.scribe_process.returncode
                        if return_code != 0:
                            # Read stderr for error messages
                            stderr_output = self.scribe_process.stderr.read()
                            if stderr_output:
                                self.log_message(f"Scribe error: {stderr_output}")
                        
                        self.log_message(f"Scribe process ended with return code: {return_code}")
                        self.scribe_process_logged = True
                        self.scribe_process = None
                        break
                        
                    # Read stderr from scribe process for log messages
                    if self.scribe_process.stderr:
                        try:
                            # Non-blocking read
                            import select
                            if select.select([self.scribe_process.stderr], [], [], 0.1)[0]:
                                line = self.scribe_process.stderr.readline()
                                if line:
                                    self.log_message(f"Scribe: {line.strip()}")
                        except Exception as e:
                            self.log_message(f"Error reading scribe stderr: {e}")
                            
                except Exception as e:
                    self.log_message(f"Error monitoring scribe process: {e}")
                    self.scribe_process_logged = True
                    self.scribe_process = None
                    break
                    
            # Monitor output process
            if self.output_process and not self.output_process_logged:
                try:
                    if self.output_process.poll() is not None:
                        return_code = self.output_process.returncode
                        if return_code != 0:
                            stderr_output = self.output_process.stderr.read()
                            if stderr_output:
                                self.log_message(f"Output command error: {stderr_output}")
                        
                        self.log_message(f"Output process ended with return code: {return_code}")
                        self.output_process_logged = True
                        self.output_process = None
                        
                except Exception as e:
                    self.log_message(f"Error monitoring output process: {e}")
                    self.output_process_logged = True
                    self.output_process = None
                
            time.sleep(0.1)  # Sleep for 100ms
            
        # Process ended, cleanup
        self.cleanup_processes()
        
    def show_error_dialog(self, title, message):
        """Show an error dialog."""
        def show_dialog():
            dialog = Gtk.MessageDialog(
                transient_for=self.window,
                flags=0,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text=title
            )
            dialog.format_secondary_text(message)
            dialog.run()
            dialog.destroy()
            
        GLib.idle_add(show_dialog)
        
    def on_window_destroy(self, widget):
        """Handle window closing."""
        if self.is_running:
            self.on_stop_clicked(None)
        Gtk.main_quit()
        
    def run(self):
        """Start the GUI application."""
        Gtk.main()


def main():
    """Main entry point for the GUI application."""
    app = ScribeGUI()
    app.run()


if __name__ == "__main__":
    main()