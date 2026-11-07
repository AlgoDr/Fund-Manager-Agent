import os
import time
import numpy as np
import onnxruntime as ort
import sounddevice as sd

# Configuration
MODEL_PATH = "/Users/deepakrathore/Documents/Assingments/FUND_MANAGER_VOICE_AI/models/static/silero_vad.onnx"
SAMPLE_RATE = 16000     # Supports 8000 or 16000 Hz
CHUNK_SIZE = 512        # 512 samples for 16kHz
THRESHOLD = 0.5         # Probability threshold for speech

if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Model file not found at: {MODEL_PATH}")

print("Initializing Silero VAD v4 ONNX model...")
opts = ort.SessionOptions()
opts.inter_op_num_threads = 1
opts.intra_op_num_threads = 1
session = ort.InferenceSession(MODEL_PATH, sess_options=opts)

# Silero VAD v4 requires separate 'h' and 'c' states initialized to zeros
h = np.zeros((2, 1, 64), dtype=np.float32)
c = np.zeros((2, 1, 64), dtype=np.float32)
sr_tensor = np.array([SAMPLE_RATE], dtype=np.int64)

def check_speech(audio_chunk, h_state, c_state):
    """Passes an audio chunk to Silero VAD v4 using the correct h/c state dictionary."""
    audio_chunk = np.expand_dims(audio_chunk.astype(np.float32), axis=0)
    
    # Map explicit inputs to match the model schema requirements
    inputs = {
        'input': audio_chunk,
        'sr': sr_tensor,
        'h': h_state,
        'c': c_state
    }
    
    # VAD v4 outputs: raw probability float, new h state, new c state
    out, new_h, new_c = session.run(None, inputs)
    
    return out[0][0], new_h, new_c

print("\n--- VAD Test Started ---")
print("The script will record for 10 seconds, then report if human speech was detected.")
print("Speak into your microphone now...")

try:
    while True:
        print("\n[Recording started for 10 seconds...]")
        duration = 10.0  
        audio_data = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32')
        sd.wait()  
        
        print("[Recording finished. Analyzing...] ")
        audio_flat = audio_data.flatten()
        
        # Reset recurrent state tracking arrays for the fresh window
        h = np.zeros((2, 1, 64), dtype=np.float32)
        c = np.zeros((2, 1, 64), dtype=np.float32)
        
        speech_detected_in_loop = False
        max_prob = 0.0
        
        for i in range(0, len(audio_flat), CHUNK_SIZE):
            chunk = audio_flat[i:i + CHUNK_SIZE]
            if len(chunk) < CHUNK_SIZE:
                chunk = np.pad(chunk, (0, CHUNK_SIZE - len(chunk)), 'constant')
                
            prob, h, c = check_speech(chunk, h, c)
            
            if prob > max_prob:
                max_prob = prob
            if prob > THRESHOLD:
                speech_detected_in_loop = True

        print(f"-> Max Speech Probability Found: {max_prob:.4f}")
        if speech_detected_in_loop:
            print("-> RESULT: 🎙️ HUMAN SPEECH DETECTED!")
        else:
            print("-> RESULT: 🤫 SILENCE / NO HUMAN SPEECH DETECTED.")
            
        print("\nStarting next 10-second window in 2 seconds... (Press Ctrl+C to stop)")
        time.sleep(2)

except KeyboardInterrupt:
    print("\nTest stopped by user.")
