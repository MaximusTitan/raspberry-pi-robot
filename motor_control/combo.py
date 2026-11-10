#!/usr/bin/env python3
# voice_keyboard_motor.py
# Combined keyboard + Vosk voice control for motors.
# Run with: sudo python3 voice_keyboard_motor.py
#
# Requirements:
#   pip install vosk PyAudio
#   Vosk model directory (e.g. "model") must exist and contain a Vosk model.
#
# Behavior:
#   - Keyboard: WASD (with the W/S swap behavior from your keyboard script),
#     space stop, +/- speed change, Q to quit.
#   - Voice: say "forward", "backward", "left", "right", "stop", "faster", "slower", "quit" etc.
#     Voice commands toggle motion until a stop or other voice command.
#
# Ensure microphone is available and Vosk model path is set below.

import sys
import termios
import tty
import select
import time
import threading
import queue
import json

# Audio / Vosk
import pyaudio
from vosk import Model, KaldiRecognizer

# Import your motor control functions (adjust names if your motor_a_control.py differs)
from motor_a_control import (
    left_motor_forward, left_motor_backward, left_motor_stop,
    right_motor_forward, right_motor_backward, right_motor_stop,
    all_stop
)

# ---------------------------
# Config
# ---------------------------
MODEL_PATH = "model"       # path to your Vosk model directory
SAMPLE_RATE = 16000
CHUNK = 4000               # frames per buffer for pyaudio
DEFAULT_SPEED = 0.4       # 0.0 - 1.0

# ---------------------------
# Motor control helpers
# ---------------------------
def set_both_forward(speed=DEFAULT_SPEED):
    left_motor_forward(speed)
    right_motor_forward(speed)

def set_both_backward(speed=DEFAULT_SPEED):
    left_motor_backward(speed)
    right_motor_backward(speed)

def spin_left(speed=DEFAULT_SPEED):
    left_motor_backward(speed)
    right_motor_forward(speed)

def spin_right(speed=DEFAULT_SPEED):
    left_motor_forward(speed)
    right_motor_backward(speed)

def stop_all():
    # prefer per-motor stops for explicitness; use all_stop() if you want global stop
    try:
        left_motor_stop()
        right_motor_stop()
    except Exception:
        # fallback to all_stop if provided
        try:
            all_stop()
        except Exception:
            pass

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

# ---------------------------
# Keyboard helpers (non-blocking single character)
# ---------------------------
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

def print_instructions(start_speed):
    print("Combined Keyboard + Voice control (press Q to quit):")
    print("Keyboard:")
    print("  W: BACKWARD (swapped)")
    print("  S: FORWARD  (swapped)")
    print("  A: turn/ spin left")
    print("  D: turn/ spin right")
    print("  Space: stop")
    print("  + / - : increase / decrease speed")
    print("  Q or Ctrl-C: quit and stop motors")
    print("")
    print("Voice (examples): 'forward', 'backward', 'stop', 'left', 'right', 'faster', 'slower', 'quit'")
    print(f"Starting speed: {start_speed:.2f}\n")

# ---------------------------
# Voice thread
# ---------------------------
def voice_listen_thread(model_path, out_queue, stop_event):
    """Thread that listens on microphone and puts recognized text into out_queue."""
    try:
        print("Loading Vosk model...")
        model = Model(model_path)
    except Exception as e:
        print("Failed to load Vosk model:", e)
        out_queue.put(("__error__", f"Failed to load model: {e}"))
        return

    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    pa = pyaudio.PyAudio()

    try:
        stream = pa.open(format=pyaudio.paInt16,
                         channels=1,
                         rate=SAMPLE_RATE,
                         input=True,
                         frames_per_buffer=CHUNK)
    except Exception as e:
        out_queue.put(("__error__", f"Failed to open microphone: {e}"))
        pa.terminate()
        return

    stream.start_stream()
    print("Voice: Listening on microphone...")

    try:
        while not stop_event.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            if recognizer.AcceptWaveform(data):
                res = recognizer.Result()
                try:
                    text = json.loads(res).get("text", "").strip().lower()
                except Exception:
                    text = ""
                if text:
                    # push recognized text to queue
                    out_queue.put(("voice", text))
    except Exception as e:
        out_queue.put(("__error__", f"Voice thread error: {e}"))
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        pa.terminate()

