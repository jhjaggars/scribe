#!/usr/bin/env python3
"""
Test script for Windows audio functionality
Run this on Windows to verify sounddevice and WindowsAudioRecorder work correctly.
"""

import sys
import platform
import time

def test_sounddevice_import():
    """Test if sounddevice can be imported."""
    print("Testing sounddevice import...")
    try:
        import sounddevice as sd
        print(f"✓ sounddevice imported successfully (version: {sd.__version__})")
        return True
    except ImportError as e:
        print(f"✗ Failed to import sounddevice: {e}")
        print("  Install with: pip install sounddevice")
        return False

def test_audio_devices():
    """Test audio device detection."""
    print("\nTesting audio device detection...")
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        print(f"✓ Found {len(devices)} audio devices:")
        
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                print(f"  [{i}] {device['name']} - {device['max_input_channels']} input channels")
        
        # Get default input device
        default_device = sd.query_devices(kind='input')
        print(f"\nDefault input device: {default_device['name']}")
        return True
        
    except Exception as e:
        print(f"✗ Audio device detection failed: {e}")
        return False

def test_audio_recording():
    """Test basic audio recording."""
    print("\nTesting basic audio recording...")
    try:
        import sounddevice as sd
        import numpy as np
        
        duration = 2  # seconds
        sample_rate = 16000
        
        print(f"Recording {duration} seconds of audio at {sample_rate}Hz...")
        audio_data = sd.rec(
            frames=duration * sample_rate,
            samplerate=sample_rate,
            channels=1,
            dtype=np.float32
        )
        sd.wait()  # Wait for recording to complete
        
        # Check if we got audio data
        max_amplitude = np.max(np.abs(audio_data))
        print(f"✓ Recording completed. Max amplitude: {max_amplitude:.4f}")
        
        if max_amplitude > 0.001:
            print("✓ Audio data contains signal (speak into microphone during test)")
        else:
            print("⚠ Audio data is very quiet (microphone might be muted or not working)")
        
        return True
        
    except Exception as e:
        print(f"✗ Audio recording test failed: {e}")
        return False

def test_windows_audio_recorder():
    """Test the WindowsAudioRecorder class."""
    print("\nTesting WindowsAudioRecorder class...")
    
    # Add src path to import scribe modules
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
    
    try:
        from scribe.main import WindowsAudioRecorder, SOUNDDEVICE_AVAILABLE
        
        if not SOUNDDEVICE_AVAILABLE:
            print("✗ sounddevice not available for WindowsAudioRecorder")
            return False
        
        print("✓ WindowsAudioRecorder imported successfully")
        
        # Test initialization
        recorder = WindowsAudioRecorder(
            sample_rate=16000,
            channels=1,
            chunk_duration=2.0,
            debug=True,
            vad_mode=False  # Use fixed chunks for testing
        )
        print("✓ WindowsAudioRecorder initialized")
        
        # Test stream start/stop
        print("Starting audio stream for 3 seconds...")
        recorder.start_streaming()
        time.sleep(3)
        recorder.stop_streaming()
        print("✓ Audio streaming test completed")
        
        # Clean up
        recorder.cleanup()
        print("✓ WindowsAudioRecorder cleanup completed")
        
        return True
        
    except Exception as e:
        print(f"✗ WindowsAudioRecorder test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("Windows Audio Functionality Test")
    print("=" * 40)
    print(f"Platform: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}")
    print()
    
    tests = [
        test_sounddevice_import,
        test_audio_devices, 
        test_audio_recording,
        test_windows_audio_recorder
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except KeyboardInterrupt:
            print("\n\nTest interrupted by user")
            break
        except Exception as e:
            print(f"✗ Test failed with unexpected error: {e}")
    
    print(f"\nTest Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Windows audio functionality is working correctly.")
    else:
        print("⚠ Some tests failed. Check the output above for details.")
        
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)