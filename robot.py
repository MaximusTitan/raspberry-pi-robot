#!/home/admin/.pyenv/shims/python3
"""
COMBINED VOICE AI + KEYBOARD MOTOR CONTROL
Microphone → VOSK → OLLAMA → PIPER → AUDIO OUT → MOTOR MOVEMENT
+ Keyboard control with WASD keys
"""
import os
import json
import argparse
import subprocess
import shutil
import time
import pyaudio
import sys
import termios
import tty
import select
import threading
import re
import signal
import random
import collections
import lgpio
import pygame
from vosk import Model, KaldiRecognizer
from gpiozero import PWMOutputDevice, OutputDevice
from http.server import HTTPServer, BaseHTTPRequestHandler
import socketserver
import webbrowser
import base64


def _ensure_gesture_runtime():
    """Use the pyenv Python runtime whenever possible so MediaPipe works."""
    required_modules = ("cv2", "mediapipe")
    missing = []
    for module_name in required_modules:
        try:
            __import__(module_name)
        except ImportError as exc:
            missing.append((module_name, str(exc)))

    # Point at the real interpreter, not the pyenv shim: the shim is a bash
    # script, so its realpath never equals sys.executable and we'd re-exec forever.
    # Under sudo, expanduser("~") is /root, so use the invoking user's home.
    home = os.path.expanduser(f"~{os.environ.get('SUDO_USER', '')}")
    candidates = [
        os.path.join(home, ".pyenv/versions/3.12.12/bin/python3"),
    ]

    target_python = next((p for p in candidates if p and os.path.exists(p)), None)
    current_python = os.path.realpath(sys.executable)
    target_python_real = os.path.realpath(target_python) if target_python else None

    already_restarted = os.environ.get("ROBOT_REEXECED") == "1"
    if target_python_real and current_python != target_python_real and not already_restarted:
        os.environ["ROBOT_REEXECED"] = "1"
        reason = " (MediaPipe dependencies detected)" if missing else ""
        print(f"[INIT] Restarting with pyenv Python{reason}...")
        os.execv(target_python_real, [target_python_real, *sys.argv])

    if missing:
        if not target_python_real:
            print("[WARNING] OpenCV/MediaPipe missing and no pyenv Python was found.")
            print("          Run ./run_robot.sh or install the packages for this interpreter.")
            return

        if current_python == target_python_real:
            # Already using the preferred interpreter; nothing else we can do here.
            print("[WARNING] OpenCV/MediaPipe missing for this interpreter."
                  " Install them with: pip install opencv-python mediapipe")
            print("          Or run ./run_robot.sh to use the configured pyenv environment.")
            return


_ensure_gesture_runtime()

# OpenCV and MediaPipe for hand gesture control
try:
    import cv2
    import mediapipe as mp
    GESTURE_AVAILABLE = True
except ImportError:
    GESTURE_AVAILABLE = False
    print("[WARNING] OpenCV or MediaPipe not installed. Hand gesture control disabled.")
    print("         Install with: pip install opencv-python mediapipe")

# Camera functionality
CAMERA_AVAILABLE = True  # We'll use ffmpeg for capture

GAMEPAD_DEADZONE = 0.15
GAMEPAD_MAX_SPEED = 0.8
AXIS_LX = 0
AXIS_RT = 5
AXIS_LT = 2

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'

def clear_screen():
    """Clear the terminal screen"""
    os.system('clear')

def print_header(title):
    """Print a styled header"""
    width = 60
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*width}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*10} {title.center(width-22)} {'='*10}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*width}{Colors.END}")

def print_section(title):
    """Print a section header"""
    print(f"\n{Colors.BOLD}{Colors.YELLOW}{title}{Colors.END}")
    print(f"{Colors.YELLOW}{'-'*len(title)}{Colors.END}")

def print_comprehensive_help():
    """Display comprehensive help information"""
    clear_screen()
    print_header("ROBOT CONTROL HELP")
    print_section("MOVEMENT CONTROLS")
    print(f"{Colors.GREEN}WASD Keys:{Colors.END}")
    print("  W: Move Forward")
    print("  S: Move Backward")
    print("  A: Spin Left")
    print("  D: Spin Right")
    print("  Space: Emergency Stop")
    
    print_section("SPEED CONTROLS")
    print(f"{Colors.GREEN}Speed Adjustment:{Colors.END}")
    print("  +/=: Increase speed")
    print("  -: Decrease speed")
    print("  1-9: Set speed preset (1=slowest, 9=fastest)")
    
    print_section("VOICE COMMANDS")
    print(f"{Colors.GREEN}Movement Commands (many synonyms supported):{Colors.END}")
    print("  Forward: 'forward', 'go ahead', 'move forward', 'proceed', 'advance', 'straight'")
    print("  Backward: 'back', 'reverse', 'backward', 'retreat', 'back up', 'move back'")
    print("  Left: 'left', 'turn left', 'go left', 'spin left', 'rotate left', 'veer left'")
    print("  Right: 'right', 'turn right', 'go right', 'spin right', 'rotate right', 'veer right'")
    print("  Stop: 'stop', 'halt', 'freeze', 'cease', 'pause', 'hold'")
    
    print_section("GAMEPAD CONTROLS")
    print(f"{Colors.GREEN}Xbox Controller:{Colors.END}")
    print("  LT: Move Forward")
    print("  RT: Move Backward")
    print("  Left Stick: Steer/Spin")
    print("  LT+RT: Emergency Stop")
    
    print_section("VISION CONTROLS")
    print(f"{Colors.GREEN}Image Analysis:{Colors.END}")
    print("  'what do you see?', 'describe image', 'take a picture'")
    print("  'look around', 'analyze image', 'identify this'")

    print_section("HAND GESTURE CONTROLS")
    print(f"{Colors.GREEN}Gestures (requires camera):{Colors.END}")
    print("  ✋ Open Palm (5 fingers): Stop")
    print("  ☝️ Index finger up: Move Forward")
    print("  ✌️ Two fingers (peace): Move Backward")
    print("  👍 Thumb left: Spin Left")
    print("  👍 Thumb right: Spin Right")
    print("  ✊ Closed fist: Emergency Stop")
    print("  G: Toggle gesture control on/off")

    print_section("SYSTEM CONTROLS")
    print(f"{Colors.GREEN}System:{Colors.END}")
    print("  H: Show this help")
    print("  G: Toggle gesture control")
    print("  Q: Quit program")
    
    print(f"\n{Colors.RED}Press any key to return...{Colors.END}")
    getch_blocking()

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "gemma3:1b"  # Text responses (faster)
DEFAULT_VISION_MODEL = "gemma3:4b"  # Image analysis (more capable)
DEFAULT_PIPER_MODEL = "/home/admin/piper_voices/en_US-amy-medium.onnx"
DEFAULT_PIPER_CONFIG = "/home/admin/piper_voices/en_US-amy-medium.onnx.json"
DEFAULT_VOSK_MODEL = "/home/admin/rasp/motor_control/model"

STREAM_DEBUG = False
OUT_WAV = "voice_reply.wav"
SPEED = 0.4

def clean_text_for_tts(text):
    """Remove asterisks and emojis from text before TTS"""
    text = text.replace('*', '')
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002700-\U000027BF"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"
        "\u3030"
        "]+",
        flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)
    return text.strip()

# Motor control globals
ENA = None
IN1 = None
IN2 = None
ENB = None
IN3 = None
IN4 = None

# Ultrasonic sensor configuration
SENSOR1_TRIG = 20
SENSOR1_ECHO = 19
SENSOR2_TRIG = 5
SENSOR2_ECHO = 6
SPEED_OF_SOUND = 34300
TIMEOUT = 0.025
OBSTACLE_THRESHOLD = 30
ultrasonic_handle = None
ultrasonic_lock = threading.Lock()  # serialize sensor reads across threads

def init_motors():
    global ENA, IN1, IN2, ENB, IN3, IN4
    try:
        ENA = PWMOutputDevice(12)
        IN1 = OutputDevice(23)
        IN2 = OutputDevice(24)
        ENB = PWMOutputDevice(13)
        IN3 = OutputDevice(16)
        IN4 = OutputDevice(21)
        print(f"{Colors.GREEN}[MOTOR] Motors initialized successfully{Colors.END}")
    except Exception as e:
        print(f"{Colors.RED}[MOTOR] Failed to initialize motors: {e}{Colors.END}")
        print(f"{Colors.YELLOW}[MOTOR] Running in audio-only mode{Colors.END}")
        ENA = IN1 = IN2 = ENB = IN3 = IN4 = None

def init_ultrasonic():
    global ultrasonic_handle
    try:
        ultrasonic_handle = lgpio.gpiochip_open(4)
        lgpio.gpio_claim_output(ultrasonic_handle, SENSOR1_TRIG)
        lgpio.gpio_claim_output(ultrasonic_handle, SENSOR2_TRIG)
        lgpio.gpio_claim_input(ultrasonic_handle, SENSOR1_ECHO)
        lgpio.gpio_claim_input(ultrasonic_handle, SENSOR2_ECHO)
        lgpio.gpio_write(ultrasonic_handle, SENSOR1_TRIG, 0)
        lgpio.gpio_write(ultrasonic_handle, SENSOR2_TRIG, 0)
        print(f"{Colors.GREEN}[ULTRASONIC] Sensors initialized{Colors.END}")
        time.sleep(0.5)
    except Exception as e:
        try:
            ultrasonic_handle = lgpio.gpiochip_open(0)
            lgpio.gpio_claim_output(ultrasonic_handle, SENSOR1_TRIG)
            lgpio.gpio_claim_output(ultrasonic_handle, SENSOR2_TRIG)
            lgpio.gpio_claim_input(ultrasonic_handle, SENSOR1_ECHO)
            lgpio.gpio_claim_input(ultrasonic_handle, SENSOR2_ECHO)
            lgpio.gpio_write(ultrasonic_handle, SENSOR1_TRIG, 0)
            lgpio.gpio_write(ultrasonic_handle, SENSOR2_TRIG, 0)
            print(f"{Colors.GREEN}[ULTRASONIC] Sensors initialized (gpiochip0){Colors.END}")
            time.sleep(0.5)
        except Exception as e2:
            print(f"{Colors.YELLOW}[ULTRASONIC] Init failed: {e2}{Colors.END}")
            ultrasonic_handle = None

# Camera functionality
def init_camera():
    """Check if camera is available using ffmpeg"""
    if not CAMERA_AVAILABLE:
        print(f"{Colors.YELLOW}[CAMERA] Camera not available{Colors.END}")
        return False

    try:
        # Test camera availability with ffmpeg
        result = subprocess.run(
            ["ffmpeg", "-f", "video4linux2", "-i", "/dev/video0", "-frames:v", "1", "-f", "null", "-"],
            capture_output=True,
            timeout=5
        )
        # ffmpeg returns non-zero exit code even for successful device detection
        # but we can check if it found the device
        print(f"{Colors.GREEN}[CAMERA] Camera initialized successfully{Colors.END}")
        return True
    except subprocess.TimeoutExpired:
        print(f"{Colors.GREEN}[CAMERA] Camera detected (timeout expected){Colors.END}")
        return True
    except Exception as e:
        print(f"{Colors.YELLOW}[CAMERA] Camera may not be available: {e}{Colors.END}")
        return True  # Still try to use it

def capture_image():
    """Capture an image using rpicam-jpeg and return file path and base64 data"""
    try:
        image_path = "/tmp/robot_capture.jpg"

        # Use rpicam-jpeg to capture an image
        result = subprocess.run([
            "rpicam-jpeg",
            "--output", image_path,
            "--width", "640",
            "--height", "480",
            "--quality", "85",
            "--nopreview",
            "--immediate"  # Capture immediately without preview
        ], capture_output=True, timeout=15)

        if result.returncode != 0:
            print(f"{Colors.RED}[CAMERA] rpicam-jpeg capture failed: {result.stderr.decode()}{Colors.END}")
            return None

        if not os.path.exists(image_path):
            print(f"{Colors.RED}[CAMERA] Image file not created{Colors.END}")
            return None

        # Read the image file and convert to base64
        with open(image_path, 'rb') as f:
            image_bytes = f.read()

        image_b64 = base64.b64encode(image_bytes).decode('utf-8')

        print(f"{Colors.GREEN}[CAMERA] Image captured successfully{Colors.END}")
        return image_path, image_b64

    except subprocess.TimeoutExpired:
        print(f"{Colors.RED}[CAMERA] Camera capture timeout{Colors.END}")
        return None
    except Exception as e:
        print(f"{Colors.RED}[CAMERA] Failed to capture image: {e}{Colors.END}")
        return None

def measure_distance(trig_pin, echo_pin):
    if ultrasonic_handle is None:
        return None
    # Only one thread may pulse/read a sensor at a time, or the trigger/echo
    # pulses from different threads interfere and give garbage readings.
    with ultrasonic_lock:
        return _measure_distance_locked(trig_pin, echo_pin)

def _measure_distance_locked(trig_pin, echo_pin):
    try:
        lgpio.gpio_write(ultrasonic_handle, trig_pin, 1)
        time.sleep(0.00001)
        lgpio.gpio_write(ultrasonic_handle, trig_pin, 0)
        start_time = time.time()
        timeout_start = start_time
        while lgpio.gpio_read(ultrasonic_handle, echo_pin) == 0:
            start_time = time.time()
            if start_time - timeout_start > TIMEOUT:
                return None
        stop_time = time.time()
        timeout_stop = stop_time
        while lgpio.gpio_read(ultrasonic_handle, echo_pin) == 1:
            stop_time = time.time()
            if stop_time - timeout_stop > TIMEOUT:
                return None
        elapsed_time = stop_time - start_time
        distance = (elapsed_time * SPEED_OF_SOUND) / 2
        if 2 <= distance <= 400:
            return round(distance, 2)
        return None
    except:
        return None

def check_front_obstacle():
    """Check obstacle in front direction using sensor 2"""
    d2 = measure_distance(SENSOR2_TRIG, SENSOR2_ECHO)
    if d2 and d2 < OBSTACLE_THRESHOLD:
        return True, d2
    return False, None

def check_back_obstacle():
    """Check obstacle in back direction using sensor 1"""
    d1 = measure_distance(SENSOR1_TRIG, SENSOR1_ECHO)
    if d1 and d1 < OBSTACLE_THRESHOLD:
        return True, d1
    return False, None

def check_obstacle():
    """Legacy function - checks both sensors (used for spinning/turning)"""
    d1 = measure_distance(SENSOR1_TRIG, SENSOR1_ECHO)
    d2 = measure_distance(SENSOR2_TRIG, SENSOR2_ECHO)
    if d1 and d1 < OBSTACLE_THRESHOLD:
        return True, d1
    if d2 and d2 < OBSTACLE_THRESHOLD:
        return True, d2
    return False, None

def left_motor_forward(speed=0.4):
    if ENA is None: return
    IN1.off()
    IN2.on()
    ENA.value = speed

def left_motor_backward(speed=0.4):
    if ENA is None: return
    IN1.on()
    IN2.off()
    ENA.value = speed

def left_motor_stop():
    if ENA is None: return
    IN1.off()
    IN2.off()
    ENA.value = 0

def right_motor_forward(speed=0.4):
    if ENB is None: return
    IN3.off()
    IN4.on()
    ENB.value = speed

def right_motor_backward(speed=0.4):
    if ENB is None: return
    IN3.on()
    IN4.off()
    ENB.value = speed