# ---------------------------
# Command processing
# ---------------------------
def process_command(source, text, state):
    """
    source: 'keyboard' or 'voice'
    text: normalized command text (single character for keyboard or string for voice)
    state: dict containing 'speed', 'last_action', 'last_source'
    Returns True if should quit program.
    """
    speed = state["speed"]
    quit_program = False

    # If source is keyboard we pass single character commands (uppercase)
    if source == "keyboard":
        c = text.upper()
        if c == "W":
            # W => backward (swapped)
            set_both_backward(speed)
            state["last_action"] = "backward"
            state["last_source"] = "keyboard"
        elif c == "S":
            set_both_forward(speed)
            state["last_action"] = "forward"
            state["last_source"] = "keyboard"
        elif c == "A":
            spin_left(speed)
            state["last_action"] = "spin_left"
            state["last_source"] = "keyboard"
        elif c == "D":
            spin_right(speed)
            state["last_action"] = "spin_right"
            state["last_source"] = "keyboard"
        elif c == " ":
            stop_all()
            state["last_action"] = "stopped"
            state["last_source"] = "keyboard"
        elif c in ("+", "="):
            old_speed = state["speed"]
            state["speed"] = clamp(state["speed"] + 0.05)
            if state["speed"] != old_speed:
                print(f"speed increased -> {state['speed']:.2f}")
        elif c == "-":
            old_speed = state["speed"]
            state["speed"] = clamp(state["speed"] - 0.05)
            if state["speed"] != old_speed:
                print(f"speed decreased -> {state['speed']:.2f}")
        elif c == "Q":
            quit_program = True
        # On keyboard we don't print extra text here; main loop prints status
        return quit_program

    # Source is 'voice'
    # text may contain multiple words; use keyword matching
    t = text.lower().strip()
    # synonyms mapping
    if t == "":
        return False

    # Quit
    if any(word in t for word in ("quit", "exit", "stop program", "shutdown", "bye", "goodbye")):
        # treat 'stop program' that also includes 'stop' as quit if includes 'program' or 'quit' specifically
        if "stop program" in t or "quit" in t or "exit" in t or "shutdown" in t:
            quit_program = True
            return True

    # Movement
    if any(word in t for word in ("forward", "go forward", "move forward", "ahead")):
        set_both_forward(state["speed"])
        state["last_action"] = "forward"
        state["last_source"] = "voice"
    elif any(word in t for word in ("back", "backward", "reverse", "go back")):
        set_both_backward(state["speed"])
        state["last_action"] = "backward"
        state["last_source"] = "voice"
    elif any(word in t for word in ("left", "turn left", "spin left")):
        spin_left(state["speed"])
        state["last_action"] = "spin_left"
        state["last_source"] = "voice"
    elif any(word in t for word in ("right", "turn right", "spin right")):
        spin_right(state["speed"])
        state["last_action"] = "spin_right"
        state["last_source"] = "voice"
    elif any(word in t for word in ("stop", "halt", "brake", "pause")):
        stop_all()
        state["last_action"] = "stopped"
        state["last_source"] = "voice"
    # Speed control
    elif any(word in t for word in ("faster", "speed up", "increase", "increase speed")):
        old_speed = state["speed"]
        state["speed"] = clamp(state["speed"] + 0.05)
        if state["speed"] != old_speed:
            print(f"speed increased -> {state['speed']:.2f}")
        # if currently moving due to voice, reapply motion at new speed
        if state["last_source"] == "voice" and state["last_action"] != "stopped":
            # reapply action
            reapply_action(state)
    elif any(word in t for word in ("slower", "slow down", "decrease", "decrease speed")):
        old_speed = state["speed"]
        state["speed"] = clamp(state["speed"] - 0.05)
        if state["speed"] != old_speed:
            print(f"speed decreased -> {state['speed']:.2f}")
        if state["last_source"] == "voice" and state["last_action"] != "stopped":
            reapply_action(state)
    else:
        # unrecognized voice phrase; ignore (could enhance with fuzzy matching)
        print(f"Voice recognized but unhandled: '{t}'")

    return quit_program

def reapply_action(state):
    """Reapply the current last_action at current speed (useful after speed change)."""
    a = state["last_action"]
    s = state["speed"]
    if a == "forward":
        set_both_forward(s)
    elif a == "backward":
        set_both_backward(s)
    elif a == "spin_left":
        spin_left(s)
    elif a == "spin_right":
        spin_right(s)
    elif a == "stopped":
        stop_all()

# ---------------------------
# Main
# ---------------------------
def main():
    # initial state
    state = {
        "speed": DEFAULT_SPEED,
        "last_action": "stopped",   # forward/backward/spin_left/spin_right/stopped
        "last_source": None         # 'keyboard' or 'voice'
    }

    print_instructions(state["speed"])

    # Ensure motors stopped at program start
    stop_all()
    print(f">>> {state['last_action']} (speed={state['speed']:.2f})")

    # set up voice thread and queue
    voice_q = queue.Queue()
    stop_event = threading.Event()
    vthread = threading.Thread(target=voice_listen_thread, args=(MODEL_PATH, voice_q, stop_event), daemon=True)
    vthread.start()

    quit_program = False
    try:
        while not quit_program:
            # 1) keyboard input - non-blocking
            ch = getch(timeout=0.05)

            if ch is not None:
                # handle keyboard key immediately
                # we pass the char to process_command which sets state and motors
                quit_program = process_command("keyboard", ch, state)
                print(f">>> {state['last_action']} (speed={state['speed']:.2f})")
                # small sleep to avoid flooding
                time.sleep(0.01)
                # after processing keyboard, continue loop (keyboard input has priority)
                continue
            else:
                # No keyboard key pressed right now.
                # If last input was keyboard and motors were running due to keyboard, then stop motors now.
                if state["last_source"] == "keyboard" and state["last_action"] != "stopped":
                    stop_all()
                    state["last_action"] = "stopped"
                    print(f">>> {state['last_action']} (speed={state['speed']:.2f})")

            # 2) process any voice messages from queue
            try:
                # non-blocking get of all queued voice messages (use latest)
                while True:
                    src, payload = voice_q.get_nowait()
                    if src == "__error__":
                        print("Error from voice thread:", payload)
                        # do not quit automatically, but user may check logs
                        continue
                    if src == "voice":
                        recognized_text = payload
                        print(f"Voice recognized: '{recognized_text}'")
                        # process the voice command
                        should_quit = process_command("voice", recognized_text, state)
                        print(f">>> {state['last_action']} (speed={state['speed']:.2f})")
                        if should_quit:
                            quit_program = True
                    # mark task done if needed
                    voice_q.task_done()
            except queue.Empty:
                pass

            # short sleep to keep loop responsive
            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nInterrupted by user (Ctrl-C).")
    finally:
        # request voice thread stop
        stop_event.set()
        # give it a moment
        time.sleep(0.2)
        stop_all()
        print("Motors stopped. Exiting.")

if __name__ == "__main__":
    main()
