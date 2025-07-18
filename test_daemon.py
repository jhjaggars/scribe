#!/usr/bin/env python3
"""Test script for daemon architecture."""

import time
import subprocess
import sys
import os

def test_daemon_lifecycle():
    """Test daemon startup, communication, and shutdown."""
    print("Testing daemon lifecycle...")
    
    # Test 1: Start daemon
    print("\n1. Starting daemon...")
    result = subprocess.run([
        sys.executable, "-m", "scribe.client", 
        "--model", "tiny", "--daemon-only", "--debug"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Failed to start daemon: {result.stderr}")
        return False
    
    print("Daemon started successfully")
    
    # Test 2: Check status
    print("\n2. Checking daemon status...")
    result = subprocess.run([
        sys.executable, "-m", "scribe.client", "--status"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Failed to get status: {result.stderr}")
        return False
    
    print(f"Status: {result.stdout.strip()}")
    
    # Test 3: Test a short recording session (2 seconds)
    print("\n3. Testing short recording session...")
    process = subprocess.Popen([
        sys.executable, "-m", "scribe.client", 
        "--model", "tiny", "--debug"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Let it run for 2 seconds
    time.sleep(2)
    
    # Stop the process
    process.terminate()
    stdout, stderr = process.communicate()
    
    print(f"Recording stderr: {stderr}")
    if stdout:
        print(f"Recording stdout: {stdout}")
    
    # Test 4: Shutdown daemon
    print("\n4. Shutting down daemon...")
    result = subprocess.run([
        sys.executable, "-m", "scribe.client", "--shutdown-daemon"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Failed to shutdown daemon: {result.stderr}")
        return False
    
    print("Daemon shutdown successfully")
    
    return True

def test_startup_performance():
    """Test startup performance comparison."""
    print("\nTesting startup performance...")
    
    # Start daemon first
    print("Starting daemon...")
    result = subprocess.run([
        sys.executable, "-m", "scribe.client", 
        "--model", "tiny", "--daemon-only"
    ], capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"Failed to start daemon: {result.stderr}")
        return False
    
    # Test multiple quick start/stop cycles
    print("Testing 3 quick start/stop cycles...")
    
    for i in range(3):
        print(f"Cycle {i+1}:")
        start_time = time.time()
        
        # Start recording
        process = subprocess.Popen([
            sys.executable, "-m", "scribe.client", 
            "--model", "tiny"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Wait briefly
        time.sleep(0.5)
        
        # Stop recording
        process.terminate()
        stdout, stderr = process.communicate()
        
        end_time = time.time()
        print(f"  Start/stop cycle took: {end_time - start_time:.4f}s")
    
    # Shutdown daemon
    subprocess.run([
        sys.executable, "-m", "scribe.client", "--shutdown-daemon"
    ], capture_output=True, text=True)
    
    return True

if __name__ == "__main__":
    print("Scribe Daemon Architecture Test")
    print("=" * 40)
    
    try:
        if test_daemon_lifecycle():
            print("\n✓ Daemon lifecycle test passed")
        else:
            print("\n✗ Daemon lifecycle test failed")
            sys.exit(1)
        
        if test_startup_performance():
            print("\n✓ Startup performance test passed")
        else:
            print("\n✗ Startup performance test failed")
            sys.exit(1)
            
        print("\n🎉 All tests passed!")
        
    except KeyboardInterrupt:
        print("\nTest interrupted")
        # Try to cleanup
        subprocess.run([
            sys.executable, "-m", "scribe.client", "--shutdown-daemon"
        ], capture_output=True, text=True)
    except Exception as e:
        print(f"\nTest error: {e}")
        sys.exit(1)