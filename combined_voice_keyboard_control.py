#!/usr/bin/env python3

"""
COMBINED VOICE AI + KEYBOARD MOTOR CONTROL
Microphone → VOSK → OLLAMA → PIPER → AUDIO OUT → MOTOR MOVEMENT
+ Keyboard control with WASD keys

Uses your EXACT MOTOR PIN CONFIG:

LEFT MOTOR:
    ENA = PWMOutputDevice(12)
    IN1 = OutputDevice(23)
    IN2 = OutputDevice(24)

RIGHT MOTOR:
    ENB = PWMOutputDevice(13)
    IN3 = OutputDevice(16)
    IN4 = OutputDevice(21)
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
from vosk import Model, KaldiRecognizer
from gpiozero import PWMOutputDevice, OutputDevice

# ANSI color codes for enhanced interface
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

# Enhanced interface functions
def clear_screen():
    """Clear the terminal screen"""
    print('\033[2J\033[H', end='')

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

def print_status(speed, mode, last_action, voice_enabled=False):
    """Print real-time status display"""
    print(f"\033[s", end='')  # Save cursor position
    print(f"\033[1;1H", end='')  # Move to top-left

    status_lines = [
        f"{Colors.BOLD}{Colors.GREEN}ROBOT CONTROL SYSTEM{Colors.END}",
        f"{Colors.BLUE}Mode:{Colors.END} {mode}",
        f"{Colors.BLUE}Speed:{Colors.END} {speed:.2f}",
        f"{Colors.BLUE}Status:{Colors.END} {last_action}",
        f"{Colors.BLUE}Voice:{Colors.END} {'Enabled' if voice_enabled else 'Disabled'}",
        "",
        f"{Colors.CYAN}Controls: WASD + Space | +/- speed | H-help | Q-quit{Colors.END}"
    ]

    for line in status_lines:
        print(line)

    print(f"\033[u", end='')  # Restore cursor position

def print_comprehensive_help():
    """Display comprehensive help information"""
    clear_screen()
    print_header("ROBOT CONTROL HELP")

    print_section("MOVEMENT CONTROLS")
    print(f"{Colors.GREEN}WASD Keys:{Colors.END}")
    print("  W: Move Backward")
    print("  S: Move Forward")
    print("  A: Spin Left")
    print("  D: Spin Right")
    print("  Space: Emergency Stop")

    print(f"\n{Colors.GREEN}Diagonal Movement:{Colors.END}")
    print("  E: Forward-Right")
    print("  Z: Backward-Left")
    print("  C: Backward-Right")

    print_section("SPEED CONTROLS")
    print(f"{Colors.GREEN}Speed Adjustment:{Colors.END}")
    print("  + / =: Increase speed")
    print("  -: Decrease speed")
    print("  1-9: Set speed preset (1=slowest, 9=fastest)")
    print("  0: Emergency slow speed")

    print_section("VOICE COMMANDS")
    print(f"{Colors.GREEN}Basic Movement:{Colors.END}")
    print("  'forward', 'go ahead' → Move forward")
    print("  'back', 'reverse' → Move backward")
    print("  'left', 'turn left' → Spin left")
    print("  'right', 'turn right' → Spin right")
    print("  'stop' → Stop all movement")

    print(f"\n{Colors.GREEN}Advanced Voice Commands:{Colors.END}")
    print("  'faster' → Increase speed")
    print("  'slower' → Decrease speed")
    print("  'full speed' → Maximum speed")
    print("  'slow down' → Minimum speed")
    print("  'diagonal left' → Forward-left")
    print("  'diagonal right' → Forward-right")
    print("  'circle left/right' → Circle movement")

    print_section("SYSTEM CONTROLS")
    print(f"{Colors.GREEN}System:{Colors.END}")
    print("  H: Show this help")
    print("  R: Reset speed to default")
    print("  I: System information")
    print("  Q: Quit program")
    print("  Ctrl+C: Emergency stop and quit")

    print_section("STATUS DISPLAY")
    print("Top of screen shows real-time status:")
    print("  - Current mode (voice/keyboard/both)")
    print("  - Speed setting")
    print("  - Last action")
    print("  - Voice status")

    print(f"\n{Colors.RED}Press any key to return to control...{Colors.END}")
    input()

def print_system_info():
    """Display system information"""
    clear_screen()
    print_header("SYSTEM INFORMATION")

    try:
        import psutil
        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        print(f"{Colors.BLUE}CPU Usage:{Colors.END} {cpu}%")
        print(f"{Colors.BLUE}Memory:{Colors.END} {memory.percent}% used ({memory.available//1024//1024}MB free)")
        print(f"{Colors.BLUE}Disk:{Colors.END} {disk.percent}% used")
    except ImportError:
        print(f"{Colors.YELLOW}psutil not available for system stats{Colors.END}")

    print(f"\n{Colors.BLUE}GPIO Status:{Colors.END}")
    try:
        # Check if motors are accessible
        print("Motors: Initialized and ready")
    except:
        print("Motors: Not accessible (need sudo?)")

    print(f"\n{Colors.BLUE}Audio Status:{Colors.END}")
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        device_count = pa.get_device_count()
        print(f"Audio devices: {device_count} available")
        pa.terminate()
    except:
        print("Audio: Not available")

    print(f"\n{Colors.RED}Press any key to continue...{Colors.END}")
    input()


DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL_NAME = "gemma3:1b"
DEFAULT_PIPER_MODEL = "/home/admin/piper_voices/en_US-amy-medium.onnx"
DEFAULT_PIPER_CONFIG = "/home/admin/piper_voices/en_US-amy-medium.onnx.json"
DEFAULT_VOSK_MODEL = "/home/admin/rasp/motor_control/model"
STREAM_DEBUG = False
OUT_WAV = "voice_reply.wav"
SPEED = 0.4


# ============================================================
#  TEXT CLEANUP FOR TTS
# ============================================================
def clean_text_for_tts(text):
    """Remove asterisks and emojis from text before TTS"""
    # Remove all asterisks
    text = text.replace('*', '')

    # Remove emojis (basic pattern)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map symbols
        "\U0001F1E0-\U0001F1FF"  # flags (iOS)
        "\U00002700-\U000027BF"  # dingbats
        "\U0001f926-\U0001f937"  # gestures
        "\U00010000-\U0010ffff"  # other unicode
        "\u2640-\u2642"  # gender symbols
        "\u2600-\u2B55"  # misc symbols
        "\u200d"  # zero width joiner
        "\u23cf"  # eject symbol
        "\u23e9"  # fast forward
        "\u231a"  # watch
        "\ufe0f"  # variation selector
        "\u3030"  # wavy dash
        "]+",
        flags=re.UNICODE
    )
    text = emoji_pattern.sub('', text)

    return text.strip()


# ============================================================
#  MOTOR CONTROL FUNCTIONS (from motor_a_control.py)
# ============================================================

# Global motor instances (initialized later)
ENA = None
IN1 = None
IN2 = None
ENB = None
IN3 = None
IN4 = None

def init_motors():
    global ENA, IN1, IN2, ENB, IN3, IN4
    try:
        # LEFT MOTOR
        ENA = PWMOutputDevice(12)
        IN1 = OutputDevice(23)
        IN2 = OutputDevice(24)
        # RIGHT MOTOR
        ENB = PWMOutputDevice(13)
        IN3 = OutputDevice(16)
        IN4 = OutputDevice(21)
        print("[MOTOR] Motors initialized successfully")
    except Exception as e:
        print(f"[MOTOR] Failed to initialize motors: {e}")
        print("[MOTOR] Running in audio-only mode (no motor control)")
        ENA = IN1 = IN2 = ENB = IN3 = IN4 = None

def left_motor_forward(speed=0.4):
    if ENA is None: return
    IN1.on()
    IN2.off()
    ENA.value = speed

def left_motor_backward(speed=0.4):
    if ENA is None: return
    IN1.off()
    IN2.on()
    ENA.value = speed

def left_motor_stop():
    if ENA is None: return
    IN1.off()
    IN2.off()
    ENA.value = 0

def right_motor_forward(speed=0.4):
    if ENB is None: return
    IN3.on()
    IN4.off()
    ENB.value = speed

def right_motor_backward(speed=0.4):
    if ENB is None: return
    IN3.off()
    IN4.on()
    ENB.value = speed

def right_motor_stop():
    if ENB is None: return
    IN3.off()
    IN4.off()
    ENB.value = 0

def all_stop():
    left_motor_stop()
    right_motor_stop()


# ============================================================
#  PIPER TTS
# ============================================================
class PiperTTS:
    def __init__(self, model_path, config_path):
        print("[PIPER] Loading model...")
        from piper_onnx import Piper
        self.p = Piper(model_path, config_path)
        print("[PIPER] Ready.")

    def speak(self, text, out_file=OUT_WAV):
        print("[PIPER] Synthesizing...")
        audio, sr = self.p.create(text)

        import numpy as np, wave
        pcm = (audio * 32767).astype("int16")

        with wave.open(out_file, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(pcm.tobytes())

        return out_file


# ============================================================
#  AUDIO PLAYBACK
# ============================================================
def play_audio(path):
    aplay = shutil.which("aplay")
    if aplay:
        subprocess.run([aplay, path])
        return

    import soundfile as sf, sounddevice as sd
    data, sr = sf.read(path, dtype='int16')
    sd.play(data, sr)
    sd.wait()


# ============================================================
#  MICROPHONE HANDLER
# ============================================================
class MicInput:
    def __init__(self, vosk_model_path):

        print("[VOSK] Loading speech model...")
        if not os.path.exists(vosk_model_path):
            raise RuntimeError("Vosk model not found!")

        self.model = Model(vosk_model_path)

        self.pa = pyaudio.PyAudio()
        self.device_index, self.sample_rate = self.detect_input_device()
        print(f"[MIC] Using device {self.device_index} @ {self.sample_rate} Hz")

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

        # First pass: look for devices with keywords in name
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

        # Second pass: if no keyword match, try default device or first device with input
        if best_idx is not None:
            return best_idx, best_rate

        # Third pass: try to find any device with input channels (including pulseaudio)
        for i in range(self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(i)
            chans = info["maxInputChannels"]
            rate = int(info.get("defaultSampleRate", 16000))
            if chans > 0:
                return i, rate

        # If still no device found, raise an error
        raise RuntimeError("No audio input device found. Please check your microphone setup.")

    def listen(self):
        print("\n[LISTEN] Speak now...")
        while True:
            data = self.stream.read(4096, exception_on_overflow=False)

            if self.recognizer.AcceptWaveform(data):
                result = json.loads(self.recognizer.Result())
                return result.get("text", "").strip()


# ============================================================
#  OLLAMA STREAM
# ============================================================
def ask_ollama(prompt, model, url):
    import requests

    payload = {"model": model, "prompt": prompt, "stream": True}
    r = requests.post(url, json=payload, stream=True)

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


# ============================================================
#  COMMAND PARSER
# ============================================================
def check_robot_command(text, current_speed=SPEED):
    t = text.lower()

    # Basic movement
    if "forward" in t or "go ahead" in t:
        if "left" in t or "diagonal left" in t:
            forward_left(current_speed)
            return "Moving forward-left"
        elif "right" in t or "diagonal right" in t:
            forward_right(current_speed)
            return "Moving forward-right"
        else:
            set_both_forward(current_speed)
            return "Moving forward"

    if "back" in t or "reverse" in t or "backward" in t:
        if "left" in t:
            backward_left(current_speed)
            return "Moving backward-left"
        elif "right" in t:
            backward_right(current_speed)
            return "Moving backward-right"
        else:
            set_both_backward(current_speed)
            return "Moving backward"

    if ("left" in t or "turn left" in t) and not ("forward" in t or "back" in t):
        if "circle" in t:
            circle_left(current_speed)
            return "Circling left"
        else:
            spin_left(current_speed)
            return "Spinning left"

    if ("right" in t or "turn right" in t) and not ("forward" in t or "back" in t):
        if "circle" in t:
            circle_right(current_speed)
            return "Circling right"
        else:
            spin_right(current_speed)
            return "Spinning right"

    if "stop" in t or "halt" in t:
        stop_all()
        return "Stopped"

    # Speed control via voice
    if "faster" in t or "speed up" in t:
        return "SPEED_UP"

    if "slower" in t or "slow down" in t:
        return "SPEED_DOWN"

    if "full speed" in t or "maximum" in t:
        return "SPEED_MAX"

    if "slow" in t and ("speed" in t or "motion" in t):
        return "SPEED_MIN"

    if "quit" in t or "exit" in t:
        print("Voice command: Exiting...")
        sys.exit(0)

    return None


# ============================================================
#  KEYBOARD CONTROL FUNCTIONS
# ============================================================

def set_both_forward(speed=SPEED):
    left_motor_forward(speed)
    right_motor_forward(speed)

def set_both_backward(speed=SPEED):
    left_motor_backward(speed)
    right_motor_backward(speed)

def spin_left(speed=SPEED):
    # left backward, right forward -> rotate left in place
    left_motor_backward(speed)
    right_motor_forward(speed)

def spin_right(speed=SPEED):
    # left forward, right backward -> rotate right in place
    left_motor_forward(speed)
    right_motor_backward(speed)

def stop_all():
    left_motor_stop()
    right_motor_stop()

# Enhanced movement functions
def forward_left(speed=SPEED):
    """Move forward-left diagonally"""
    left_motor_forward(speed * 0.5)  # Slower left motor
    right_motor_forward(speed)

def forward_right(speed=SPEED):
    """Move forward-right diagonally"""
    left_motor_forward(speed)
    right_motor_forward(speed * 0.5)  # Slower right motor

def backward_left(speed=SPEED):
    """Move backward-left diagonally"""
    left_motor_backward(speed * 0.5)
    right_motor_backward(speed)

def backward_right(speed=SPEED):
    """Move backward-right diagonally"""
    left_motor_backward(speed)
    right_motor_backward(speed * 0.5)

def circle_left(speed=SPEED):
    """Circle movement to the left"""
    left_motor_backward(speed * 0.3)
    right_motor_forward(speed * 0.7)

def circle_right(speed=SPEED):
    """Circle movement to the right"""
    left_motor_forward(speed * 0.7)
    right_motor_backward(speed * 0.3)

def set_speed_preset(preset, current_speed):
    """Set speed based on preset (1-9)"""
    if preset == 0:
        return 0.1  # Emergency slow
    elif 1 <= preset <= 9:
        return preset * 0.1  # 0.1 to 0.9
    return current_speed

# --- terminal helpers to read single character without Enter ---
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
    print(f"{Colors.BOLD}{Colors.GREEN}ROBOT CONTROL INTERFACE{Colors.END}")
    print(f"{Colors.CYAN}{'='*50}{Colors.END}")
    print(f"{Colors.BOLD}Movement Controls:{Colors.END}")
    print("  W: Backward    S: Forward")
    print("  A: Spin Left   D: Spin Right")
    print("  E: Fwd-Right   Z: Bck-Left")
    print("  C: Bck-Right")
    print(f"{Colors.BOLD}Speed Controls:{Colors.END}")
    print("  +/=: Faster    -: Slower")
    print("  1-9: Speed preset  0: Emergency slow")
    print(f"{Colors.BOLD}System Controls:{Colors.END}")
    print("  Space: Stop    H: Help")
    print("  R: Reset speed I: System Info")
    print("  Q: Quit")
    print(f"{Colors.CYAN}{'='*50}{Colors.END}")
    print(f"Voice commands also available! Starting speed: {SPEED}")
    print(f"{Colors.YELLOW}Press H anytime for full help{Colors.END}\n")

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


# ============================================================
#  MAIN
# ============================================================
def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["voice", "keyboard", "both"], default="both",
                       help="Control mode: voice (speech), keyboard (WASD), or both")
    parser.add_argument("--piper-model", default=DEFAULT_PIPER_MODEL, help="Path to Piper TTS model file")
    parser.add_argument("--piper-config", default=DEFAULT_PIPER_CONFIG, help="Path to Piper TTS config file")
    parser.add_argument("--vosk", default=DEFAULT_VOSK_MODEL, help="Path to Vosk speech recognition model directory")
    parser.add_argument("--model", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--url", default=DEFAULT_OLLAMA_URL)
    args = parser.parse_args()

    # Initialize motors
    init_motors()
    motor_driver = None

    # Initialize voice components if needed
    tts = None
    mic = None
    if args.mode in ["voice", "both"]:
        if os.path.exists(args.piper_model) and os.path.exists(args.piper_config):
            try:
                tts = PiperTTS(args.piper_model, args.piper_config)
                mic = MicInput(args.vosk)
            except Exception as e:
                print(f"Warning: Failed to initialize voice components: {e}")
                print("Falling back to keyboard-only mode")
                args.mode = "keyboard"
                tts = None
                mic = None
        else:
            print(f"Warning: Piper model ({args.piper_model}) or config ({args.piper_config}) not found, voice mode disabled")
            args.mode = "keyboard"

    clear_screen()
    print_header(f"{args.mode.upper()} CONTROL SYSTEM READY")
    print(f"{Colors.GREEN}Initializing robot control system...{Colors.END}")

    if args.mode == "voice":
        print(f"{Colors.BLUE}Mode:{Colors.END} Voice control with AI responses")
    elif args.mode == "keyboard":
        print(f"{Colors.BLUE}Mode:{Colors.END} Keyboard control only")
    else:
        print(f"{Colors.BLUE}Mode:{Colors.END} Combined voice + keyboard control")

    print(f"{Colors.BLUE}Motors:{Colors.END} Initialized")
    if args.mode in ["voice", "both"]:
        if tts:
            print(f"{Colors.BLUE}TTS:{Colors.END} Piper ready")
        if mic:
            print(f"{Colors.BLUE}Voice Recognition:{Colors.END} Vosk ready")

    print(f"\n{Colors.YELLOW}Press H anytime for comprehensive help{Colors.END}")
    print(f"{Colors.CYAN}{'='*60}{Colors.END}\n")

    if args.mode == "voice":
        # Voice-only mode
        while True:
            text = mic.listen()
            if not text:
                continue

            print("[YOU]:", text)

            # Motor commands first
            m_reply = check_robot_command(text, SPEED)
            if m_reply:
                if m_reply == "SPEED_UP":
                    print(f"{Colors.GREEN}Voice command: Speed up{Colors.END}")
                    # In voice-only mode, we don't have persistent speed variable
                    play_audio(tts.speak(clean_text_for_tts("Speed control not available in voice-only mode")))
                elif m_reply == "SPEED_DOWN":
                    print(f"{Colors.GREEN}Voice command: Slow down{Colors.END}")
                    play_audio(tts.speak(clean_text_for_tts("Speed control not available in voice-only mode")))
                else:
                    play_audio(tts.speak(clean_text_for_tts(m_reply)))
                continue

            # Otherwise use LLM
            reply = ask_ollama(text, args.model, args.url)
            play_audio(tts.speak(clean_text_for_tts(reply)))

    elif args.mode == "keyboard":
        # Keyboard-only mode
        try:
            print_instructions()
            speed = SPEED
            last_action = "stopped"
            # ensure motors are stopped on start
            stop_all()
            print(f">>> {last_action} (speed={speed:.2f})")

            while True:
                # Update status display
                print_status(speed, "keyboard", last_action, voice_enabled=False)

                ch = getch(timeout=0.05)

                if ch is None:
                    # No key currently pressed — ensure motors stopped if they were running
                    if last_action != "stopped":
                        stop_all()
                        last_action = "stopped"
                    # continue loop waiting for a real key press
                    continue

                # Handle special keys (arrow keys, function keys, etc.)
                if ch == '\x03':  # Ctrl+C
                    print(f"{Colors.RED}Interrupted by user (Ctrl-C).{Colors.END}")
                    break
                elif ch == '\x1b':  # ESC sequence start
                    ch = getch(timeout=0.01)
                    if ch == '[':
                        ch = getch(timeout=0.01)
                        # Handle arrow keys if needed
                        continue
                    else:
                        continue

                # Normalize to uppercase to accept lowercase letters too
                c = ch.upper()

                action_taken = False

                # Movement controls
                if c == "W":
                    set_both_backward(speed)
                    last_action = "backward"
                    action_taken = True
                elif c == "S":
                    set_both_forward(speed)
                    last_action = "forward"
                    action_taken = True
                elif c == "A":
                    spin_left(speed)
                    last_action = "spin_left"
                    action_taken = True
                elif c == "D":
                    spin_right(speed)
                    last_action = "spin_right"
                    action_taken = True
                elif c == "E":
                    forward_right(speed)
                    last_action = "forward_right"
                    action_taken = True
                elif c == "Z":
                    backward_left(speed)
                    last_action = "backward_left"
                    action_taken = True
                elif c == "C":
                    backward_right(speed)
                    last_action = "backward_right"
                    action_taken = True
                elif c == " ":
                    stop_all()
                    last_action = "stopped"
                    action_taken = True

                # Speed controls
                elif c == "+" or c == "=":
                    old_speed = speed
                    speed = clamp(speed + 0.05)
                    if speed != old_speed:
                        print(f"{Colors.GREEN}Speed increased → {speed:.2f}{Colors.END}")
                    action_taken = True
                elif c == "-":
                    old_speed = speed
                    speed = clamp(speed - 0.05)
                    if speed != old_speed:
                        print(f"{Colors.GREEN}Speed decreased → {speed:.2f}{Colors.END}")
                    action_taken = True
                elif c.isdigit():
                    preset = int(c)
                    old_speed = speed
                    speed = set_speed_preset(preset, speed)
                    if speed != old_speed:
                        print(f"{Colors.GREEN}Speed preset {preset} → {speed:.2f}{Colors.END}")
                    action_taken = True

                # System controls
                elif c == "H":
                    print_comprehensive_help()
                    clear_screen()
                    print_instructions()
                    action_taken = True
                elif c == "R":
                    speed = SPEED
                    print(f"{Colors.GREEN}Speed reset to default: {speed:.2f}{Colors.END}")
                    action_taken = True
                elif c == "I":
                    print_system_info()
                    clear_screen()
                    print_instructions()
                    action_taken = True
                elif c == "Q":
                    print(f"{Colors.RED}Quitting...{Colors.END}")
                    break
                else:
                    # ignore other keys
                    continue

                # small sleep so terminal isn't overwhelmed; keep responsive
                time.sleep(0.01)

        except KeyboardInterrupt:
            # Ctrl-C: stop motors
            print("\nInterrupted by user (Ctrl-C).")
        finally:
            stop_all()
            print("Motors stopped. Exiting.")

    else:  # both mode
        # Both voice and keyboard mode
        print("Combined mode: Voice commands + Keyboard control")
        print("Voice commands: 'forward', 'back', 'left', 'right', 'stop'")
        print_instructions()

        speed = SPEED
        last_action = "stopped"
        stop_all()
        print(f">>> {last_action} (speed={speed:.2f})")

        try:
            while True:
                # Update status display
                print_status(speed, "both", last_action, voice_enabled=True)

                # Check for keyboard input
                ch = getch(timeout=0.01)  # Short timeout to not block voice

                if ch is not None:
                    # Handle special keys
                    if ch == '\x03':  # Ctrl+C
                        print(f"{Colors.RED}Interrupted by user (Ctrl-C).{Colors.END}")
                        break

                    # Handle keyboard input
                    c = ch.upper()

                    action_taken = False

                    # Movement controls
                    if c == "W":
                        set_both_backward(speed)
                        last_action = "backward"
                        action_taken = True
                    elif c == "S":
                        set_both_forward(speed)
                        last_action = "forward"
                        action_taken = True
                    elif c == "A":
                        spin_left(speed)
                        last_action = "spin_left"
                        action_taken = True
                    elif c == "D":
                        spin_right(speed)
                        last_action = "spin_right"
                        action_taken = True
                    elif c == "E":
                        forward_right(speed)
                        last_action = "forward_right"
                        action_taken = True
                    elif c == "Z":
                        backward_left(speed)
                        last_action = "backward_left"
                        action_taken = True
                    elif c == "C":
                        backward_right(speed)
                        last_action = "backward_right"
                        action_taken = True
                    elif c == " ":
                        stop_all()
                        last_action = "stopped"
                        action_taken = True

                    # Speed controls
                    elif c == "+" or c == "=":
                        old_speed = speed
                        speed = clamp(speed + 0.05)
                        if speed != old_speed:
                            print(f"{Colors.GREEN}Speed increased → {speed:.2f}{Colors.END}")
                        action_taken = True
                    elif c == "-":
                        old_speed = speed
                        speed = clamp(speed - 0.05)
                        if speed != old_speed:
                            print(f"{Colors.GREEN}Speed decreased → {speed:.2f}{Colors.END}")
                        action_taken = True
                    elif c.isdigit():
                        preset = int(c)
                        old_speed = speed
                        speed = set_speed_preset(preset, speed)
                        if speed != old_speed:
                            print(f"{Colors.GREEN}Speed preset {preset} → {speed:.2f}{Colors.END}")
                        action_taken = True

                    # System controls
                    elif c == "H":
                        print_comprehensive_help()
                        clear_screen()
                        print_instructions()
                        action_taken = True
                    elif c == "R":
                        speed = SPEED
                        print(f"{Colors.GREEN}Speed reset to default: {speed:.2f}{Colors.END}")
                        action_taken = True
                    elif c == "I":
                        print_system_info()
                        clear_screen()
                        print_instructions()
                        action_taken = True
                    elif c == "Q":
                        print(f"{Colors.RED}Quitting...{Colors.END}")
                        break

                    if action_taken:
                        time.sleep(0.01)
                        continue

                # Check for voice input (non-blocking)
                try:
                    text = mic.listen()
                    if text:
                        print(f"{Colors.BOLD}[YOU]:{Colors.END}", text)

                        # Motor commands first
                        m_reply = check_robot_command(text, speed)
                        if m_reply:
                            if m_reply == "SPEED_UP":
                                old_speed = speed
                                speed = clamp(speed + 0.05)
                                if speed != old_speed:
                                    play_audio(tts.speak(clean_text_for_tts(f"Speed increased to {speed:.2f}")))
                                    print(f"{Colors.GREEN}Voice: Speed increased → {speed:.2f}{Colors.END}")
                                continue
                            elif m_reply == "SPEED_DOWN":
                                old_speed = speed
                                speed = clamp(speed - 0.05)
                                if speed != old_speed:
                                    play_audio(tts.speak(clean_text_for_tts(f"Speed decreased to {speed:.2f}")))
                                    print(f"{Colors.GREEN}Voice: Speed decreased → {speed:.2f}{Colors.END}")
                                continue
                            elif m_reply == "SPEED_MAX":
                                speed = 1.0
                                play_audio(tts.speak(clean_text_for_tts("Full speed")))
                                print(f"{Colors.GREEN}Voice: Full speed{Colors.END}")
                                continue
                            elif m_reply == "SPEED_MIN":
                                speed = 0.1
                                play_audio(tts.speak(clean_text_for_tts("Slow speed")))
                                print(f"{Colors.GREEN}Voice: Slow speed{Colors.END}")
                                continue
                            else:
                                play_audio(tts.speak(clean_text_for_tts(m_reply)))
                                continue

                        # Otherwise use LLM
                        reply = ask_ollama(text, args.model, args.url)
                        play_audio(tts.speak(clean_text_for_tts(reply)))
                except:
                    # Voice input failed, continue with keyboard
                    pass

        except KeyboardInterrupt:
            print("\nInterrupted by user (Ctrl-C).")
        finally:
            stop_all()
            print("Motors stopped. Exiting.")


if __name__ == "__main__":
    main()