def right_motor_stop():
    if ENB is None: return
    IN3.off()
    IN4.off()
    ENB.value = 0

def all_stop():
    left_motor_stop()
    right_motor_stop()

# PIPER TTS
class PiperTTS:
    def __init__(self, model_path, config_path):
        from piper_onnx import Piper
        self.p = Piper(model_path, config_path)
    
    def speak(self, text, out_file=OUT_WAV):
        audio, sr = self.p.create(text)
        import numpy as np
        import wave
        audio = np.asarray(audio, dtype=np.float32)
        # Clip to [-1, 1] BEFORE scaling: values outside this range overflow
        # int16 and wrap around, which is heard as crackle/pops ("breaking").
        audio = np.clip(audio, -1.0, 1.0)
        pcm = (audio * 32767.0).astype("int16")
        with wave.open(out_file, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())
        return out_file

def update_robot_status(key, value):
    """Update robot status for web UI"""
    global robot_status
    with status_lock:
        robot_status[key] = value

def get_robot_status():
    """Return current robot status"""
    global robot_status
    with status_lock:
        return robot_status.copy()

class RobotUIHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            html_content = self.get_robot_html()
            self.wfile.write(html_content.encode())
        elif self.path == '/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            status = get_robot_status()
            self.wfile.write(json.dumps(status).encode())
        elif self.path == '/video_feed':
            self.send_response(200)
            self.send_header('Content-type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.stream_video()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/quit':
            # On-screen "Exit" button: acknowledge, then trigger a clean shutdown
            # of the whole program (the finally block also closes this browser).
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            print(f"{Colors.RED}[WEB UI] Exit requested from interface - shutting down{Colors.END}")
            # FIRST close the fullscreen kiosk browser (so we exit fullscreen right
            # away), THEN trigger a clean shutdown of the whole program via SIGINT.
            def _shutdown():
                close_kiosk_browser()
                time.sleep(0.3)
                os.kill(os.getpid(), signal.SIGINT)
            threading.Thread(target=_shutdown, daemon=True).start()
        elif self.path == '/control':
            # Movement/commands sent from the browser interface (keyboard driving)
            length = int(self.headers.get('Content-Length', 0) or 0)
            body = self.rfile.read(length).decode() if length else ''
            action = ''
            try:
                action = json.loads(body).get('action', '') if body else ''
            except Exception:
                action = body.strip()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            try:
                handle_web_control(action)
            except Exception as e:
                print(f"{Colors.RED}[WEB CONTROL] error: {e}{Colors.END}")
        else:
            self.send_response(404)
            self.end_headers()

    def stream_video(self):
        """Stream MJPEG video frames"""
        global video_frame_buffer, video_frame_lock
        while True:
            try:
                frame_data = None
                with video_frame_lock:
                    if video_frame_buffer is not None:
                        frame_data = video_frame_buffer
                if frame_data is None:
                    # No frame yet; wait briefly instead of busy-spinning a CPU core
                    time.sleep(0.05)
                    continue

                self.wfile.write(b'--frame\r\n')
                self.wfile.write(b'Content-Type: image/jpeg\r\n\r\n')
                self.wfile.write(frame_data)
                self.wfile.write(b'\r\n')
                time.sleep(0.033)  # ~30 FPS
            except (BrokenPipeError, ConnectionResetError):
                break
            except Exception as e:
                break

    def get_robot_html(self):
        """Return the HTML content for the web interface"""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Friendly Robot Eyes</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background: radial-gradient(circle at 50% 40%, #7a1230 0%, #4c0519 55%, #2a0912 100%); /* rose-500 theme */
            height: 100vh;
            width: 100vw;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden;
        }

        .face-container {
            display: flex;
            gap: 10vw; /* Space between eyes */
            width: 80%;
            justify-content: center;
            align-items: center;
            animation: float 5s ease-in-out infinite; /* gentle breathing bob */
        }

        /* Gentle up-and-down bob so the face feels alive, like breathing */
        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-1.5vh); }
        }

        /* Quick happy bounce used while the robot is talking */
        @keyframes talkBounce {
            0%, 100% { transform: translateY(0) scale(1); }
            30% { transform: translateY(-2vh) scale(1.03); }
            60% { transform: translateY(0.3vh) scale(0.99); }
        }

        .face-container.talking {
            animation: talkBounce 0.55s ease-in-out infinite;
        }

        /* Brighter rose glow on the eyes while the robot is listening to you */
        .face-container.listening .eye {
            box-shadow: 0 0 90px rgba(251, 113, 133, 0.75), inset 0 -12px 28px rgba(244, 63, 94, 0.14);
        }

        .eye-group {
            display: flex;
            flex-direction: column;
            align-items: center;
        }

        /* Soft rosy blush cheeks under each eye for extra cuteness */
        .blush {
            width: 13vw;
            height: 6vw;
            max-width: 150px;
            max-height: 70px;
            margin-top: 1vw;
            background: radial-gradient(circle, rgba(251, 113, 133, 0.8) 0%, rgba(251, 113, 133, 0) 70%);
            border-radius: 50%;
            filter: blur(3px);
        }

        .eye {
            position: relative;
            width: 36vw;
            height: 36vw;
            max-width: 410px;
            max-height: 410px;
            background: radial-gradient(circle at 50% 42%, #fff5f6 0%, #ffe4e9 100%); /* soft rose-white */
            border-radius: 50%;
            overflow: hidden; /* Hides the pupil when looking far sideways */
            box-shadow: 0 0 65px rgba(244, 63, 94, 0.55), inset 0 -12px 28px rgba(244, 63, 94, 0.14); /* rose glow */

            /* Initial state for blink animation */
            transform: scaleY(1);
            transition: transform 0.1s ease-in-out, clip-path 0.3s ease-in-out;
        }

        .pupil {
            position: absolute;
            top: 50%;
            left: 50%;
            width: 70%; /* bigger = cuter */
            height: 70%;
            background: radial-gradient(circle at 50% 35%, #5b2130 0%, #2b0f16 72%); /* glossy warm-dark */
            border-radius: 50%;
            transform: translate(-50%, -50%);
            transition: transform 0.5s cubic-bezier(0.25, 0.1, 0.25, 1); /* snappy but smooth glances */
        }

        /* The cute shiny reflection in the eye */
        .highlight {
            position: absolute;
            top: 14%;
            right: 18%;
            width: 33%;
            height: 33%;
            background: rgba(255, 255, 255, 0.97);
            border-radius: 50%;
        }

        .highlight-small {
            position: absolute;
            bottom: 25%;
            left: 25%;
            width: 10%;
            height: 10%;
            background: rgba(255, 255, 255, 0.6);
            border-radius: 50%;
        }

        /* The Eyelid - Used for the blinking animation */
        .eyelid {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 0%;
            background-color: #4c0519; /* deep rose to match theme */
            z-index: 10;
            transition: height 0.1s ease-in-out;
        }

        /* Active blink state class */
        .eye.blinking .eyelid {
            height: 100%;
        }
        /* Happy squint state class */
        .eye.happy {
            /* Creates a "smiling eye" shape by flattening the bottom slightly */
            clip-path: ellipse(130% 100% at 50% 0%);
        }

        .status-panel {
            position: absolute;
            bottom: 20px;
            left: 20px;
            background: rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 15px;
            backdrop-filter: blur(10px);
            color: white;
            font-family: Arial, sans-serif;
            font-size: 18px;
        }

        .status-panel div {
            margin-bottom: 5px;
        }

        .audio-display {
            position: fixed;
            bottom: 40px;
            left: 50%;
            transform: translateX(-50%);
            text-align: center;
            z-index: 250;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 18px;
            max-width: 96%;
            width: 100%;
        }

        .audio-input {
            font-size: clamp(1.7rem, 3.6vw, 3rem);
            font-weight: 700;
            color: #ffffff;
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.6);
            background: #f43f5e;                 /* solid rose-500 - always readable */
            border: 3px solid #fecdd3;
            padding: 20px 42px;
            border-radius: 24px;
            display: none;
            opacity: 0;
            transform: translateY(30px) scale(0.95);
            transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 12px 45px rgba(0, 0, 0, 0.5);
            line-height: 1.35;
            letter-spacing: 0.3px;
            max-width: 92vw;
            word-wrap: break-word;
        }

        .audio-input::before {
            content: '🎤 You: ';
            opacity: 0.85;
        }

        .audio-input.show {
            opacity: 1;
            transform: translateY(0) scale(1);
        }

        .audio-output {
            font-size: clamp(1.7rem, 3.6vw, 3rem);
            font-weight: 700;
            color: #ffffff;
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.6);
            background: #9f1239;                 /* solid rose-800 - always readable */
            border: 3px solid #fb7185;
            padding: 20px 42px;
            border-radius: 24px;
            display: none;
            opacity: 0;
            transform: translateY(30px) scale(0.95);
            transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
            box-shadow: 0 12px 45px rgba(0, 0, 0, 0.5);
            line-height: 1.35;
            letter-spacing: 0.3px;
            max-width: 92vw;
            word-wrap: break-word;
        }

        .audio-output::before {
            content: '🤖 Buddy: ';
            opacity: 0.85;
        }

        .audio-output.show {
            opacity: 1;
            transform: translateY(0) scale(1);
        }

        /* Video Stream Panel */
        .video-panel {
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(0, 0, 0, 0.8);
            border-radius: 15px;
            padding: 10px;
            border: 2px solid rgba(244, 63, 94, 0.5);
            box-shadow: 0 10px 40px rgba(244, 63, 94, 0.2);
            z-index: 300;
            transition: all 0.3s ease;
        }

        .video-panel.hidden {
            transform: translateX(calc(100% + 40px));
            opacity: 0;
        }

        .video-panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            padding-bottom: 8px;
            border-bottom: 1px solid rgba(244, 63, 94, 0.3);
        }

        .video-panel-title {
            color: #f43f5e;
            font-family: Arial, sans-serif;
            font-size: 14px;
            font-weight: bold;
            text-shadow: 0 0 10px rgba(244, 63, 94, 0.5);
        }

        .video-toggle-btn {
            background: rgba(244, 63, 94, 0.2);
            border: 1px solid rgba(244, 63, 94, 0.5);
            color: #f43f5e;
            padding: 5px 10px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 12px;
            transition: all 0.2s ease;
        }

        .video-toggle-btn:hover {
            background: rgba(244, 63, 94, 0.4);
        }

        .video-stream {
            width: 320px;
            height: 240px;
            background: #000;
            border-radius: 10px;
            object-fit: cover;
        }

        .video-placeholder {
            width: 320px;
            height: 240px;
            background: linear-gradient(135deg, #1a1a2e 0%, #0a0a15 100%);
            border-radius: 10px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            color: #666;
            font-family: Arial, sans-serif;
            font-size: 14px;
        }

        .video-placeholder-icon {
            font-size: 48px;
            margin-bottom: 10px;
            opacity: 0.5;
        }

        .gesture-info {
            margin-top: 10px;
            color: #fb7185;
            font-family: Arial, sans-serif;
            font-size: 12px;
            text-align: center;
        }

        .gesture-status {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            margin-top: 5px;
        }

        .gesture-indicator {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #ff4444;
            transition: background 0.3s ease;
        }

        .gesture-indicator.active {
            background: #f43f5e;
            box-shadow: 0 0 10px rgba(244, 63, 94, 0.5);
        }

        .gesture-legend {
            margin-top: 8px;
            font-size: 10px;
            color: #888;
            line-height: 1.4;
        }

        /* Minimize button */
        .minimize-btn {
            position: fixed;
            top: 20px;
            right: 20px;
            background: rgba(244, 63, 94, 0.2);
            border: 2px solid rgba(244, 63, 94, 0.5);
            color: #f43f5e;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            cursor: pointer;
            font-size: 24px;
            display: none;
            justify-content: center;
            align-items: center;
            z-index: 299;
            transition: all 0.3s ease;
            box-shadow: 0 5px 20px rgba(244, 63, 94, 0.3);
        }

        .minimize-btn:hover {
            background: rgba(244, 63, 94, 0.4);
            transform: scale(1.1);
        }

        .minimize-btn.show {
            display: flex;
        }

        /* Exit / back button (leave the interface) */
        #exit-btn {
            position: fixed;
            top: 20px;
            left: 20px;
            width: 52px;
            height: 52px;
            border-radius: 50%;
            background: rgba(244, 63, 94, 0.18);
            border: 2px solid rgba(244, 63, 94, 0.6);
            color: #ffe4e9;
            font-size: 24px;
            cursor: pointer;
            z-index: 400;
            display: flex;
            justify-content: center;
            align-items: center;
            transition: all 0.2s ease;
            backdrop-filter: blur(8px);
        }
        #exit-btn:hover { background: rgba(244, 63, 94, 0.45); transform: scale(1.08); }

        #exit-overlay {
            position: fixed;
            inset: 0;
            background: rgba(20, 4, 9, 0.75);
            backdrop-filter: blur(6px);
            z-index: 500;
            display: none;
            justify-content: center;
            align-items: center;
        }
        #exit-overlay.show { display: flex; }
        #exit-box {
            background: linear-gradient(135deg, #7a1230, #4c0519);
            border: 2px solid rgba(251, 113, 133, 0.6);
            border-radius: 20px;
            padding: 30px 40px;
            text-align: center;
            font-family: Arial, sans-serif;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
        }
        #exit-msg { color: #fff1f2; font-size: 1.6rem; margin-bottom: 22px; }
        #exit-box button {
            font-size: 1.1rem;
            padding: 12px 24px;
            margin: 0 8px;
            border-radius: 12px;
            cursor: pointer;
            border: none;
            font-weight: 600;
        }
        .exit-yes { background: #f43f5e; color: white; }
        .exit-no { background: rgba(255,255,255,0.15); color: #ffe4e9; }

        /* Obstacle alert banner (top-center) */
        #obstacle-alert {
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%) translateY(-20px);
            background: linear-gradient(135deg, #e11d48, #9f1239);
            color: #fff;
            font-family: Arial, sans-serif;
            font-size: 1.5rem;
            font-weight: 700;
            padding: 14px 30px;
            border-radius: 16px;
            border: 2px solid #fb7185;
            box-shadow: 0 8px 30px rgba(225, 29, 72, 0.5);
            z-index: 450;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.25s ease, transform 0.25s ease;
        }
        #obstacle-alert.show {
            opacity: 1;
            transform: translateX(-50%) translateY(0);
            animation: obstaclePulse 1s ease-in-out infinite;
        }
        @keyframes obstaclePulse {
            0%, 100% { box-shadow: 0 8px 30px rgba(225, 29, 72, 0.5); }
            50% { box-shadow: 0 8px 45px rgba(255, 92, 92, 0.9); }
        }
    </style>
