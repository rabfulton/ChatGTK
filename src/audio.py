import sounddevice as sd
import numpy as np
import os

def record_audio(microphone, recording_flag):
    """Record audio from microphone.
    
    Args:
        microphone: Name or index of input device
        recording_flag: Boolean flag to control recording state
        
    Returns:
        tuple: (recording_data, sample_rate) or (None, None) on error
    """
    try:
        recorded_chunks = []  # Store audio chunks here
        
        os.environ['AUDIODEV'] = 'pulse'  # Force use of PulseAudio
        
        # Get device info for the selected microphone
        device_info = sd.query_devices(microphone, 'input')
        if device_info is None:
            print(f"Warning: Could not find microphone '{microphone}', using default")
            device_info = sd.query_devices(sd.default.device[0], 'input')
        
        # Use the device's supported sample rate
        supported_sample_rate = int(device_info['default_samplerate'])
        
        # Callback to store audio chunks
        def audio_callback(indata, frames, time, status):
            if status:
                print(f'Status: {status}')
            recorded_chunks.append(indata.copy())
        
        # Create input stream
        stream = sd.InputStream(
            device=microphone,
            channels=1,
            samplerate=supported_sample_rate,
            callback=audio_callback,
            dtype=np.float32
        )
        
        # Start recording
        with stream:
            print(f"Recording started at {supported_sample_rate} Hz")
            while recording_flag.is_set():  # Use threading.Event instead of boolean
                sd.sleep(100)  # Sleep between checks
        
        # Concatenate all recorded chunks
        if recorded_chunks:
            recording = np.concatenate(recorded_chunks, axis=0)
            return recording, supported_sample_rate
        
        return None, None
            
    except Exception as e:
        print(f"Error recording audio: {e}")
        return None, None
