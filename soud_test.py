import sounddevice as sd
import numpy as np

def callback(indata, frames, time, status):
    print("Frames:", frames, "Max amplitude:", np.max(indata))

with sd.InputStream(samplerate=44100, channels=1, callback=callback):
    sd.sleep(5000)  # capture for 5 seconds
