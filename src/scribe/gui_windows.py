#!/usr/bin/env python3
"""Windows-native GUI application for managing Scribe speech-to-text transcription using tkinter."""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import threading
import os
import platform
import time
import signal
import sys


class ScribeWindowsGUI:
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
        self.window = tk.Tk()
        self.window.title("Scribe - Speech-to-Text GUI (Windows)")
        self.window.geometry("700x600")
        self.window.protocol("WM_DELETE_WINDOW", self.on_window_destroy)
        
        # Configure style
        style = ttk.Style()
        style.theme_use('vista')  # Use Windows Vista theme
        
        # Create main container with padding
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        
        # Settings frame
        settings_frame = ttk.LabelFrame(main_frame, text="Settings", padding="10")
        settings_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        settings_frame.columnconfigure(1, weight=1)
        
        # Model selection
        ttk.Label(settings_frame, text="Whisper Model:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.model_var = tk.StringVar(value="base")
        self.model_combo = ttk.Combobox(settings_frame, textvariable=self.model_var, 
                                       values=["tiny", "base", "small", "medium", "large", "turbo"],
                                       state="readonly", width=15)
        self.model_combo.grid(row=0, column=1, sticky=tk.W, pady=(0, 5))
        
        # Language selection
        ttk.Label(settings_frame, text="Language (optional):").grid(row=1, column=0, sticky=tk.W, padx=(0, 10))
        self.language_var = tk.StringVar()
        self.language_entry = ttk.Entry(settings_frame, textvariable=self.language_var, width=20)
        self.language_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=(0, 5))
        
        # Output command
        ttk.Label(settings_frame, text="Output Command:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10))
        self.output_var = tk.StringVar(value="")
        self.output_entry = ttk.Entry(settings_frame, textvariable=self.output_var)
        self.output_entry.grid(row=2, column=1, sticky=(tk.W, tk.E), pady=(0, 5))
        
        # Silence threshold
        ttk.Label(settings_frame, text="Silence Threshold:").grid(row=3, column=0, sticky=tk.W, padx=(0, 10))
        self.threshold_var = tk.StringVar(value="0.01")
        self.threshold_entry = ttk.Entry(settings_frame, textvariable=self.threshold_var, width=10)
        self.threshold_entry.grid(row=3, column=1, sticky=tk.W, pady=(0, 5))
        
        # Mode selection
        mode_frame = ttk.Frame(settings_frame)
        mode_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(5, 0))
        
        self.mode_var = tk.StringVar(value="streaming")
        self.streaming_radio = ttk.Radiobutton(mode_frame, text="Streaming (VAD)", 
                                              variable=self.mode_var, value="streaming")
        self.streaming_radio.grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        self.batch_radio = ttk.Radiobutton(mode_frame, text="Batch", 
                                          variable=self.mode_var, value="batch")
        self.batch_radio.grid(row=0, column=1, sticky=tk.W)
        
        # Debug and verbose options
        options_frame = ttk.Frame(settings_frame)
        options_frame.grid(row=5, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(5, 0))
        
        self.debug_var = tk.BooleanVar()
        self.debug_check = ttk.Checkbutton(options_frame, text="Debug output", variable=self.debug_var)
        self.debug_check.grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        
        self.verbose_var = tk.BooleanVar()
        self.verbose_check = ttk.Checkbutton(options_frame, text="Verbose output", variable=self.verbose_var)
        self.verbose_check.grid(row=0, column=1, sticky=tk.W)
        
        # Control buttons
        control_frame = ttk.Frame(main_frame)
        control_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        control_frame.columnconfigure(0, weight=1)
        control_frame.columnconfigure(1, weight=1)
        
        self.start_button = ttk.Button(control_frame, text="Start Recording", 
                                      command=self.start_recording, style="Accent.TButton")
        self.start_button.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5))
        
        self.stop_button = ttk.Button(control_frame, text="Stop Recording", 
                                     command=self.stop_recording, state=tk.DISABLED)
        self.stop_button.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0))
        
        # Status frame
        status_frame = ttk.LabelFrame(main_frame, text="Status", padding="10")
        status_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        status_frame.columnconfigure(0, weight=1)
        
        self.status_var = tk.StringVar(value="Ready to record")
        self.status_label = ttk.Label(status_frame, textvariable=self.status_var)
        self.status_label.grid(row=0, column=0, sticky=(tk.W, tk.E))
        
        # Output text area
        output_frame = ttk.LabelFrame(main_frame, text="Transcription Output", padding="10")
        output_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        self.output_text = scrolledtext.ScrolledText(output_frame, wrap=tk.WORD, height=15)
        self.output_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Clear button for output
        clear_button = ttk.Button(output_frame, text="Clear Output", command=self.clear_output)
        clear_button.grid(row=1, column=0, sticky=tk.E, pady=(5, 0))
        
        # Set initial focus
        self.model_combo.focus()
        
    def start_recording(self):
        """Start the recording process."""
        if self.is_running:
            return
            
        try:
            # Build scribe command
            cmd = ["uv", "run", "scribe"]
            
            # Add model
            cmd.extend(["--model", self.model_var.get()])
            
            # Add language if specified
            if self.language_var.get().strip():
                cmd.extend(["--language", self.language_var.get().strip()])
            
            # Add mode
            if self.mode_var.get() == "batch":
                cmd.append("--batch")
            
            # Add silence threshold
            cmd.extend(["--silence-threshold", self.threshold_var.get()])
            
            # Add debug and verbose flags
            if self.debug_var.get():
                cmd.append("--debug")
            if self.verbose_var.get():
                cmd.append("--verbose")
            
            self.log_message(f"Starting scribe with command: {' '.join(cmd)}")
            
            # Start scribe process
            self.scribe_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Start output process if command is specified
            output_cmd = self.output_var.get().strip()
            if output_cmd:
                self.log_message(f"Starting output command: {output_cmd}")
                self.output_process = subprocess.Popen(
                    output_cmd,
                    stdin=subprocess.PIPE,
                    shell=True,
                    text=True
                )
            
            # Update UI state
            self.is_running = True
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
            self.status_var.set("Recording... Press Stop to end")
            
            # Start monitoring thread
            self.monitor_thread = threading.Thread(target=self.monitor_processes, daemon=True)
            self.monitor_thread.start()
            
        except Exception as e:
            self.log_message(f"Error starting recording: {e}")
            messagebox.showerror("Error", f"Failed to start recording: {e}")
    
    def stop_recording(self):
        """Stop the recording process."""
        if not self.is_running:
            return
            
        try:
            self.log_message("Stopping recording...")
            
            # Terminate scribe process
            if self.scribe_process and self.scribe_process.poll() is None:
                if platform.system() == "Windows":
                    self.scribe_process.terminate()
                else:
                    self.scribe_process.send_signal(signal.SIGINT)
                
                # Wait for process to finish
                try:
                    self.scribe_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.scribe_process.kill()
                    self.scribe_process.wait()
            
            # Terminate output process
            if self.output_process and self.output_process.poll() is None:
                self.output_process.terminate()
                try:
                    self.output_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.output_process.kill()
                    self.output_process.wait()
            
            # Update UI state
            self.is_running = False
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.status_var.set("Recording stopped")
            
            self.log_message("Recording stopped successfully")
            
        except Exception as e:
            self.log_message(f"Error stopping recording: {e}")
            messagebox.showerror("Error", f"Failed to stop recording: {e}")
    
    def monitor_processes(self):
        """Monitor the scribe and output processes."""
        self.scribe_process_logged = False
        self.output_process_logged = False
        
        while self.is_running:
            try:
                # Check scribe process
                if self.scribe_process:
                    # Read stdout (transcription output)
                    if self.scribe_process.stdout and not self.scribe_process.stdout.closed:
                        try:
                            line = self.scribe_process.stdout.readline()
                            if line:
                                line = line.strip()
                                if line:
                                    # Display transcription in output area
                                    self.window.after(0, self.display_transcription, line)
                                    
                                    # Send to output command if available
                                    if self.output_process and self.output_process.stdin:
                                        try:
                                            self.output_process.stdin.write(line + "\n")
                                            self.output_process.stdin.flush()
                                        except:
                                            pass
                        except:
                            pass
                    
                    # Check if process has ended
                    if self.scribe_process.poll() is not None:
                        if not self.scribe_process_logged:
                            stderr = self.scribe_process.stderr.read() if self.scribe_process.stderr else ""
                            if stderr:
                                self.window.after(0, self.log_message, f"Scribe process ended with error: {stderr}")
                            else:
                                self.window.after(0, self.log_message, "Scribe process ended normally")
                            self.scribe_process_logged = True
                        
                        if self.is_running:
                            self.window.after(0, self.stop_recording)
                        break
                
                time.sleep(0.1)
                
            except Exception as e:
                self.window.after(0, self.log_message, f"Error in monitor thread: {e}")
                break
    
    def display_transcription(self, text):
        """Display transcription text in the output area."""
        self.output_text.insert(tk.END, text + " ")
        self.output_text.see(tk.END)
        self.output_text.update()
    
    def log_message(self, message):
        """Log a message to the status area."""
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {message}\n"
        self.output_text.insert(tk.END, log_line)
        self.output_text.see(tk.END)
        self.output_text.update()
    
    def clear_output(self):
        """Clear the output text area."""
        self.output_text.delete(1.0, tk.END)
    
    def on_window_destroy(self):
        """Handle window close event."""
        if self.is_running:
            self.stop_recording()
        self.window.destroy()
    
    def run(self):
        """Start the GUI main loop."""
        self.window.mainloop()


def main():
    """Main entry point for Windows GUI."""
    try:
        app = ScribeWindowsGUI()
        app.run()
    except Exception as e:
        print(f"Error starting Windows GUI: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()