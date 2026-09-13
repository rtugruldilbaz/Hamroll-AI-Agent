import tempfile
import threading

import numpy as np
import sounddevice as sd
from scipy.io.wavfile import write


SAMPLE_RATE = 16000

recording = False
audio_chunks = []
stream = None
lock = threading.Lock()


def _audio_callback(indata, frames, time, status):
    if status:
        print(f"[Voice] Audio status: {status}")

    with lock:
        if recording:
            audio_chunks.append(indata.copy())


def start_recording():
    global recording, stream, audio_chunks

    with lock:
        if recording:
            return False

        audio_chunks = []
        recording = True

    try:
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            callback=_audio_callback,
        )
        stream.start()
        return True

    except Exception:
        with lock:
            recording = False
            audio_chunks = []

        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

        stream = None
        raise


def stop_recording():
    global recording, stream, audio_chunks

    with lock:
        if not recording:
            return None

        recording = False
        current_stream = stream
        stream = None

    if current_stream is not None:
        try:
            current_stream.stop()
        finally:
            current_stream.close()

    with lock:
        chunks = audio_chunks
        audio_chunks = []

    if not chunks:
        return None

    audio = np.concatenate(
        chunks,
        axis=0,
    )

    temp_file = tempfile.NamedTemporaryFile(
        suffix=".wav",
        delete=False,
    )
    temp_file.close()

    write(
        temp_file.name,
        SAMPLE_RATE,
        audio,
    )

    return temp_file.name