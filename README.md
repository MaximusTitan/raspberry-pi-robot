# Raspberry Pi Robot

Voice-controlled Raspberry Pi 5 robot: motors, ultrasonic sensors, camera,
hand-gesture control (OpenCV + MediaPipe), offline speech recognition (Vosk),
text-to-speech (Piper) and an Ollama-backed assistant ("Buddy").

## Files
| File | Purpose |
|---|---|
| `robot.py` | Main robot program |
| `run_robot.sh` | Launcher - runs `robot.py` with pyenv Python and passes audio env through sudo |
| `robot` | Older launcher (plain sudo - Bluetooth audio won't work through it) |
| `mic_test.py` | Standalone mic / Vosk STT tester with keyboard controls |
| `combined_voice_keyboard_control.py`, `run_combined_control.sh` | Older combined voice + keyboard controller |
| `motor_control/` | Motor, sensor and gamepad test scripts |

## Setup
- Python 3.12 via pyenv (`~/.pyenv/versions/3.12.12`) with:
  `opencv-python mediapipe vosk pyaudio piper-onnx pygame numpy requests`
- Vosk model at `~/rasp/motor_control/model` (e.g. `vosk-model-small-en-us-0.15`)
- Piper voice at `~/piper_voices/en_US-amy-medium.onnx` (+ `.onnx.json`)
- Ollama running locally

## Run
```
./run_robot.sh     # not with sudo - the script elevates itself
./mic_test.py      # test the microphone + speech recognition
```
Bluetooth headsets only send mic audio in HFP (headset) mode.