</head>
<body>

    <!-- Video Stream Panel (hidden until the camera is actually in use) -->
    <div class="video-panel" id="video-panel" style="display: none;">
        <div class="video-panel-header">
            <span class="video-panel-title">🖐️ Hand Gesture Detection</span>
            <button class="video-toggle-btn" id="minimize-video" onclick="toggleVideoPanel()">−</button>
        </div>
        <div id="video-container">
            <img id="video-stream" class="video-stream" src="/video_feed" alt="Video Stream" onerror="showPlaceholder()" style="display: none;" />
            <div id="video-placeholder" class="video-placeholder">
                <div class="video-placeholder-icon">📹</div>
                <div>Camera initializing...</div>
                <div style="font-size: 11px; margin-top: 5px; color: #555;">Press G to enable gestures</div>
            </div>
        </div>
        <div class="gesture-info">
            <div class="gesture-status">
                <span class="gesture-indicator" id="gesture-indicator"></span>
                <span id="gesture-status-text">Gesture Control: OFF</span>
            </div>
            <div class="gesture-legend">
                ✋ Stop | ☝️ Forward | ✌️ Back | 👍 Turn | ✊ E-Stop
            </div>
        </div>
    </div>

    <!-- Minimize button (shown when panel is hidden) -->
    <button class="minimize-btn" id="restore-video" onclick="toggleVideoPanel()">📹</button>

    <!-- Exit / back button -->
    <button id="exit-btn" onclick="confirmExit()" title="Exit interface">&#9211;</button>
    <div id="exit-overlay">
        <div id="exit-box">
            <div id="exit-msg">Exit the robot interface?</div>
            <div>
                <button class="exit-yes" onclick="doExit()">Yes, exit</button>
                <button class="exit-no" onclick="cancelExit()">Cancel</button>
            </div>
        </div>
    </div>

    <!-- Obstacle alert banner -->
    <div id="obstacle-alert">&#9888;&#65039; Obstacle: <span id="obstacle-alert-text"></span></div>

    <!-- Audio Display -->
    <div class="audio-display">
        <div id="audio-input-display" class="audio-input"></div>
        <div id="audio-output-display" class="audio-output"></div>
    </div>

    <!-- Image Preview -->
    <div id="image-preview-container" style="position: fixed; top: 20px; left: 50%; transform: translateX(-50%); z-index: 200; display: none;">
        <img id="image-preview" style="max-width: 300px; max-height: 200px; border-radius: 15px; border: 3px solid rgba(244, 63, 94, 0.6); box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);" />
        <div style="text-align: center; color: #fb7185; font-size: 0.9rem; margin-top: 8px; text-shadow: 0 2px 10px rgba(244, 63, 94, 0.5);">📸 Captured Image</div>
    </div>

    <div class="face-container">
        <!-- Left Eye -->
        <div class="eye-group">
            <div class="eye" id="eye-left">
                <div class="eyelid"></div>
                <div class="pupil">
                    <div class="highlight"></div>
                    <div class="highlight-small"></div>
                </div>
            </div>
            <div class="blush"></div>
        </div>

        <!-- Right Eye -->
        <div class="eye-group">
            <div class="eye" id="eye-right">
                <div class="eyelid"></div>
                <div class="pupil">
                    <div class="highlight"></div>
                    <div class="highlight-small"></div>
                </div>
            </div>
            <div class="blush"></div>
        </div>
    </div>

    <div class="status-panel">
        <div id="status">Status: Initializing...</div>
        <div id="speed">Speed: 0.4</div>
        <div id="obstacle">Obstacle: Clear</div>
        <div id="voice">Voice: Ready</div>
        <div id="gesture">Gesture: OFF</div>
        <div id="mode" style="margin-top: 6px; font-size: 16px; color: #fb7185;">Mode: Manual</div>
        <div id="model-info" style="margin-top: 8px; font-size: 16px; color: #fb7185;">Model: gemma3:1b</div>
        <div id="image-description" style="margin-top: 10px; font-size: 16px; color: #fb7185;"></div>
    </div>

    <script>
        const leftEye = document.getElementById('eye-left');
        const rightEye = document.getElementById('eye-right');
        const leftPupil = leftEye.querySelector('.pupil');
        const rightPupil = rightEye.querySelector('.pupil');

        // --- Blinking Logic ---

        function blink() {
            // Remove happy class briefly if it's there so the blink looks full
            const wasHappy = leftEye.classList.contains('happy');
            leftEye.classList.remove('happy');
            rightEye.classList.remove('happy');

            // Add blink class
            leftEye.classList.add('blinking');
            rightEye.classList.add('blinking');

            // Remove blink class after a short delay (speed of blink)
            setTimeout(() => {
                leftEye.classList.remove('blinking');
                rightEye.classList.remove('blinking');

                // Restore happy state if it was there
                if (wasHappy) {
                    leftEye.classList.add('happy');
                    rightEye.classList.add('happy');
                }

                // Set the next blink time randomly
                scheduleNextBlink();
            }, 180 + Math.random() * 70); // Natural blink duration (180-250ms)
        }

        function scheduleNextBlink() {
            // Random time between 3.5-7 seconds (livelier, still natural)
            const randomDelay = 3500 + Math.random() * 3500;

            // Occasionally do a "double blink" (5% chance)
            if (Math.random() < 0.05) {
                setTimeout(() => {
                    blink();
                    // Second blink happens after the first completes
                }, randomDelay);
            } else {
                setTimeout(blink, randomDelay);
            }
        }

        // --- Happy/Friendly Logic ---

        function toggleHappy() {
            // 50% chance to be in "happy mode" (squinting slightly)
            const isHappy = Math.random() > 0.5;

            if (isHappy) {
                leftEye.classList.add('happy');
                rightEye.classList.add('happy');
            } else {
                leftEye.classList.remove('happy');
                rightEye.classList.remove('happy');
            }

            // Change expression every 8-15 seconds (much less frequent)
            setTimeout(toggleHappy, 8000 + Math.random() * 7000);
        }

        // --- Looking Around Logic (Idle Animation) ---

        function moveEyes() {
            // Only wander when idle, so we don't fight the reactive expressions
            // (listening/forward/left/right/etc.) set from robot status.
            const idleStates = ['normal', 'blinking', 'thinking'];
            if (idleStates.includes(lastState)) {
                // Mostly small curious drifts, occasionally a bigger glance
                const range = Math.random() < 0.25 ? 55 : 28;
                const x = (Math.random() - 0.5) * range;
                const y = (Math.random() - 0.5) * range;
                leftPupil.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
                rightPupil.style.transform = `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))`;
            }

            // Livelier cadence: next glance in 1.8-4.5 seconds
            const nextMove = 1800 + Math.random() * 2700;
            setTimeout(moveEyes, nextMove);
        }

        // --- Robot Status Integration ---

        // Track last state to avoid redundant updates
        let lastState = 'normal';

        function updateEyesForState(state) {
            // Skip if same state (prevents repeated blink triggers)
            if (state === lastState && state !== 'normal') return;
            lastState = state;

            if (state === 'listening') {
                // Wide eyes, looking attentive
                leftPupil.style.transform = 'translate(-50%, -50%) scale(1.1)';
                rightPupil.style.transform = 'translate(-50%, -50%) scale(1.1)';
            } else if (state === 'surprised') {
                // Wide eyes looking up
                leftPupil.style.transform = 'translate(-50%, calc(-50% - 20px))';
                rightPupil.style.transform = 'translate(-50%, calc(-50% - 20px))';
            } else if (state === 'sleeping') {
                // Eyes half closed
                leftPupil.style.transform = 'translate(-50%, calc(-50% + 15px))';
                rightPupil.style.transform = 'translate(-50%, calc(-50% + 15px))';
            } else if (state === 'left') {
                // Looking left
                leftPupil.style.transform = 'translate(calc(-50% - 25px), -50%)';
                rightPupil.style.transform = 'translate(calc(-50% - 25px), -50%)';
            } else if (state === 'right') {
                // Looking right
                leftPupil.style.transform = 'translate(calc(-50% + 25px), -50%)';
                rightPupil.style.transform = 'translate(calc(-50% + 25px), -50%)';
            } else if (state === 'forward') {
                // Looking forward/up
                leftPupil.style.transform = 'translate(-50%, calc(-50% - 15px))';
                rightPupil.style.transform = 'translate(-50%, calc(-50% - 15px))';
            } else if (state === 'backward') {
                // Looking down
                leftPupil.style.transform = 'translate(-50%, calc(-50% + 15px))';
                rightPupil.style.transform = 'translate(-50%, calc(-50% + 15px))';
            } else if (state === 'happy' || state === 'excited') {
                // Big cute happy squint + look up
                leftEye.classList.add('happy');
                rightEye.classList.add('happy');
                leftPupil.style.transform = 'translate(-50%, calc(-50% - 10px)) scale(1.05)';
                rightPupil.style.transform = 'translate(-50%, calc(-50% - 10px)) scale(1.05)';
            } else if (state === 'curious') {
                // Tilt-glance to the side, inquisitive
                leftEye.classList.remove('happy');
                rightEye.classList.remove('happy');
                leftPupil.style.transform = 'translate(calc(-50% + 22px), calc(-50% - 8px))';
                rightPupil.style.transform = 'translate(calc(-50% + 22px), calc(-50% - 8px))';
            } else if (state === 'blinking' || state === 'thinking') {
                // Do nothing - let the natural blink schedule handle blinking
                // Just slightly adjust pupils to look focused
                leftPupil.style.transform = 'translate(-50%, -50%)';
                rightPupil.style.transform = 'translate(-50%, -50%)';
            }
            // For 'normal' state, do nothing - let idle animations continue
        }

        // --- Exit / back from interface ---
        function confirmExit() {
            document.getElementById('exit-overlay').classList.add('show');
        }
        function cancelExit() {
            document.getElementById('exit-overlay').classList.remove('show');
        }
        function doExit() {
            // 1) Exit fullscreen right away (covers Fullscreen-API / normal-tab cases)
            try { if (document.fullscreenElement) document.exitFullscreen(); } catch (e) {}
            // 2) Tell the robot to shut down - this ALSO closes the kiosk browser first
            fetch('/quit', { method: 'POST' }).catch(() => {});
            // 3) Try to close the tab/window (works for kiosk / script-opened windows)
            setTimeout(() => { try { window.close(); } catch (e) {} }, 300);
            // 4) Last-resort message if the window is somehow still open
            setTimeout(() => {
                document.body.innerHTML =
                    '<div style="color:#ffe4e9;font-family:Arial;font-size:2rem;text-align:center;width:100%;padding-top:40vh;">&#128075; Robot stopped. You can close this screen.</div>';
            }, 1500);
        }

        function pollStatus() {
            fetch('/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('status').textContent = 'Status: ' + data.status;
                    document.getElementById('speed').textContent = 'Speed: ' + data.speed;
                    document.getElementById('obstacle').textContent = 'Obstacle: ' + data.obstacle;
                    const obsEl = document.getElementById('obstacle');
                    obsEl.style.color = data.obstacle_alert ? '#ff5c5c' : '#fb7185';
                    const obsBanner = document.getElementById('obstacle-alert');
                    if (obsBanner) {
                        if (data.obstacle_alert) {
                            document.getElementById('obstacle-alert-text').textContent = data.obstacle;
                            obsBanner.classList.add('show');
                        } else {
                            obsBanner.classList.remove('show');
                        }
                    }
                    document.getElementById('voice').textContent = 'Voice: ' + data.voice;
                    if (data.current_model) {
                        document.getElementById('model-info').textContent = 'Model: ' + data.current_model;
                    }
                    const inputDisplay = document.getElementById('audio-input-display');
                    const outputDisplay = document.getElementById('audio-output-display');

                    if (data.audio_input) {
                        inputDisplay.textContent = data.audio_input;
                        inputDisplay.style.display = 'block';
                        inputDisplay.classList.add('show');
                    } else {
                        inputDisplay.classList.remove('show');
                        setTimeout(() => {
                            if (!inputDisplay.classList.contains('show')) {
                                inputDisplay.style.display = 'none';
                            }
                        }, 500);
                    }

                    if (data.audio_output) {
                        outputDisplay.textContent = data.audio_output;
                        outputDisplay.style.display = 'block';
                        outputDisplay.classList.add('show');
                    } else {
                        outputDisplay.classList.remove('show');
                        setTimeout(() => {
                            if (!outputDisplay.classList.contains('show')) {
                                outputDisplay.style.display = 'none';
                            }
                        }, 500);
                    }
                    if (data.image_description) {
                        document.getElementById('image-description').textContent = 'Vision: ' + data.image_description;
                        document.getElementById('image-description').style.display = 'block';
                    } else {
                        document.getElementById('image-description').style.display = 'none';
                    }

                    // Show image preview if available
                    if (data.captured_image) {
                        const imgPreview = document.getElementById('image-preview');
                        const imgContainer = document.getElementById('image-preview-container');
                        imgPreview.src = 'data:image/jpeg;base64,' + data.captured_image;
                        imgContainer.style.display = 'block';
                    } else {
                        document.getElementById('image-preview-container').style.display = 'none';
                    }

                    // Camera panel appears ONLY when the camera is actually in
                    // use (gesture control on / streaming); closed by default.
                    const camPanel = document.getElementById('video-panel');
                    if (camPanel) {
                        const camInUse = data.gesture_enabled || data.video_streaming;
                        camPanel.style.display = camInUse ? 'block' : 'none';
                    }

                    // Update gesture status
                    updateGestureStatus(data.gesture_enabled, data.video_streaming);

                    // Mode line: roam + wake/awake state
                    const modeEl = document.getElementById('mode');
                    if (modeEl) {
                        let m = data.roam_enabled ? '🤖 Roaming' : 'Manual';
                        if (data.wake_required) m += (data.awake ? ' · Awake' : ' · Asleep 💤');
                        modeEl.textContent = 'Mode: ' + m;
                    }

                    // Liveliness: bounce while talking, glow while listening
                    const face = document.querySelector('.face-container');
                    if (face) {
                        face.classList.toggle('talking', !!data.audio_output);
                        face.classList.toggle('listening', data.eye_state === 'listening');
                    }

                    updateEyesForState(data.eye_state);
                })
                .catch(err => console.log('Status update failed'));
        }

        // --- Video Panel Functions ---
        let videoPanelVisible = true;
        let videoStreamStarted = false;

        function toggleVideoPanel() {
            const panel = document.getElementById('video-panel');
            const restoreBtn = document.getElementById('restore-video');
            videoPanelVisible = !videoPanelVisible;
            
            if (videoPanelVisible) {
                panel.classList.remove('hidden');
                restoreBtn.classList.remove('show');
            } else {
                panel.classList.add('hidden');
                restoreBtn.classList.add('show');
            }
        }

        function showPlaceholder() {
            document.getElementById('video-stream').style.display = 'none';
            document.getElementById('video-placeholder').style.display = 'flex';
        }

        function showVideoStream() {
            document.getElementById('video-placeholder').style.display = 'none';
            document.getElementById('video-stream').style.display = 'block';
        }

        function updateGestureStatus(enabled, streaming) {
            const indicator = document.getElementById('gesture-indicator');
            const statusText = document.getElementById('gesture-status-text');
            const gestureDiv = document.getElementById('gesture');
            const videoStream = document.getElementById('video-stream');
            const placeholder = document.getElementById('video-placeholder');
            
            if (enabled) {
                indicator.classList.add('active');
                statusText.textContent = 'Gesture Control: ON';
                statusText.style.color = '#f43f5e';
                gestureDiv.textContent = 'Gesture: ON';
                gestureDiv.style.color = '#f43f5e';
            } else {
                indicator.classList.remove('active');
                statusText.textContent = 'Gesture Control: OFF';
                statusText.style.color = '#888';
                gestureDiv.textContent = 'Gesture: OFF';
                gestureDiv.style.color = '#888';
            }

            // Show/hide video stream based on streaming status
            if (streaming && !videoStreamStarted) {
                videoStreamStarted = true;
                videoStream.src = '/video_feed?' + Date.now(); // Add timestamp to force reload
                videoStream.onload = showVideoStream;
                videoStream.onerror = showPlaceholder;
            } else if (!streaming) {
                videoStreamStarted = false;
                showPlaceholder();
            }
        }

        // NOTE: the camera stream is intentionally NOT started on page load.
        // It only starts when the camera is in use (gesture control enabled),
        // handled by updateGestureStatus() from the polled status.

        // --- Keyboard driving FROM the interface ---
        // Works whenever this screen has focus (which it does in fullscreen),
        // because terminal keys only reach the program when the terminal is focused.
        const KEY_ACTION = {
            'w': 'forward', 'arrowup': 'forward',
            's': 'backward', 'arrowdown': 'backward',
            'a': 'left', 'arrowleft': 'left',
            'd': 'right', 'arrowright': 'right'
        };
        const ONESHOT_ACTION = {
            ' ': 'stop', 'r': 'roam_toggle',
            '+': 'speed_up', '=': 'speed_up', '-': 'speed_down'
        };
        let currentDriveKey = null;
        let driveInterval = null;

        function sendControl(action) {
            fetch('/control', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: action })
            }).catch(() => {});
        }

        function startDrive(key, action) {
            if (currentDriveKey === key) return;
            stopDrive(false);                 // clear any previous key
            currentDriveKey = key;
            sendControl(action);              // move now...
            driveInterval = setInterval(() => sendControl(action), 200);  // ...and keep moving while held
        }
        function stopDrive(sendStop) {
            if (driveInterval) { clearInterval(driveInterval); driveInterval = null; }
            currentDriveKey = null;
            if (sendStop) sendControl('stop');
        }

        document.addEventListener('keydown', (e) => {
            // Ignore keys while the exit dialog is open
            if (document.getElementById('exit-overlay').classList.contains('show')) return;
            const k = e.key.toLowerCase();
            if (k in KEY_ACTION) {
                e.preventDefault();
                if (e.repeat) return;         // our own interval handles the hold
                startDrive(k, KEY_ACTION[k]);
            } else if (k in ONESHOT_ACTION) {
                e.preventDefault();
                if (e.repeat) return;
                if (k === ' ') stopDrive(false);   // space also cancels any hold
                sendControl(ONESHOT_ACTION[k]);
            }
        });
        document.addEventListener('keyup', (e) => {
            const k = e.key.toLowerCase();
            if (k in KEY_ACTION && k === currentDriveKey) {
                e.preventDefault();
                stopDrive(true);              // released -> stop
            }
        });
        // Safety: if the window loses focus while driving, stop.
        window.addEventListener('blur', () => stopDrive(true));

        // Start the idle animations
        scheduleNextBlink();
        toggleHappy();
        moveEyes();

        // Poll robot status often enough that talk/listen reactions feel responsive
        setInterval(pollStatus, 700);
        pollStatus();
    </script>
