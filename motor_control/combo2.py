#!/usr/bin/env python3

# ============================================================
# DEBUG SECTION (added for diagnosing venv/sudo/vosk issues)
# ============================================================
import sys
print("========== DEBUG INFO ==========")
print("sys.executable =", sys.executable)
print("sys.version =", sys.version)
print("sys.path (first 8) =", sys.path[:8])

try:
    import vosk
    print("VOSK IMPORT OK:", getattr(vosk, "__file__", "no __file__"))
except Exception as e:
    print("VOSK IMPORT ERROR:", repr(e))

print("================================\n")
# ============================================================


# voice_keyboard_motor.py
# Combined keyboard + Vosk voice control for motors.

import termios
import tty
import select
import time
import threading
import queue
import json
import pyaudio
from vosk import Model, KaldiRecognizer

from motor_a_control import (
    left_motor_forward, left_motor_backward, left_motor_stop,
    right_motor_forward, right_motor_backward, right_motor_stop,
    all_stop
)

MODEL_PATH = "model"
SAMPLE_RATE = 16000
CHUNK = 4000
DEFAULT_SPEED = 0.4


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
    try:
        left_motor_stop()
        right_motor_stop()
    except Exception:
        try:
            all_stop()
        except Exception:
            pass

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def getch(timeout=0.05):
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        r, _, _ = select.select([fd], [], [], timeout)
        if r:
            return sys.stdin.read(1)
        return None
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def print_instructions(speed):
    print("Combined Keyboard + Voice control (Q to quit):\n")
    print("Keyboard:")
    print("  W = BACKWARD (swapped)")
    print("  S = FORWARD  (swapped)")
    print("  A = left spin")
    print("  D = right spin")
    print("  Space = stop")
    print("  + / - = speed adjust")
    print("  Q = quit")
    print("\nVoice commands: forward, backward, left, right, stop, faster, slower, quit")
    print(f"\nStarting speed: {speed}\n")


def voice_listen_thread(model_path, out_q, stop_event):
    try:
        print("Voice thread: Loading Vosk model...")
        model = Model(model_path)
    except Exception as e:
        out_q.put(("__error__", f"Model load error: {e}"))
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
        out_q.put(("__error__", f"Mic open error: {e}"))
        pa.terminate()
        return

    stream.start_stream()
    print("Voice thread: Listening...")

    try:
        while not stop_event.is_set():
            data = stream.read(CHUNK, exception_on_overflow=False)
            if recognizer.AcceptWaveform(data):
                txt = json.loads(recognizer.Result()).get("text", "").strip().lower()
                if txt:
                    out_q.put(("voice", txt))
    except Exception as e:
        out_q.put(("__error__", f"Voice thread error: {e}"))
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except:
            pass
        pa.terminate()


def reapply_action(state):
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


def process_command(source, text, state):
    speed = state["speed"]
    quit_flag = False

    if source == "keyboard":
        c = text.upper()

        if c == "W":
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
            state["speed"] = clamp(speed + 0.05)
            print(f"Speed increased -> {state['speed']:.2f}")

        elif c == "-":
            state["speed"] = clamp(speed - 0.05)
            print(f"Speed decreased -> {state['speed']:.2f}")

        elif c == "Q":
            quit_flag = True

        return quit_flag

    t = text.lower().strip()

    if any(w in t for w in ("quit", "exit", "shutdown")):
        return True

    if any(w in t for w in ("forward", "ahead")):
        set_both_forward(state["speed"])
        state["last_action"] = "forward"
        state["last_source"] = "voice"

    elif any(w in t for w in ("back", "reverse", "backward")):
        set_both_backward(state["speed"])
        state["last_action"] = "backward"
        state["last_source"] = "voice"

    elif any(w in t for w in ("left", "spin left", "turn left")):
        spin_left(state["speed"])
        state["last_action"] = "spin_left"
        state["last_source"] = "voice"

    elif any(w in t for w in ("right", "spin right", "turn right")):
        spin_right(state["speed"])
        state["last_action"] = "spin_right"
        state["last_source"] = "voice"

    elif any(w in t for w in ("stop", "halt", "pause")):
        stop_all()
        state["last_action"] = "stopped"
        state["last_source"] = "voice"

    elif any(w in t for w in ("faster", "speed up", "increase")):
        old = state["speed"]
        state["speed"] = clamp(old + 0.05)
        print(f"Speed increased -> {state['speed']:.2f}")
        if state["last_source"] == "voice" and state["last_action"] != "stopped":
            reapply_action(state)

    elif any(w in t for w in ("slower", "slow down", "decrease")):
        old = state["speed"]
        state["speed"] = clamp(old - 0.05)
        print(f"Speed decreased -> {state['speed']:.2f}")
        if state["last_source"] == "voice" and state["last_action"] != "stopped":
            reapply_action(state)

    else:
        print(f"Voice recognized but unhandled: '{t}'")

    return quit_flag


def main():
    state = {
        "speed": DEFAULT_SPEED,
        "last_action": "stopped",
        "last_source": None
    }

    print_instructions(state["speed"])
    stop_all()
    print(f">>> {state['last_action']} (speed={state['speed']:.2f})")

    voice_q = queue.Queue()
    stop_event = threading.Event()

    vthread = threading.Thread(
        target=voice_listen_thread,
        args=(MODEL_PATH, voice_q, stop_event),
        daemon=True
    )
    vthread.start()

    quit_flag = False

    try:
        while not quit_flag:
            ch = getch(timeout=0.05)

            if ch:
                quit_flag = process_command("keyboard", ch, state)
                print(f">>> {state['last_action']} (speed={state['speed']:.2f})")
                time.sleep(0.01)
                continue
            else:
                if state["last_source"] == "keyboard" and state["last_action"] != "stopped":
                    stop_all()
                    state["last_action"] = "stopped"
                    print(f">>> {state['last_action']} (speed={state['speed']:.2f})")

            try:
                while True:
                    src, payload = voice_q.get_nowait()

                    if src == "__error__":
                        print("VOICE THREAD ERROR:", payload)
                        continue

                    if src == "voice":
                        print(f"Voice recognized: '{payload}'")
                        if process_command("voice", payload, state):
                            quit_flag = True
                        print(f">>> {state['last_action']} (speed={state['speed']:.2f})")

                    voice_q.task_done()
            except queue.Empty:
                pass

            time.sleep(0.01)

    except KeyboardInterrupt:
        print("\nKeyboardInterrupt")

    finally:
        stop_event.set()
        time.sleep(0.2)
        stop_all()
        print("Motors stopped. Exiting.")


if __name__ == "__main__":
    main()
