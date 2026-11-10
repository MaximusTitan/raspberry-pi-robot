import json
import pyaudio
from vosk import Model, KaldiRecognizer

MODEL_PATH = "model"
SAMPLE_RATE = 16000
CHUNK = 4000

def main():
    print("Loading model...")
    model = Model(MODEL_PATH)
    recognizer = KaldiRecognizer(model, SAMPLE_RATE)

    p = pyaudio.PyAudio()

    print("Opening microphone...")
    stream = p.open(format=pyaudio.paInt16,
                    channels=1,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=CHUNK)

    stream.start_stream()
    print("Listening... (Ctrl + C to stop)\n")

    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            if recognizer.AcceptWaveform(data):
                result = recognizer.Result()
                text = json.loads(result).get("text", "")
                if text:
                    print("You:", text)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    main()