</body>
</html>"""

    def log_message(self, format, *args):
        # Suppress default HTTP server logs to keep console clean
        pass

class ReusableTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP server: each request runs in its own thread so keyboard
    control, status polling, and the video stream don't block one another."""
    allow_reuse_address = True
    daemon_threads = True

# Handle to the kiosk browser process, so the on-screen Exit button can close it
kiosk_process = None

def close_kiosk_browser():
    """Close the fullscreen kiosk browser immediately so we drop out of fullscreen.
    Kills the whole process group we launched, then any leftover instance."""
    global kiosk_process
    # 1) Kill the process group we started (the sudo wrapper + chromium children)
    try:
        if kiosk_process is not None:
            try:
                os.killpg(os.getpgid(kiosk_process.pid), signal.SIGTERM)
            except Exception:
                kiosk_process.terminate()
    except Exception:
        pass
    # 2) Also target our specific kiosk instance by its app URL (belt & suspenders)
    try:
        subprocess.run(["pkill", "-f", "--app=http://localhost:8080"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

def launch_kiosk_browser(url="http://localhost:8080"):
    """Open the robot-eyes UI fullscreen (kiosk mode) on the Pi's touchscreen.

    Falls back to a normal browser window if Chromium kiosk mode can't launch.
    """
    global kiosk_process
    chromium = shutil.which("chromium") or shutil.which("chromium-browser")
    sudo_user = os.environ.get("SUDO_USER")

    env = os.environ.copy()
    # The desktop session runs on the login user's display; make sure DISPLAY is set.
    env.setdefault("DISPLAY", ":0")

    kiosk_flags = [
        "--kiosk",
        "--noerrdialogs",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
        "--disable-features=Translate",
        "--check-for-update-interval=31536000",
        "--incognito",
        f"--app={url}",
    ]

    if chromium:
        try:
            if sudo_user:
                # Running under sudo (needed for GPIO): launch the browser AS the
                # desktop user so it appears on their screen, not as root.
                cmd = ["sudo", "-u", sudo_user, "env", f"DISPLAY={env['DISPLAY']}",
                       chromium, *kiosk_flags]
            else:
                cmd = [chromium, *kiosk_flags]
                if os.geteuid() == 0:
                    cmd.insert(1, "--no-sandbox")
            kiosk_process = subprocess.Popen(cmd, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)  # own process group, so we can kill it cleanly
            print(f"{Colors.GREEN}[WEB UI] Kiosk eyes launched on display{Colors.END}")
            return
        except Exception as e:
            print(f"{Colors.YELLOW}[WEB UI] Kiosk launch failed ({e}); trying default browser{Colors.END}")

    try:
        webbrowser.open(url)
        print(f"{Colors.GREEN}[WEB UI] Browser opened{Colors.END}")
    except Exception as e:
        print(f"{Colors.YELLOW}[WEB UI] Could not open browser: {e}{Colors.END}")
        print(f"{Colors.CYAN}[WEB UI] Open {url} manually on the Pi's screen{Colors.END}")

def start_web_ui(port=8080):
    """Start web server for robot UI.

    Bound to localhost (127.0.0.1) ONLY. The /status endpoint exposes live
    microphone transcripts and base64 camera captures, and /video_feed streams
    the camera, all without authentication. Binding to "" would expose the
    robot's mic and camera to everyone on the network. To view from another
    device, use an SSH tunnel or an authenticated reverse proxy instead.
    """
    try:
        with ReusableTCPServer(("127.0.0.1", port), RobotUIHandler) as httpd:
            print(f"{Colors.GREEN}[WEB UI] Server running on http://localhost:{port}{Colors.END}")
            httpd.serve_forever()
    except Exception as e:
        print(f"{Colors.RED}[WEB UI] Failed to start server: {e}{Colors.END}")

# Audio environment cache (computed once)
_audio_env_cache = None

def get_audio_env():
    """Get environment variables needed for audio playback when running as root"""
    global _audio_env_cache
    if _audio_env_cache is not None:
        return _audio_env_cache
    
    env = os.environ.copy()
    sudo_uid = os.environ.get('SUDO_UID')
    
    if sudo_uid:
        runtime_dir = f"/run/user/{sudo_uid}"
        env.update({
            'XDG_RUNTIME_DIR': runtime_dir,
            'PULSE_SERVER': f"unix:{runtime_dir}/pulse/native",
            'PIPEWIRE_RUNTIME_DIR': runtime_dir,
            'PULSE_RUNTIME_PATH': f"{runtime_dir}/pulse"
        })
    
    _audio_env_cache = env
    return env

def _try_audio_command(cmd, env=None, timeout=60):
    """Helper to run audio command and return success status"""
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
        return result.returncode == 0
    except:
        return False

def play_audio(path):
    """Play audio file using the system's selected audio device"""
    audio_env = get_audio_env()
    sudo_user = os.environ.get('SUDO_USER')
    
    # Try paplay first (PulseAudio/PipeWire) - most reliable
    paplay = shutil.which("paplay")
    if paplay:
        if _try_audio_command([paplay, path], audio_env):
            return
        # Try as original user if running with sudo
        if sudo_user and _try_audio_command(["sudo", "-u", sudo_user, paplay, path], audio_env):
            return
    
    # Try mpv with PulseAudio
    mpv = shutil.which("mpv")
    if mpv:
        if _try_audio_command([mpv, "--no-video", "--really-quiet", "--ao=pulse", path], audio_env):
            return
        if sudo_user and _try_audio_command(["sudo", "-u", sudo_user, mpv, "--no-video", "--really-quiet", path], audio_env):
            return
    
    # Try ffplay
    ffplay = shutil.which("ffplay")
    if ffplay and _try_audio_command([ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", path], audio_env):
        return
    
    # Try aplay with pulse
    aplay = shutil.which("aplay")
    if aplay and _try_audio_command([aplay, "-q", "-D", "pulse", path], audio_env):
        return
    
    # Try pygame as last resort
    try:
        import pygame
        for key in ['PULSE_SERVER', 'XDG_RUNTIME_DIR']:
            if audio_env.get(key):
                os.environ[key] = audio_env[key]
        os.environ['SDL_AUDIODRIVER'] = 'pulseaudio'
        pygame.mixer.quit()
        pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        return
    except:
        pass
    
    print(f"{Colors.RED}[AUDIO] All playback methods failed!{Colors.END}")

# Microphone handler
class MicInput:
    def __init__(self, vosk_model_path):
        if not os.path.exists(vosk_model_path):
            raise RuntimeError("Vosk model not found!")
        self.model = Model(vosk_model_path)
        self.pa = pyaudio.PyAudio()
        self.device_index, self.sample_rate = self.detect_input_device()
        print(f"{Colors.GREEN}[MIC] Using device {self.device_index} @ {self.sample_rate} Hz{Colors.END}", flush=True)
        self.stream = self.pa.open(
            rate=self.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=4096
        )
        self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
    
    def detect_input_device(self):
        keyword_hits = ["usb", "audio", "mic", "input"]
        best_idx = None
        best_rate = 16000
        
        for i in range(self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(i)
            name = info["name"].lower()
            chans = info["maxInputChannels"]
            rate = int(info.get("defaultSampleRate", 16000))
            
            if chans > 0:
                if any(k in name for k in keyword_hits):
                    return i, rate
                if best_idx is None:
                    best_idx = i
                    best_rate = rate
        
        if best_idx is not None:
            return best_idx, best_rate
        
        raise RuntimeError("No audio input device found")
    
    def listen(self):
        while True:
            data = self.stream.read(4096, exception_on_overflow=False)
            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    return text

def ask_ollama(prompt, model, url, image_path=None):
    import requests
    system_prompt = "You are Buddy, an educational assistant robot. You are friendly and helpful. Keep answers brief and helpful."

    if image_path and os.path.exists(image_path):
        # Image analysis mode - always use gemma3:4b for vision
        vision_model = DEFAULT_VISION_MODEL
        update_robot_status("current_model", vision_model)
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()

            # Base64 encode the image data for Ollama API
            import base64
            image_b64 = base64.b64encode(image_data).decode('utf-8')

            # Use Ollama chat API for vision
            payload = {
                "model": vision_model,
                "messages": [
                    {
                        'role': 'user',
                        'content': prompt,
                        'images': [image_b64]
                    }
                ],
                "stream": True
            }

            # Use chat endpoint for vision models
            chat_url = url.replace('/api/generate', '/api/chat')
            # (connect timeout, read timeout) so a hung Ollama can't block the voice thread forever
            r = requests.post(chat_url, json=payload, stream=True, timeout=(5, 120))
            output = []
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    obj = json.loads(line.decode())
                    if 'message' in obj and 'content' in obj['message']:
                        token = obj['message']['content']
                        output.append(token)
                    elif 'response' in obj:
                        token = obj.get("response", "")
                        output.append(token)
                except:
                    continue
            return " ".join(output).strip()

        except Exception as e:
            print(f"{Colors.RED}[OLLAMA] Image analysis failed: {e}{Colors.END}")
            return "Sorry, I couldn't analyze the image right now."
    else:
        # Text-only mode (original functionality)
        update_robot_status("current_model", model)
        payload = {"model": model, "prompt": prompt, "system": system_prompt, "stream": True}
        # (connect timeout, read timeout) so a hung Ollama can't block the voice thread forever
        r = requests.post(url, json=payload, stream=True, timeout=(5, 120))
        output = []
        for line in r.iter_lines():
            if not line:
                continue
            try:
                obj = json.loads(line.decode())
                token = obj.get("response") or obj.get("text", "")
            except:
                token = line.decode()
            output.append(token)
        return " ".join(output).strip()

def _phrase_in(phrase, text):
    """Whole-word/phrase match so ordinary conversation doesn't falsely trigger
    motor commands. e.g. 'welcome'/'become' must NOT match 'come', and
    'background' must NOT match 'back'."""
    return re.search(r'(?<!\w)' + re.escape(phrase) + r'(?!\w)', text) is not None

def check_robot_command(text, current_speed=SPEED):
    t = text.lower()

    # Image detection commands - CHECK FIRST (before greetings)
    image_commands = [
        "what do you see", "describe image", "take a picture", "look around",
        "what's in front of you", "analyze image", "see image", "show me",
        "what is this", "identify this", "tell me about this"
    ]
    if any(_phrase_in(cmd, t) for cmd in image_commands):
        return "IMAGE_DETECTION"

    # Greeting commands - robot giggles happily (delayed to sync with voice)!
    greeting_words = ["hello", "hi", "hey", "good morning", "good afternoon", 
                      "good evening", "howdy", "greetings", "what's up", "whats up",
                      "yo", "hola", "namaste", "sup"]
    if any(_phrase_in(greet, t) for greet in greeting_words):
        # Schedule giggle to happen after AI processes and voice starts
        def delayed_giggle():
            time.sleep(2.5)  # Wait for AI to process and voice to start playing
            update_robot_status("eye_state", "happy")
            update_robot_status("status", "giggling")
            giggle()
            update_robot_status("eye_state", "normal")
            update_robot_status("status", "ready")
        threading.Thread(target=delayed_giggle, daemon=True).start()
        return None  # Let AI respond to the greeting

    # Autonomous roam / explore mode
    roam_on_words = ["roam", "explore", "wander", "autonomous", "drive around",
                     "auto mode", "patrol", "go explore", "start roaming", "explore around"]
    if any(_phrase_in(w, t) for w in roam_on_words):
        set_roam(True)
        return "Okay, exploring on my own!"

    roam_off_words = ["stop roaming", "stop exploring", "manual mode", "come back", "stop roam"]
    if any(_phrase_in(w, t) for w in roam_off_words):
        set_roam(False)
        return "Okay, stopping."

    # Expressive emotes (personality gestures)
    if (_phrase_in("dance", t) or _phrase_in("celebrate", t) or _phrase_in("party", t)
            or _phrase_in("do a spin", t) or _phrase_in("spin around", t) or _phrase_in("twirl", t)):
        stop_roam_for_manual()
        happy_dance(0.5)
        return "Woohoo!"

    if _phrase_in("nod", t) or _phrase_in("say yes", t) or _phrase_in("agree", t):
        stop_roam_for_manual()
        nod_yes(current_speed)
        return "Yes!"

    if _phrase_in("shake your head", t) or _phrase_in("say no", t) or _phrase_in("disagree", t):
        stop_roam_for_manual()
        shake_no(current_speed)
        return "No!"

    if _phrase_in("wiggle", t) or _phrase_in("wobble", t) or _phrase_in("be curious", t):
        stop_roam_for_manual()
        curious_wiggle(current_speed)
        return "Hehe!"

    # Forward movement commands
    forward_synonyms = ["forward", "go ahead", "move forward", "go forward", "straight",
                       "ahead", "proceed", "advance", "go straight", "move ahead",
                       "come", "come here", "come forward", "come to me", "come closer"]
    if any(_phrase_in(word, t) for word in forward_synonyms):
        stop_roam_for_manual()
        update_robot_status("eye_state", "forward")
        update_robot_status("status", "moving forward")
        set_both_forward(current_speed)
        return "Moving forward"

    # Backward movement commands
    backward_synonyms = ["back", "reverse", "backward", "move back", "go back",
                        "retreat", "back up", "go backward", "move backward", "reverse direction"]
    if any(_phrase_in(word, t) for word in backward_synonyms):
        stop_roam_for_manual()
        update_robot_status("eye_state", "backward")
        update_robot_status("status", "moving backward")
        set_both_backward(current_speed)
        return "Moving backward"

    # Left turn commands
    left_synonyms = ["left", "turn left", "go left", "spin left", "rotate left",
                    "veer left", "turn to the left", "go leftward", "head left", "pivot left"]
    if any(_phrase_in(phrase, t) for phrase in left_synonyms):
        stop_roam_for_manual()
        update_robot_status("eye_state", "left")
        update_robot_status("status", "spinning left")
        spin_left(current_speed)
        return "Spinning left"

    # Right turn commands
    right_synonyms = ["right", "turn right", "go right", "spin right", "rotate right",
                     "veer right", "turn to the right", "go rightward", "head right", "pivot right"]
    if any(_phrase_in(phrase, t) for phrase in right_synonyms):
        stop_roam_for_manual()
        update_robot_status("eye_state", "right")
        update_robot_status("status", "spinning right")
        spin_right(current_speed)
        return "Spinning right"

    # Stop commands
    stop_synonyms = ["stop", "halt", "freeze", "quit moving", "cease", "pause",
                    "hold", "stand still", "stay put", "don't move"]
    if any(_phrase_in(word, t) for word in stop_synonyms):
        set_roam(False)
        update_robot_status("eye_state", "sleeping")
        update_robot_status("status", "stopped")
        stop_all()
        return "Stopped"

    if _phrase_in("faster", t) or _phrase_in("speed up", t):
        return "SPEED_UP"

    if _phrase_in("slower", t) or _phrase_in("slow down", t):
        return "SPEED_DOWN"

    if _phrase_in("quit", t) or _phrase_in("exit", t):
        print(f"{Colors.RED}Voice command: Exiting...{Colors.END}")
        stop_all()
        # sys.exit() only kills this daemon thread. Raise SIGINT so the main
        # thread's KeyboardInterrupt handler runs the clean shutdown/finally.
        os.kill(os.getpid(), signal.SIGINT)
        return None

    return None

# Movement functions
def set_both_forward(speed=SPEED):
    movement_cancel_event.clear()
    obstacle, dist = check_front_obstacle()
    if obstacle:
        update_robot_status("eye_state", "surprised")
        update_robot_status("status", "obstacle detected")
        update_robot_status("obstacle", f"{dist}cm")
        stop_all()
        print(f"{Colors.RED}[OBSTACLE] Front obstacle detected at {dist}cm - BLOCKED{Colors.END}")
        return
    update_robot_status("obstacle", "clear")
    left_motor_forward(speed)
    right_motor_forward(speed)
    start = time.time()
    while time.time() - start < 1.0:  # Move for 1.0 seconds
        if movement_cancel_event.is_set():
            update_robot_status("eye_state", "sleeping")
            update_robot_status("status", "stopped")
            break
        obstacle, dist = check_front_obstacle()
        if obstacle:
            update_robot_status("eye_state", "surprised")
            update_robot_status("status", "emergency stop")
            update_robot_status("obstacle", f"{dist}cm")
            stop_all()
            print(f"{Colors.RED}[OBSTACLE] Front obstacle detected at {dist}cm - STOPPED{Colors.END}")
            return
        time.sleep(0.05)
    update_robot_status("eye_state", "normal")
    update_robot_status("status", "stopped")
    stop_all()

def set_both_backward(speed=SPEED):
    movement_cancel_event.clear()
    obstacle, dist = check_back_obstacle()
    if obstacle:
        update_robot_status("eye_state", "surprised")
        update_robot_status("status", "obstacle detected")
        update_robot_status("obstacle", f"{dist}cm")
        stop_all()
        print(f"{Colors.RED}[OBSTACLE] Back obstacle detected at {dist}cm - BLOCKED{Colors.END}")
        return
    update_robot_status("obstacle", "clear")
    left_motor_backward(speed)
    right_motor_backward(speed)
    start = time.time()
    while time.time() - start < 1.5:  # Move for 1.5 seconds
        if movement_cancel_event.is_set():
            update_robot_status("eye_state", "sleeping")
            update_robot_status("status", "stopped")
            break
        obstacle, dist = check_back_obstacle()
        if obstacle:
            update_robot_status("eye_state", "surprised")
            update_robot_status("status", "emergency stop")
            update_robot_status("obstacle", f"{dist}cm")
            stop_all()
            print(f"{Colors.RED}[OBSTACLE] Back obstacle detected at {dist}cm - STOPPED{Colors.END}")
            return
        time.sleep(0.05)
    update_robot_status("eye_state", "normal")
    update_robot_status("status", "stopped")
    stop_all()

def spin_left(speed=SPEED):
    movement_cancel_event.clear()
    left_motor_backward(speed)
    right_motor_forward(speed)
    start = time.time()
    while time.time() - start < 0.5:
        if movement_cancel_event.is_set():
            break
        time.sleep(0.05)
    stop_all()

def spin_right(speed=SPEED):
    movement_cancel_event.clear()
    left_motor_forward(speed)
    right_motor_backward(speed)
    start = time.time()
    while time.time() - start < 0.5:
        if movement_cancel_event.is_set():
            break
        time.sleep(0.05)
    stop_all()

def giggle(speed=0.4):
    """Make the robot wiggle in place - a happy greeting gesture!"""
    # Quick alternating left-right wiggles that cancel out movement
    for _ in range(2):  # Reduced from 4 to 2 wiggles
        # Wiggle left
        left_motor_backward(speed)
        right_motor_forward(speed)
        time.sleep(0.06)
        stop_all()
        time.sleep(0.02)
        # Wiggle right
        left_motor_forward(speed)
        right_motor_backward(speed)
        time.sleep(0.06)
        stop_all()
        time.sleep(0.02)
    stop_all()

def stop_all():
    # Signal any ongoing movement loops to abort
    movement_cancel_event.set()
    left_motor_stop()
    right_motor_stop()

# ============================================================
# EXPRESSIVE EMOTES - personality gestures tied to the eyes
# ============================================================
def nod_yes(speed=0.45):
    """Nod 'yes' with gentle forward/back bobs."""
    update_robot_status("eye_state", "happy")
    update_robot_status("status", "nodding yes")
    for _ in range(2):
        left_motor_forward(speed); right_motor_forward(speed)
        time.sleep(0.13); all_stop(); time.sleep(0.05)
        left_motor_backward(speed); right_motor_backward(speed)
        time.sleep(0.13); all_stop(); time.sleep(0.05)
    all_stop()
    update_robot_status("eye_state", "normal")

def shake_no(speed=0.45):
    """Shake 'no' with quick left/right head-shakes."""
    update_robot_status("eye_state", "surprised")
    update_robot_status("status", "shaking no")
    for _ in range(2):
        left_motor_backward(speed); right_motor_forward(speed)
        time.sleep(0.13); all_stop(); time.sleep(0.04)
        left_motor_forward(speed); right_motor_backward(speed)
        time.sleep(0.13); all_stop(); time.sleep(0.04)
    all_stop()
    update_robot_status("eye_state", "normal")

def happy_dance(speed=0.5):
    """Celebratory spin-and-wiggle dance."""
    update_robot_status("eye_state", "happy")
    update_robot_status("status", "dancing")
    left_motor_forward(speed); right_motor_backward(speed); time.sleep(0.55)
    all_stop(); time.sleep(0.05)
    left_motor_backward(speed); right_motor_forward(speed); time.sleep(0.55)
    all_stop(); time.sleep(0.05)
    giggle(speed)
    update_robot_status("eye_state", "normal")
    update_robot_status("status", "ready")

def curious_wiggle(speed=0.4):
    """A small curious tilt/wiggle."""
    update_robot_status("eye_state", "curious")
    update_robot_status("status", "curious")
    left_motor_forward(speed); right_motor_backward(speed); time.sleep(0.12)
    all_stop(); time.sleep(0.05)
    left_motor_backward(speed); right_motor_forward(speed); time.sleep(0.12)
    all_stop()
    update_robot_status("eye_state", "normal")

# ============================================================
# AUTONOMOUS ROAM MODE - wander + ultrasonic obstacle avoidance
# ============================================================
roam_enabled = False
roam_lock = threading.Lock()

def set_roam(state):
    """Enable/disable autonomous roam mode."""
    global roam_enabled
    with roam_lock:
        roam_enabled = state
    update_robot_status("roam_enabled", state)
    if state:
        update_robot_status("status", "roaming")
        update_robot_status("eye_state", "forward")
        print(f"{Colors.GREEN}[ROAM] Autonomous roam ENABLED{Colors.END}")
    else:
        all_stop()
        update_robot_status("eye_state", "normal")
        update_robot_status("status", "stopped")
        print(f"{Colors.YELLOW}[ROAM] Autonomous roam DISABLED{Colors.END}")

def stop_roam_for_manual():
    """Turn roam off when the user takes manual control, so they don't fight."""
    with roam_lock:
        was_on = roam_enabled
    if was_on:
        set_roam(False)

def roam_thread_func():
    """Drive around autonomously, avoiding obstacles with the ultrasonic sensors."""
    global keyboard_running
    print(f"{Colors.GREEN}[ROAM] Roam thread ready (toggle with 'R' or say 'explore'){Colors.END}")
    while keyboard_running:
        with roam_lock:
            active = roam_enabled
        if not active:
            time.sleep(0.15)
            continue

        with speed_lock:
            spd = shared_speed

        front, dist = check_front_obstacle()
        if front:
            # Blocked: react, back off a little, then turn to find a clear path
            update_robot_status("eye_state", "surprised")
            update_robot_status("status", "roam: obstacle")
            update_robot_status("obstacle", f"{dist}cm")
            all_stop()
            time.sleep(0.2)

            back, _ = check_back_obstacle()
            if not back:
                left_motor_backward(spd); right_motor_backward(spd)
                time.sleep(0.4); all_stop()

            # Turn a random amount/direction to escape corners
            turn_time = 0.4 + random.random() * 0.5
            if random.random() < 0.5:
                update_robot_status("eye_state", "left")
                left_motor_backward(spd); right_motor_forward(spd)
            else:
                update_robot_status("eye_state", "right")
                left_motor_forward(spd); right_motor_backward(spd)
            t0 = time.time()
            while time.time() - t0 < turn_time and keyboard_running:
                with roam_lock:
                    if not roam_enabled:
                        break
                time.sleep(0.05)
            all_stop()
        else:
            # Clear ahead: cruise forward, re-checking the front sensor often
            update_robot_status("eye_state", "forward")
            update_robot_status("status", "roaming")
            update_robot_status("obstacle", "clear")
            left_motor_forward(spd); right_motor_forward(spd)
            t0 = time.time()
            while time.time() - t0 < 0.4 and keyboard_running:
                with roam_lock:
                    if not roam_enabled:
                        break
                blocked, _ = check_front_obstacle()
                if blocked:
                    all_stop()
                    break
                time.sleep(0.05)
        time.sleep(0.02)
    all_stop()

# ============================================================
# OBSTACLE MONITOR - continuously report obstacles to the UI
# ============================================================
def obstacle_monitor_thread_func():
    """Poll both ultrasonic sensors and reflect obstacles in the interface,
    even when the robot is sitting idle."""
    global keyboard_running
    if ultrasonic_handle is None:
        print(f"{Colors.YELLOW}[OBSTACLE] No ultrasonic sensors - monitor disabled{Colors.END}")
        return
    print(f"{Colors.GREEN}[OBSTACLE] Live obstacle monitor started{Colors.END}")
    while keyboard_running:
        try:
            front = measure_distance(SENSOR2_TRIG, SENSOR2_ECHO)
            back = measure_distance(SENSOR1_TRIG, SENSOR1_ECHO)
            parts = []
            if front is not None and front < OBSTACLE_THRESHOLD:
                parts.append(f"Front {front:.0f}cm")
            if back is not None and back < OBSTACLE_THRESHOLD:
                parts.append(f"Back {back:.0f}cm")
            if parts:
                update_robot_status("obstacle", " | ".join(parts))
                update_robot_status("obstacle_alert", True)
            else:
                update_robot_status("obstacle", "clear")
                update_robot_status("obstacle_alert", False)
        except Exception:
            pass
        time.sleep(0.25)

# ============================================================
# WEB / TOUCHSCREEN KEYBOARD CONTROL
# Lets the browser interface drive the robot when IT has focus
# (the terminal keys only work when the terminal is focused).
# ============================================================
web_drive_lock = threading.Lock()
web_drive_active = False       # True while a hold-to-move command is running
web_drive_last = [0.0]         # timestamp of the most recent drive tick

def _apply_drive(action, speed):
    """Set motors for a continuous (held) drive action. Returns True if moving."""
    if action == "forward":
        blocked, dist = check_front_obstacle()
        if blocked:
            stop_all()
            update_robot_status("eye_state", "surprised")
            update_robot_status("status", "obstacle - blocked")
            return False
        left_motor_forward(speed); right_motor_forward(speed)
        update_robot_status("eye_state", "forward")
        update_robot_status("status", "moving forward")
    elif action == "backward":
        blocked, dist = check_back_obstacle()
        if blocked:
            stop_all()
            update_robot_status("eye_state", "surprised")
            update_robot_status("status", "obstacle - blocked")
            return False
        left_motor_backward(speed); right_motor_backward(speed)
        update_robot_status("eye_state", "backward")
        update_robot_status("status", "moving backward")
    elif action == "left":
        left_motor_backward(speed); right_motor_forward(speed)
        update_robot_status("eye_state", "left")
        update_robot_status("status", "spinning left")
    elif action == "right":
        left_motor_forward(speed); right_motor_backward(speed)
        update_robot_status("eye_state", "right")
        update_robot_status("status", "spinning right")
    return True

def handle_web_control(action):
    """Execute a command sent from the browser interface."""
    global web_drive_active, shared_speed
    if action in ("forward", "backward", "left", "right"):
        stop_roam_for_manual()
        with speed_lock:
            spd = shared_speed
        _apply_drive(action, spd)
        with web_drive_lock:
            web_drive_active = True
            web_drive_last[0] = time.time()
    elif action == "stop":
        set_roam(False)
        with web_drive_lock:
            web_drive_active = False
        stop_all()
        update_robot_status("eye_state", "sleeping")
        update_robot_status("status", "stopped")
    elif action == "roam_toggle":
        with roam_lock:
            currently = roam_enabled
        set_roam(not currently)
    elif action == "speed_up":
        with speed_lock:
            shared_speed = clamp(shared_speed + 0.1)
            update_robot_status("speed", round(shared_speed, 2))
    elif action == "speed_down":
        with speed_lock:
            shared_speed = clamp(shared_speed - 0.1)
            update_robot_status("speed", round(shared_speed, 2))

def web_drive_watchdog_func():
    """Safety net: if the browser stops sending 'keep moving' ticks (key released,
    focus lost, tab closed), stop the motors so the robot never runs away."""
    global web_drive_active, keyboard_running
    while keyboard_running:
        with web_drive_lock:
            active = web_drive_active
            last = web_drive_last[0]
        if active and (time.time() - last) > 0.6:
            stop_all()
            with web_drive_lock:
                web_drive_active = False
            update_robot_status("eye_state", "normal")
            update_robot_status("status", "stopped")
        time.sleep(0.15)

# ============================================================
# WAKE WORD + CONVERSATION MEMORY
# ============================================================
WAKE_WORDS = ["buddy", "hey buddy", "ok buddy", "hey robot", "okay buddy"]
WAKE_TIMEOUT = 15.0          # stay "awake" this many seconds after being addressed
wake_word_required = True     # toggle with 'K'; when False, always listens
_last_awake_time = [0.0]      # list wrapper so nested funcs can mutate it
conversation_history = collections.deque(maxlen=4)  # recent (user, buddy) turns

def strip_wake_word(text):
    """Return (had_wake_word, remaining_text_without_wake_word)."""
    t = text.lower().strip()
    for w in sorted(WAKE_WORDS, key=len, reverse=True):
        if _phrase_in(w, t):
            remaining = re.sub(r'(?<!\w)' + re.escape(w) + r'(?!\w)', ' ', t).strip()
            remaining = re.sub(r'\s+', ' ', remaining)
            return True, remaining
    return False, t

def build_prompt_with_memory(user_text):
    """Prepend recent conversation turns so follow-up questions have context."""
    if not conversation_history:
        return user_text
    lines = []
    for u, b in conversation_history:
        lines.append(f"User: {u}")
        lines.append(f"Buddy: {b}")
    lines.append(f"User: {user_text}")
    return "Previous conversation:\n" + "\n".join(lines)

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

# Terminal helpers
def getch_blocking():
    """Read a single character (blocking)"""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def getch(timeout=0.05):
    """Return a single character from stdin or None if timeout."""
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        rlist, _, _ = select.select([fd], [], [], timeout)
        if rlist:
            ch = sys.stdin.read(1)
            return ch
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def print_instructions():
    print(f"\n{Colors.BOLD}{Colors.GREEN}ROBOT CONTROL INTERFACE{Colors.END}")
    print(f"{Colors.CYAN}{'='*50}{Colors.END}")
    print(f"{Colors.BOLD}Keyboard:{Colors.END} W=Forward S=Backward A=Left D=Right Space=Stop")
    print(f"{Colors.BOLD}Gamepad:{Colors.END} LT=Forward RT=Backward LeftStick=Steer")
    print(f"{Colors.BOLD}Gesture:{Colors.END} Open Palm=Stop, 1 Finger=Fwd, 2=Back, Thumb=Turn")
    print(f"{Colors.BOLD}Speed:{Colors.END} +/- to adjust, 1-9 presets")
    print(f"{Colors.BOLD}Autonomy:{Colors.END} R=Toggle Roam (auto-explore + obstacle avoid)")
    print(f"{Colors.BOLD}Voice:{Colors.END} K=Toggle wake word ('Hey Buddy')")
    print(f"{Colors.BOLD}System:{Colors.END} H=Help G=Toggle Gesture Q=Quit")
    print(f"{Colors.CYAN}{'='*50}{Colors.END}")
    print(f"Starting speed: {SPEED}\n")

# Global flag for keyboard thread
keyboard_running = True
current_key = None
key_lock = threading.Lock()

# Movement cancellation flag (used for immediate stops)
movement_cancel_event = threading.Event()

def keyboard_thread_func():
    global current_key, keyboard_running
    while keyboard_running:
        ch = getch(timeout=0.05)
        if ch:
            with key_lock:
                current_key = ch
        time.sleep(0.01)

def dz(v):
    return 0 if abs(v) < GAMEPAD_DEADZONE else v

def gamepad_thread_func():
    global keyboard_running, shared_speed
    
    pygame.init()
    pygame.joystick.init()
    
    if pygame.joystick.get_count() == 0:
        print(f"{Colors.YELLOW}[GAMEPAD] No gamepad detected{Colors.END}")
        return
    
    js = pygame.joystick.Joystick(0)
    js.init()
    print(f"{Colors.GREEN}[GAMEPAD] Connected: {js.get_name()}{Colors.END}")
    
    clock = pygame.time.Clock()
    
    while keyboard_running:
        try:
            pygame.event.pump()
            
            lx = js.get_axis(AXIS_LX)
            rt = js.get_axis(AXIS_RT)
            lt = js.get_axis(AXIS_LT)
            
            if rt < 0: rt = (rt + 1) / 2
            if lt < 0: lt = (lt + 1) / 2
            
            lx = dz(lx)
            
            with speed_lock:
                max_spd = min(shared_speed + 0.2, GAMEPAD_MAX_SPEED)
            
            if rt > 0.2 and lt > 0.2:
                # Both triggers pressed = emergency stop
                stop_all()
                clock.tick(30)
                continue

            if lt > 0.1:
                # Left trigger = forward
                speed = lt * max_spd

                # Only check obstacles when moving straight forward (not while turning)
                if lx == 0:
                    obstacle, dist = check_front_obstacle()
                    if obstacle:
                        update_robot_status("eye_state", "surprised")
                        update_robot_status("status", "obstacle detected")
                        update_robot_status("obstacle", f"{dist}cm")
                        stop_all()
                        print(f"{Colors.RED}[GAMEPAD] Front obstacle at {dist}cm{Colors.END}")
                        clock.tick(30)
                        continue
                if lx > 0.2:
                    left_motor_backward(speed)
                    right_motor_forward(speed)
                elif lx < -0.2:
                    left_motor_forward(speed)
                    right_motor_backward(speed)
                else:
                    left_motor_forward(speed)
                    right_motor_forward(speed)
            
            elif rt > 0.1:
                speed = rt * max_spd

                # Only check obstacles when moving straight backward, not when turning
                if lx == 0:  # Only check obstacles when moving straight backward
                    obstacle, dist = check_back_obstacle()
                    if obstacle:
                        update_robot_status("eye_state", "surprised")
                        update_robot_status("status", "obstacle detected")
                        update_robot_status("obstacle", f"{dist}cm")
                        stop_all()
                        print(f"{Colors.RED}[GAMEPAD] Back obstacle at {dist}cm{Colors.END}")
                        clock.tick(30)
                        continue
                if lx > 0.2:
                    left_motor_forward(speed)
                    right_motor_backward(speed)
                elif lx < -0.2:
                    left_motor_backward(speed)
                    right_motor_forward(speed)
                else:
                    left_motor_backward(speed)
                    right_motor_backward(speed)
            
            else:
                stop_all()
            
            clock.tick(30)
        except Exception as e:
            print(f"{Colors.RED}[GAMEPAD] Error: {e}{Colors.END}")
            time.sleep(0.5)
    
    pygame.quit()

# Hand Gesture Control
gesture_enabled = False
gesture_lock = threading.Lock()

# Video streaming for web UI
video_frame_buffer = None
video_frame_lock = threading.Lock()
video_streaming_enabled = False

class HandGestureController:
    """Hand gesture recognition using MediaPipe for robot control"""
    
    # Gesture types
    GESTURE_NONE = "none"
    GESTURE_STOP = "stop"           # Open palm (5 fingers)
    GESTURE_FORWARD = "forward"     # Index finger pointing up
    GESTURE_BACKWARD = "backward"   # Peace sign (2 fingers)
    GESTURE_LEFT = "left"           # Thumb pointing left
    GESTURE_RIGHT = "right"         # Thumb pointing right
    GESTURE_FIST = "fist"           # Closed fist - emergency stop
    
    def __init__(self, camera_index=0):
        if not GESTURE_AVAILABLE:
            raise RuntimeError("OpenCV and MediaPipe are required for gesture control")
        
        self.mp_hands = mp.solutions.hands
        self.mp_draw = mp.solutions.drawing_utils
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5
        )
        self.camera_index = camera_index
        self.cap = None
        self.last_gesture = self.GESTURE_NONE
        self.gesture_hold_time = 0.3  # seconds to hold gesture before action
        self.last_gesture_time = 0
        self.current_gesture_start = 0
        
    def start_camera(self):
        """Initialize camera capture"""
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            # Try alternative camera indices
            for idx in [0, 1, 2, -1]:
                self.cap = cv2.VideoCapture(idx)
                if self.cap.isOpened():
                    print(f"{Colors.GREEN}[GESTURE] Camera opened at index {idx}{Colors.END}")
                    break
        
        if not self.cap.isOpened():
            raise RuntimeError("Could not open camera for gesture control")
        
        # Set lower resolution for faster processing
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        
        print(f"{Colors.GREEN}[GESTURE] Camera initialized{Colors.END}")
        return True
    
    def stop_camera(self):
        """Release camera"""
        if self.cap:
            self.cap.release()
            self.cap = None
    
    def count_fingers(self, hand_landmarks, handedness):
        """Count extended fingers and return gesture"""
        tips = [4, 8, 12, 16, 20]  # Thumb, Index, Middle, Ring, Pinky tips
        pip = [3, 6, 10, 14, 18]   # PIP joints (for comparison)
        
        fingers = []
        
        # Get hand type (Left or Right)
        hand_type = handedness.classification[0].label
        
        # Thumb - check horizontal position relative to palm
        thumb_tip = hand_landmarks.landmark[tips[0]]
        thumb_ip = hand_landmarks.landmark[pip[0]]
        thumb_mcp = hand_landmarks.landmark[2]
        
        # For thumb, check if it's extended outward
        if hand_type == "Right":
            thumb_extended = thumb_tip.x < thumb_ip.x
        else:
            thumb_extended = thumb_tip.x > thumb_ip.x
        fingers.append(thumb_extended)
        
        # Other fingers - check if tip is above PIP joint (in y-coordinates, lower y = higher position)
        for i in range(1, 5):
            tip_y = hand_landmarks.landmark[tips[i]].y
            pip_y = hand_landmarks.landmark[pip[i]].y
            fingers.append(tip_y < pip_y)
        
        finger_count = sum(fingers)
        
        # Determine gesture based on finger configuration
        thumb, index, middle, ring, pinky = fingers
        
        # Open palm - all 5 fingers extended (STOP)
        if finger_count == 5:
            return self.GESTURE_STOP, finger_count
        
        # Closed fist - no fingers extended (EMERGENCY STOP)
        if finger_count == 0:
            return self.GESTURE_FIST, finger_count
        
        # Index finger only (FORWARD)
        if index and not middle and not ring and not pinky:
            return self.GESTURE_FORWARD, finger_count
        
        # Peace sign - index and middle (BACKWARD)
        if index and middle and not ring and not pinky and not thumb:
            return self.GESTURE_BACKWARD, finger_count
        
        # Thumb only extended - check direction for LEFT/RIGHT
        if thumb and not index and not middle and not ring and not pinky:
            # Check thumb horizontal position relative to wrist
            wrist = hand_landmarks.landmark[0]
            if hand_type == "Right":
                if thumb_tip.x < wrist.x - 0.1:
                    return self.GESTURE_LEFT, finger_count
                else:
                    return self.GESTURE_RIGHT, finger_count
            else:
                if thumb_tip.x > wrist.x + 0.1:
                    return self.GESTURE_RIGHT, finger_count
                else:
                    return self.GESTURE_LEFT, finger_count
        
        return self.GESTURE_NONE, finger_count
    
    def process_frame(self):
        """Process a single frame and return detected gesture"""
        if not self.cap or not self.cap.isOpened():
            return None, None
        
        ret, frame = self.cap.read()
        if not ret:
            return None, None
        
        # Flip frame horizontally for mirror effect
        frame = cv2.flip(frame, 1)
        
        # Convert to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self.hands.process(rgb_frame)
        
        gesture = self.GESTURE_NONE
        finger_count = 0
        
        if results.multi_hand_landmarks and results.multi_handedness:
            for hand_landmarks, handedness in zip(results.multi_hand_landmarks, results.multi_handedness):
                # Draw hand landmarks on frame
                self.mp_draw.draw_landmarks(
                    frame, hand_landmarks, self.mp_hands.HAND_CONNECTIONS,
                    self.mp_draw.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=2),
                    self.mp_draw.DrawingSpec(color=(255, 0, 0), thickness=2)
                )
                
                # Detect gesture
                gesture, finger_count = self.count_fingers(hand_landmarks, handedness)
        
        # Add gesture text to frame
        gesture_text = f"Gesture: {gesture.upper()} ({finger_count} fingers)"
        cv2.putText(frame, gesture_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 
                    1, (0, 255, 0), 2, cv2.LINE_AA)
        
        # Add instructions
        cv2.putText(frame, "Open Palm=Stop | 1 Finger=Forward | 2 Fingers=Back", 
                    (10, frame.shape[0] - 40), cv2.FONT_HERSHEY_SIMPLEX, 
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, "Thumb=Turn | Fist=Emergency Stop | Q=Quit", 
                    (10, frame.shape[0] - 15), cv2.FONT_HERSHEY_SIMPLEX, 
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)
        
        return gesture, frame
    
    def get_confirmed_gesture(self, gesture):
        """Return gesture only if held for sufficient time"""
        current_time = time.time()
        
        if gesture != self.last_gesture:
            self.last_gesture = gesture
            self.current_gesture_start = current_time
            return self.GESTURE_NONE
        
        # Check if gesture has been held long enough
        if current_time - self.current_gesture_start >= self.gesture_hold_time:
            if current_time - self.last_gesture_time >= 0.5:  # Debounce
                self.last_gesture_time = current_time
                return gesture
        
        return self.GESTURE_NONE
    
    def cleanup(self):
        """Clean up resources"""
        self.stop_camera()
        if self.hands:
            self.hands.close()


def gesture_thread_func(camera_index=0, show_window=True):
    """Thread function for hand gesture control with web streaming"""
    global keyboard_running, shared_speed, gesture_enabled, video_frame_buffer, video_frame_lock, video_streaming_enabled
    
    if not GESTURE_AVAILABLE:
        print(f"{Colors.RED}[GESTURE] OpenCV/MediaPipe not available{Colors.END}")
        return
    
    try:
        controller = HandGestureController(camera_index)
        controller.start_camera()
        video_streaming_enabled = True
        update_robot_status("video_streaming", True)
    except Exception as e:
        print(f"{Colors.RED}[GESTURE] Failed to initialize: {e}{Colors.END}")
        return
    
    print(f"{Colors.GREEN}[GESTURE] Hand gesture control started{Colors.END}")
    print(f"{Colors.CYAN}[GESTURE] Press 'G' to toggle gesture control on/off{Colors.END}")
    print(f"{Colors.GREEN}[GESTURE] Video streaming enabled for web UI{Colors.END}")
    
    last_action = None
    action_cooldown = 0.8  # seconds between actions
    last_action_time = 0
    
    while keyboard_running:
        try:
            with gesture_lock:
                is_enabled = gesture_enabled
            
            gesture, frame = controller.process_frame()
            
            if frame is not None:
                # Show enabled/disabled status
                status_text = "GESTURE CONTROL: ON" if is_enabled else "GESTURE CONTROL: OFF (Press G)"
                color = (0, 255, 0) if is_enabled else (100, 100, 100)
                cv2.putText(frame, status_text, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 
                            0.7, color, 2, cv2.LINE_AA)
                
                # Encode frame to JPEG for web streaming
                _, jpeg_buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                with video_frame_lock:
                    video_frame_buffer = jpeg_buffer.tobytes()
                
                # Show local window if enabled
                if show_window:
                    cv2.imshow('Robot Gesture Control', frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord('q'):
                        break
            
            if not is_enabled:
                time.sleep(0.033)  # Still update frames at ~30fps for streaming
                continue
            
            if gesture is None:
                continue
            
            # Get confirmed gesture (held for minimum time)
            confirmed_gesture = controller.get_confirmed_gesture(gesture)
            
            if confirmed_gesture == controller.GESTURE_NONE:
                continue
            
            current_time = time.time()
            if current_time - last_action_time < action_cooldown:
                continue
            
            with speed_lock:
                current_speed = shared_speed
            
            # Execute action based on gesture
            if confirmed_gesture == controller.GESTURE_STOP:
                if last_action != "stop":
                    update_robot_status("eye_state", "sleeping")
                    update_robot_status("status", "stopped (gesture)")
                    stop_all()
                    last_action = "stop"
                    last_action_time = current_time
                    print(f"{Colors.YELLOW}[GESTURE] ✋ Open Palm → STOP{Colors.END}")
            
            elif confirmed_gesture == controller.GESTURE_FIST:
                update_robot_status("eye_state", "surprised")
                update_robot_status("status", "emergency stop")
                stop_all()
                last_action = "emergency_stop"
                last_action_time = current_time
                print(f"{Colors.RED}[GESTURE] ✊ Fist → EMERGENCY STOP{Colors.END}")
            
            elif confirmed_gesture == controller.GESTURE_FORWARD:
                update_robot_status("eye_state", "forward")
                update_robot_status("status", "moving forward (gesture)")
                set_both_forward(current_speed)
                last_action = "forward"
                last_action_time = current_time
                print(f"{Colors.GREEN}[GESTURE] ☝️ Index → FORWARD{Colors.END}")
            
            elif confirmed_gesture == controller.GESTURE_BACKWARD:
                update_robot_status("eye_state", "backward")
                update_robot_status("status", "moving backward (gesture)")
                set_both_backward(current_speed)
                last_action = "backward"
                last_action_time = current_time
                print(f"{Colors.GREEN}[GESTURE] ✌️ Peace → BACKWARD{Colors.END}")
            
            elif confirmed_gesture == controller.GESTURE_LEFT:
                update_robot_status("eye_state", "left")
                update_robot_status("status", "spinning left (gesture)")
                spin_left(current_speed)
                last_action = "left"
                last_action_time = current_time
                print(f"{Colors.GREEN}[GESTURE] 👍← Thumb Left → SPIN LEFT{Colors.END}")
            
            elif confirmed_gesture == controller.GESTURE_RIGHT:
                update_robot_status("eye_state", "right")
                update_robot_status("status", "spinning right (gesture)")
                spin_right(current_speed)
                last_action = "right"
                last_action_time = current_time
                print(f"{Colors.GREEN}[GESTURE] 👍→ Thumb Right → SPIN RIGHT{Colors.END}")
            
        except Exception as e:
            print(f"{Colors.RED}[GESTURE] Error: {e}{Colors.END}")
            time.sleep(0.5)
    
    video_streaming_enabled = False
    update_robot_status("video_streaming", False)
    controller.cleanup()
    cv2.destroyAllWindows()
    print(f"{Colors.YELLOW}[GESTURE] Hand gesture control stopped{Colors.END}")


def video_streaming_thread_func(camera_index=0):
    """Thread function for video streaming to web UI (without gesture control)
    
    This runs when gesture control is not available but camera streaming is wanted.
    """
    global keyboard_running, video_frame_buffer, video_frame_lock, video_streaming_enabled
    
    if not GESTURE_AVAILABLE:
        print(f"{Colors.YELLOW}[VIDEO] OpenCV not available for video streaming{Colors.END}")
        return
    
    try:
        cap = cv2.VideoCapture(camera_index)
        if not cap.isOpened():
            for idx in [0, 1, 2, -1]:
                cap = cv2.VideoCapture(idx)
                if cap.isOpened():
                    print(f"{Colors.GREEN}[VIDEO] Camera opened at index {idx}{Colors.END}")
                    break
        
        if not cap.isOpened():
            print(f"{Colors.RED}[VIDEO] Could not open camera for streaming{Colors.END}")
            return
        
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        video_streaming_enabled = True
        update_robot_status("video_streaming", True)
        print(f"{Colors.GREEN}[VIDEO] Camera streaming started for web UI{Colors.END}")
        
    except Exception as e:
        print(f"{Colors.RED}[VIDEO] Failed to initialize camera: {e}{Colors.END}")
        return
    
    while keyboard_running:
        try:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue
            
            # Flip frame for mirror effect
            frame = cv2.flip(frame, 1)
            
            # Add info text
            cv2.putText(frame, "Camera Feed - Press G to enable gesture control", 
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
            
            # Encode frame to JPEG for web streaming
            _, jpeg_buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            with video_frame_lock:
                video_frame_buffer = jpeg_buffer.tobytes()
            
            time.sleep(0.033)  # ~30 FPS
            
        except Exception as e:
            print(f"{Colors.RED}[VIDEO] Streaming error: {e}{Colors.END}")
            time.sleep(0.5)
    
    video_streaming_enabled = False
    update_robot_status("video_streaming", False)
    cap.release()
    print(f"{Colors.YELLOW}[VIDEO] Camera streaming stopped{Colors.END}")


# Global shared speed variable
shared_speed = SPEED
speed_lock = threading.Lock()

# Web UI status tracking
robot_status = {
    "status": "stopped",
    "speed": SPEED,
    "obstacle": "clear",
    "voice": "ready",
    "eye_state": "normal",
    "image_description": "",
    "audio_input": "",
    "audio_output": "",
    "captured_image": "",
    "current_model": DEFAULT_MODEL_NAME,
    "gesture_enabled": False,
    "video_streaming": False,
    "roam_enabled": False,
    "awake": False,
    "wake_required": True,
    "obstacle_alert": False
}
status_lock = threading.Lock()

def main():
    global keyboard_running, current_key, shared_speed, gesture_enabled, wake_word_required
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["voice", "keyboard", "both"], default="both")
    parser.add_argument("--piper-model", default=DEFAULT_PIPER_MODEL)
    parser.add_argument("--piper-config", default=DEFAULT_PIPER_CONFIG)
    parser.add_argument("--vosk", default=DEFAULT_VOSK_MODEL)
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--gesture", action="store_true", help="Enable hand gesture control")
    parser.add_argument("--gesture-camera", type=int, default=0, help="Camera index for gesture control")
    args = parser.parse_args()
    
    init_motors()
    init_ultrasonic()
    init_camera()
    
    tts = None
    mic = None
    voice_enabled = False
    
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}INITIALIZING VOICE COMPONENTS{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")
    
    # Check Piper files
    print(f"{Colors.YELLOW}Checking Piper TTS files...{Colors.END}")
    if not os.path.exists(args.piper_model):
        print(f"{Colors.RED}[ERROR] Piper model not found:{Colors.END}")
        print(f"  Expected: {args.piper_model}")
    else:
        print(f"{Colors.GREEN}[OK] Piper model found: {args.piper_model}{Colors.END}")
    
    if not os.path.exists(args.piper_config):
        print(f"{Colors.RED}[ERROR] Piper config not found:{Colors.END}")
        print(f"  Expected: {args.piper_config}")
    else:
        print(f"{Colors.GREEN}[OK] Piper config found: {args.piper_config}{Colors.END}")
    
    # Check Vosk model
    print(f"\n{Colors.YELLOW}Checking Vosk speech recognition model...{Colors.END}")
    if not os.path.exists(args.vosk):
        print(f"{Colors.RED}[ERROR] Vosk model directory not found:{Colors.END}")
        print(f"  Expected: {args.vosk}")
    else:
        print(f"{Colors.GREEN}[OK] Vosk model found: {args.vosk}{Colors.END}")
    
    # Try to initialize
    if os.path.exists(args.piper_model) and os.path.exists(args.piper_config) and os.path.exists(args.vosk):
        try:
            print(f"\n{Colors.BLUE}[INIT] Loading Piper TTS...{Colors.END}", flush=True)
            tts = PiperTTS(args.piper_model, args.piper_config)
            print(f"{Colors.GREEN}[OK] Piper TTS loaded successfully{Colors.END}", flush=True)
            
            print(f"{Colors.BLUE}[INIT] Loading Vosk speech recognition...{Colors.END}", flush=True)
            mic = MicInput(args.vosk)
            print(f"{Colors.GREEN}[OK] Vosk loaded successfully{Colors.END}", flush=True)
            
            voice_enabled = True
            print(f"\n{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.END}")
            print(f"{Colors.BOLD}{Colors.GREEN}VOICE SYSTEM READY!{Colors.END}")
            print(f"{Colors.BOLD}{Colors.GREEN}{'='*60}{Colors.END}\n")
        except Exception as e:
            print(f"\n{Colors.BOLD}{Colors.RED}{'='*60}{Colors.END}")
            print(f"{Colors.BOLD}{Colors.RED}VOICE INITIALIZATION FAILED{Colors.END}")
            print(f"{Colors.BOLD}{Colors.RED}{'='*60}{Colors.END}")
            print(f"{Colors.RED}Error: {e}{Colors.END}\n")
            print(f"{Colors.YELLOW}Full traceback:{Colors.END}")
            import traceback
            traceback.print_exc()
            print(f"\n{Colors.YELLOW}Continuing with keyboard-only mode{Colors.END}")
            print(f"{Colors.YELLOW}Press Enter to continue...{Colors.END}")
            input()
    else:
        print(f"\n{Colors.BOLD}{Colors.RED}{'='*60}{Colors.END}")
        print(f"{Colors.BOLD}{Colors.RED}VOICE FILES NOT FOUND{Colors.END}")
        print(f"{Colors.BOLD}{Colors.RED}{'='*60}{Colors.END}")
        print(f"{Colors.YELLOW}Voice functionality disabled - missing required files{Colors.END}")
        print(f"\n{Colors.CYAN}To enable voice:{Colors.END}")
        print(f"  1. Install Piper TTS model to: {args.piper_model}")
        print(f"  2. Install Piper config to: {args.piper_config}")
        print(f"  3. Install Vosk model to: {args.vosk}")
        print(f"\n{Colors.YELLOW}Press Enter to continue with keyboard-only mode...{Colors.END}")
        input()
    
    clear_screen()
    print_header("FULL SYSTEM - KEYBOARD + VOICE")
    print_instructions()
    
    print()
    if voice_enabled:
        print(f"{Colors.GREEN}✓ Voice AI Active - Speak anytime!{Colors.END}")
    else:
        print(f"{Colors.RED}✗ Voice AI Disabled - Check errors above{Colors.END}")
    print(f"{Colors.GREEN}✓ Keyboard Control Active - Use WASD!{Colors.END}")
    if ultrasonic_handle:
        print(f"{Colors.GREEN}✓ Obstacle Detection Active - Threshold: {OBSTACLE_THRESHOLD}cm{Colors.END}")
    else:
        print(f"{Colors.RED}✗ Obstacle Detection Disabled{Colors.END}")
    if CAMERA_AVAILABLE:
        print(f"{Colors.GREEN}✓ Camera Vision Active - Say 'what do you see?'{Colors.END}")
    else:
        print(f"{Colors.RED}✗ Camera Vision Disabled{Colors.END}")
    if GESTURE_AVAILABLE:
        if args.gesture:
            print(f"{Colors.GREEN}✓ Hand Gesture Control Active - Use hand gestures!{Colors.END}")
        else:
            print(f"{Colors.YELLOW}○ Hand Gesture Available - Press 'G' or use --gesture flag{Colors.END}")
    else:
        print(f"{Colors.RED}✗ Hand Gesture Disabled - Install opencv-python mediapipe{Colors.END}")
    print()
    
    stop_all()

    # Start web UI server
    web_thread = threading.Thread(target=start_web_ui, daemon=True)
    web_thread.start()
    print(f"{Colors.GREEN}[THREAD] Web UI thread started{Colors.END}")

    # Auto-open the eyes UI fullscreen (kiosk) on the Pi's display
    launch_kiosk_browser('http://localhost:8080')

    kb_thread = threading.Thread(target=keyboard_thread_func, daemon=True)
    kb_thread.start()
    print(f"{Colors.GREEN}[THREAD] Keyboard thread started{Colors.END}")

    gamepad_thread = threading.Thread(target=gamepad_thread_func, daemon=True)
    gamepad_thread.start()
    print(f"{Colors.GREEN}[THREAD] Gamepad thread started{Colors.END}")

    roam_thread = threading.Thread(target=roam_thread_func, daemon=True)
    roam_thread.start()
    print(f"{Colors.GREEN}[THREAD] Autonomous roam thread started{Colors.END}")

    obstacle_thread = threading.Thread(target=obstacle_monitor_thread_func, daemon=True)
    obstacle_thread.start()
    print(f"{Colors.GREEN}[THREAD] Obstacle monitor thread started{Colors.END}")

    webdrive_thread = threading.Thread(target=web_drive_watchdog_func, daemon=True)
    webdrive_thread.start()
    print(f"{Colors.GREEN}[THREAD] Web-drive safety watchdog started{Colors.END}")
    
    # Start gesture control thread if available and requested
    gesture_thread = None
    video_thread = None
    if GESTURE_AVAILABLE and args.gesture:
        gesture_enabled = True
        update_robot_status("gesture_enabled", True)
        gesture_thread = threading.Thread(
            target=gesture_thread_func, 
            args=(args.gesture_camera, False),  # Don't show local window, stream to web
            daemon=True
        )
        gesture_thread.start()
        print(f"{Colors.GREEN}[THREAD] Gesture control thread started (with video streaming){Colors.END}")
    elif GESTURE_AVAILABLE:
        # Do NOT auto-start the camera. The live view/stream only turns on when
        # the camera is actually being used (press 'G' for gesture control), so
        # the camera panel stays closed by default and CPU stays free for audio.
        print(f"{Colors.YELLOW}[VIDEO] Camera idle - press 'G' to enable gesture control + live view{Colors.END}")
    elif args.gesture and not GESTURE_AVAILABLE:
        print(f"{Colors.RED}[GESTURE] Requested but OpenCV/MediaPipe not installed{Colors.END}")
        print(f"{Colors.YELLOW}         Install with: pip install opencv-python mediapipe{Colors.END}")
    
    # Start voice thread if available
    voice_thread = None
    if voice_enabled and tts and mic:
        def voice_thread_func():
            global shared_speed
            print(f"{Colors.CYAN}[VOICE] Thread started - listening...{Colors.END}")
            sys.stdout.flush()
            
            while keyboard_running:
                try:
                    # Show listening indicator
                    update_robot_status("eye_state", "listening")
                    update_robot_status("voice", "listening")
                    update_robot_status("status", "listening")
                    print(f"{Colors.CYAN}[VOICE] 🎤 Listening... (speak now){Colors.END}", flush=True)
                    
                    text = mic.listen()

                    if text:
                        update_robot_status("audio_input", text)
                        print(f"{Colors.BOLD}{Colors.MAGENTA}[VOICE] You said: '{text}'{Colors.END}", flush=True)

                        # Clear audio input after a while (keep it readable on screen)
                        def clear_audio_input():
                            time.sleep(6)
                            update_robot_status("audio_input", "")
                        threading.Thread(target=clear_audio_input, daemon=True).start()

                        # --- Wake word gating ---
                        had_wake, spoken = strip_wake_word(text)
                        now = time.time()
                        awake = (now - _last_awake_time[0]) < WAKE_TIMEOUT
                        # Safety: an explicit stop is ALWAYS honored, even without the wake word
                        emergency_stop = any(_phrase_in(w, text.lower()) for w in
                                             ["stop", "halt", "freeze", "stop roaming", "stop exploring"])
                        if wake_word_required and not had_wake and not awake and not emergency_stop:
                            # Not addressed to Buddy - ignore and go sleepy
                            update_robot_status("eye_state", "sleeping")
                            update_robot_status("voice", "asleep")
                            update_robot_status("awake", False)
                            update_robot_status("status", "asleep - say 'Hey Buddy'")
                            print(f"{Colors.YELLOW}[VOICE] Ignored (no wake word): '{text}'{Colors.END}", flush=True)
                            continue
                        # Addressed (or still within the awake window): refresh timer
                        _last_awake_time[0] = now
                        update_robot_status("awake", True)
                        # Only the wake word, no command? Greet and keep listening.
                        if had_wake and not spoken:
                            greet = "Yes? I'm listening!"
                            update_robot_status("eye_state", "listening")
                            update_robot_status("audio_output", greet)
                            play_audio(tts.speak(clean_text_for_tts(greet)))
                            def clear_greet():
                                time.sleep(2)
                                update_robot_status("audio_output", "")
                            threading.Thread(target=clear_greet, daemon=True).start()
                            continue
                        # Use the command text with the wake word stripped out
                        if had_wake:
                            text = spoken

                        with speed_lock:
                            current_speed = shared_speed

                        # Check for motor commands
                        m_reply = check_robot_command(text, current_speed)
                        if m_reply:
                            if m_reply == "SPEED_UP":
                                with speed_lock:
                                    old_speed = shared_speed
                                    shared_speed = clamp(shared_speed + 0.1)
                                update_robot_status("speed", round(shared_speed, 2))
                                update_robot_status("eye_state", "normal")
                                update_robot_status("voice", "ready")
                                speed_msg = f"Speed increased to {shared_speed:.1f}"
                                update_robot_status("audio_output", speed_msg)
                                print(f"{Colors.CYAN}[VOICE] Speed: {old_speed:.2f} → {shared_speed:.2f}{Colors.END}", flush=True)
                                play_audio(tts.speak(clean_text_for_tts(speed_msg)))

                                # Clear audio output after speaking
                                def clear_audio_output():
                                    time.sleep(2)
                                    update_robot_status("audio_output", "")
                                threading.Thread(target=clear_audio_output, daemon=True).start()
                            elif m_reply == "SPEED_DOWN":
                                with speed_lock:
                                    old_speed = shared_speed
                                    shared_speed = clamp(shared_speed - 0.1)
                                update_robot_status("speed", round(shared_speed, 2))
                                update_robot_status("eye_state", "normal")
                                update_robot_status("voice", "ready")
                                speed_msg = f"Speed decreased to {shared_speed:.1f}"
                                update_robot_status("audio_output", speed_msg)
                                print(f"{Colors.CYAN}[VOICE] Speed: {old_speed:.2f} → {shared_speed:.2f}{Colors.END}", flush=True)
                                play_audio(tts.speak(clean_text_for_tts(speed_msg)))

                                # Clear audio output after speaking
                                def clear_audio_output():
                                    time.sleep(2)
                                    update_robot_status("audio_output", "")
                                threading.Thread(target=clear_audio_output, daemon=True).start()
                            elif m_reply == "IMAGE_DETECTION":
                                # Handle image detection
                                if not CAMERA_AVAILABLE:
                                    update_robot_status("eye_state", "surprised")
                                    update_robot_status("voice", "ready")
                                    update_robot_status("status", "camera unavailable")
                                    error_msg = "Sorry, my camera is not available right now."
                                    update_robot_status("audio_output", error_msg)
                                    print(f"{Colors.YELLOW}[VOICE] Camera not available{Colors.END}", flush=True)
                                    play_audio(tts.speak(clean_text_for_tts(error_msg)))

                                    # Clear audio output after speaking
                                    def clear_audio_output():
                                        time.sleep(2)
                                        update_robot_status("audio_output", "")
                                    threading.Thread(target=clear_audio_output, daemon=True).start()
                                else:
                                    update_robot_status("eye_state", "thinking")
                                    update_robot_status("voice", "processing")
                                    update_robot_status("status", "capturing image")
                                    print(f"{Colors.BLUE}[VISION] Capturing image...{Colors.END}", flush=True)

                                    # Capture image
                                    capture_result = capture_image()
                                    if capture_result:
                                        image_path, image_b64 = capture_result
                                        
                                        # Show the captured image in the web UI
                                        update_robot_status("captured_image", image_b64)
                                        update_robot_status("status", "analyzing image")

                                        # Analyze image with gemma3:4b
                                        prompt = "Describe what you see in this image in a friendly, helpful way. Keep it brief but informative."
                                        print(f"{Colors.BLUE}[VISION] Analyzing with gemma3:4b...{Colors.END}", flush=True)

                                        description = ask_ollama(prompt, args.model, args.url, image_path)

                                        # Update UI and speak
                                        update_robot_status("image_description", description[:100] + "..." if len(description) > 100 else description)
                                        update_robot_status("eye_state", "normal")
                                        update_robot_status("voice", "speaking")
                                        update_robot_status("status", "describing image")

                                        update_robot_status("audio_output", description)
                                        print(f"{Colors.GREEN}[VISION] Description: {description}{Colors.END}", flush=True)
                                        play_audio(tts.speak(clean_text_for_tts(description)))

                                        # Clear audio output after speaking
                                        def clear_audio_output():
                                            time.sleep(2)
                                            update_robot_status("audio_output", "")
                                        threading.Thread(target=clear_audio_output, daemon=True).start()

                                        # Clear description after a few seconds
                                        def clear_description():
                                            time.sleep(10)
                                            update_robot_status("image_description", "")
                                            update_robot_status("captured_image", "")
                                        threading.Thread(target=clear_description, daemon=True).start()

                                    else:
                                        update_robot_status("eye_state", "surprised")
                                        update_robot_status("voice", "ready")
                                        update_robot_status("status", "capture failed")
                                        error_msg = "Sorry, I couldn't capture an image right now."
                                        update_robot_status("audio_output", error_msg)
                                        print(f"{Colors.RED}[VISION] Capture failed{Colors.END}", flush=True)
                                        play_audio(tts.speak(clean_text_for_tts(error_msg)))

                                        # Clear audio output after speaking
                                        def clear_audio_output():
                                            time.sleep(2)
                                            update_robot_status("audio_output", "")
                                        threading.Thread(target=clear_audio_output, daemon=True).start()

                                    update_robot_status("voice", "ready")
                                    update_robot_status("status", "ready")
                            else:
                                update_robot_status("audio_output", m_reply)
                                print(f"{Colors.GREEN}[VOICE] Action: {m_reply}{Colors.END}", flush=True)
                                play_audio(tts.speak(clean_text_for_tts(m_reply)))

                                # Clear audio output after speaking
                                def clear_audio_output():
                                    time.sleep(2)
                                    update_robot_status("audio_output", "")
                                threading.Thread(target=clear_audio_output, daemon=True).start()
                        else:
                            # Use AI for conversation
                            update_robot_status("eye_state", "blinking")
                            update_robot_status("voice", "thinking")
                            update_robot_status("status", "processing")
                            print(f"{Colors.BLUE}[AI] Thinking...{Colors.END}", flush=True)
                            reply = ask_ollama(build_prompt_with_memory(text), args.model, args.url)
                            conversation_history.append((text, reply))
                            update_robot_status("eye_state", "normal")
                            update_robot_status("voice", "speaking")
                            update_robot_status("status", "responding")
                            update_robot_status("audio_output", reply)
                            print(f"{Colors.BLUE}[AI] Response: {reply}{Colors.END}", flush=True)
                            play_audio(tts.speak(clean_text_for_tts(reply)))
                            update_robot_status("voice", "ready")
                            update_robot_status("status", "ready")

                            # Clear audio output after speaking (keep it readable)
                            def clear_audio_output():
                                time.sleep(5)  # linger after speech ends
                                update_robot_status("audio_output", "")
                            threading.Thread(target=clear_audio_output, daemon=True).start()

                        # Keep the awake window alive after a successful interaction
                        _last_awake_time[0] = time.time()
                        print(f"{Colors.CYAN}[VOICE] Ready for next command...{Colors.END}", flush=True)
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"{Colors.RED}[VOICE ERROR] {e}{Colors.END}", flush=True)
                    import traceback
                    traceback.print_exc()
                    time.sleep(0.5)
            
            print(f"{Colors.YELLOW}[VOICE] Thread stopped{Colors.END}", flush=True)
        
        voice_thread = threading.Thread(target=voice_thread_func, daemon=True)
        voice_thread.start()
        print(f"{Colors.GREEN}[THREAD] Voice AI thread started{Colors.END}")
    else:
        print(f"{Colors.YELLOW}[THREAD] Voice AI not available - keyboard only{Colors.END}")
    
    print(f"\n{Colors.BOLD}{Colors.GREEN}ALL SYSTEMS RUNNING!{Colors.END}\n")
    sys.stdout.flush()
    
    # Main loop - handles keyboard commands
    try:
        last_action = "stopped"
        while True:
            with key_lock:
                ch = current_key
                current_key = None
            
            if ch:
                if ch == '\x03' or ch.upper() == 'Q':  # Ctrl+C or Q
                    print(f"\n{Colors.RED}Shutting down...{Colors.END}")
                    break
                
                c = ch.upper()
                
                with speed_lock:
                    current_speed = shared_speed
                
                # Movement commands
                if c == 'W':
                    stop_roam_for_manual()
                    update_robot_status("eye_state", "forward")
                    update_robot_status("status", "moving forward")
                    set_both_forward(current_speed)
                    last_action = "forward"
                    print(f"{Colors.GREEN}[KEYBOARD] → Forward (speed={current_speed:.2f}){Colors.END}")
                elif c == 'S':
                    stop_roam_for_manual()
                    update_robot_status("eye_state", "backward")
                    update_robot_status("status", "moving backward")
                    set_both_backward(current_speed)
                    last_action = "backward"
                    print(f"{Colors.GREEN}[KEYBOARD] → Backward (speed={current_speed:.2f}){Colors.END}")
                elif c == 'A':
                    stop_roam_for_manual()
                    update_robot_status("eye_state", "left")
                    update_robot_status("status", "spinning left")
                    spin_left(current_speed)
                    last_action = "spin_left"
                    print(f"{Colors.GREEN}[KEYBOARD] → Spin Left (speed={current_speed:.2f}){Colors.END}")
                elif c == 'D':
                    stop_roam_for_manual()
                    update_robot_status("eye_state", "right")
                    update_robot_status("status", "spinning right")
                    spin_right(current_speed)
                    last_action = "spin_right"
                    print(f"{Colors.GREEN}[KEYBOARD] → Spin Right (speed={current_speed:.2f}){Colors.END}")
                elif c == ' ':
                    set_roam(False)
                    update_robot_status("eye_state", "sleeping")
                    update_robot_status("status", "stopped")
                    stop_all()
                    last_action = "stopped"
                    print(f"{Colors.YELLOW}[KEYBOARD] → STOPPED{Colors.END}")

                # Autonomous roam toggle
                elif c == 'R':
                    with roam_lock:
                        currently = roam_enabled
                    set_roam(not currently)

                # Wake-word requirement toggle
                elif c == 'K':
                    wake_word_required = not wake_word_required
                    update_robot_status("wake_required", wake_word_required)
                    if wake_word_required:
                        print(f"{Colors.CYAN}[VOICE] Wake word REQUIRED - say 'Hey Buddy' first{Colors.END}")
                    else:
                        _last_awake_time[0] = time.time()
                        print(f"{Colors.CYAN}[VOICE] Wake word OFF - always listening{Colors.END}")
                
                # Speed controls
                elif c == '+' or c == '=':
                    with speed_lock:
                        old_speed = shared_speed
                        shared_speed = clamp(shared_speed + 0.1)
                        update_robot_status("speed", round(shared_speed, 2))
                        print(f"{Colors.CYAN}[KEYBOARD] Speed: {old_speed:.2f} → {shared_speed:.2f}{Colors.END}")
                elif c == '-':
                    with speed_lock:
                        old_speed = shared_speed
                        shared_speed = clamp(shared_speed - 0.1)
                        update_robot_status("speed", round(shared_speed, 2))
                        print(f"{Colors.CYAN}[KEYBOARD] Speed: {old_speed:.2f} → {shared_speed:.2f}{Colors.END}")
                elif c.isdigit():
                    preset = int(c)
                    if 1 <= preset <= 9:
                        with speed_lock:
                            shared_speed = preset * 0.1
                            update_robot_status("speed", round(shared_speed, 2))
                            print(f"{Colors.CYAN}[KEYBOARD] Speed preset {preset}: {shared_speed:.2f}{Colors.END}")
                
                # System commands
                elif c == 'H':
                    print_comprehensive_help()
                    clear_screen()
                    print_header("FULL SYSTEM - KEYBOARD + VOICE")
                    print_instructions()
                    if voice_enabled:
                        print(f"{Colors.GREEN}✓ Voice AI Active{Colors.END}")
                    else:
                        print(f"{Colors.RED}✗ Voice AI Disabled{Colors.END}")
                    print(f"{Colors.GREEN}✓ Keyboard Control Active{Colors.END}\n")
                
                # Toggle gesture control
                elif c == 'G':
                    if GESTURE_AVAILABLE:
                        with gesture_lock:
                            gesture_enabled = not gesture_enabled
                            update_robot_status("gesture_enabled", gesture_enabled)
                            if gesture_enabled:
                                print(f"{Colors.GREEN}[GESTURE] Hand gesture control ENABLED{Colors.END}")
                                # Start gesture thread if not already running (it handles both video + gestures)
                                if gesture_thread is None or not gesture_thread.is_alive():
                                    gesture_thread = threading.Thread(
                                        target=gesture_thread_func,
                                        args=(args.gesture_camera, False),  # Stream to web, no local window
                                        daemon=True
                                    )
                                    gesture_thread.start()
                            else:
                                print(f"{Colors.YELLOW}[GESTURE] Hand gesture control DISABLED (video still streaming){Colors.END}")
                    else:
                        print(f"{Colors.RED}[GESTURE] Not available - install opencv-python and mediapipe{Colors.END}")
            
            time.sleep(0.01)
    
    except KeyboardInterrupt:
        print(f"\n{Colors.RED}Interrupted by user{Colors.END}")
    finally:
        # Exit fullscreen first: close the kiosk browser immediately on the way out
        close_kiosk_browser()
        keyboard_running = False
        set_roam(False)
        stop_all()
        if kb_thread:
            kb_thread.join(timeout=1)
        if voice_thread:
            voice_thread.join(timeout=1)
        if gamepad_thread:
            gamepad_thread.join(timeout=1)
        if roam_thread:
            roam_thread.join(timeout=1)
        if obstacle_thread:
            obstacle_thread.join(timeout=1)
        if webdrive_thread:
            webdrive_thread.join(timeout=1)
        if gesture_thread:
            gesture_thread.join(timeout=1)
        if video_thread:
            video_thread.join(timeout=1)
        if GESTURE_AVAILABLE:
            cv2.destroyAllWindows()
        if ultrasonic_handle is not None:
            lgpio.gpiochip_close(ultrasonic_handle)
        print(f"{Colors.GREEN}All systems stopped. Goodbye!{Colors.END}")

if __name__ == "__main__":
    main()