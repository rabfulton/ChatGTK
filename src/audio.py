"""
DEPRECATED: Use services.AudioService instead.

This module is kept for backward compatibility only.
"""

import warnings
import sounddevice as sd
import numpy as np
import os


def record_audio(microphone, recording_flag):
    """Record audio from microphone.
    
    DEPRECATED: Use AudioService.record_audio() instead.
    
    Args:
        microphone: Name or index of input device
        recording_flag: Boolean flag to control recording state
        
    Returns:
        tuple: (recording_data, sample_rate) or (None, None) on error
    """
    warnings.warn(
        "audio.record_audio is deprecated. Use AudioService.record_audio() instead.",
        DeprecationWarning,
        stacklevel=2
    )
    
    try:
        recorded_chunks = []
        os.environ['AUDIODEV'] = 'pulse'
        
        device_info = sd.query_devices(microphone, 'input')
        if device_info is None:
            print(f"Warning: Could not find microphone '{microphone}', using default")
            device_info = sd.query_devices(sd.default.device[0], 'input')
        
        supported_sample_rate = int(device_info['default_samplerate'])
        
        def audio_callback(indata, frames, time, status):
            if status:
                print(f'Status: {status}')
            recorded_chunks.append(indata.copy())
        
        stream = sd.InputStream(
            device=microphone,
            channels=1,
            samplerate=supported_sample_rate,
            callback=audio_callback,
            dtype=np.float32
        )
        
        with stream:
            print(f"Recording started at {supported_sample_rate} Hz")
            while recording_flag.is_set():
                sd.sleep(100)
        
        if recorded_chunks:
            recording = np.concatenate(recorded_chunks, axis=0)
            return recording, supported_sample_rate
        
        return None, None
            
    except Exception as e:
        print(f"Error recording audio: {e}")
        return None, None
