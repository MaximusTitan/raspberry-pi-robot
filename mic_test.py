#!/home/admin/.pyenv/versions/3.12.12/bin/python3
"""
Mic + Vosk STT tester.

Shows a live mic level meter, what Vosk hears as you speak (partial),
and the final sentence with per-word confidence.

Run (as your normal user, NOT sudo, so Bluetooth audio is reachable):
    ./mic_test.py
"""
import json
import os
import select
import subprocess
import sys
import termios
import time
import tty
import wave
from collections import deque

import numpy as np
import pyaudio
from vosk import KaldiRecognizer, Model, SetLogLevel

MODEL_PATH = "/home/admin/rasp/motor_control/model"
RATE = 16000
CHUNK = 1600                     # 0.1 s
REPLAY_SECONDS = 5
PLAYBACK_FILE = "/tmp/mic_test_last.wav"

C = {"g": "\033[92m", "y": "\033[93m", "r": "\033[91m", "c": "\033[96m",
     "d": "\033[2m", "b": "\033[1m", "x": "\033[0m"}

HELP = (f"{C['b']}Keys:{C['x']} "
        "[space] pause/resume  [d] next mic  [+/-] gain  "
        "[p] BT profile (HFP mic / A2DP)  [r] replay last 5s  "
        "[c] clear  [h] help  [q] quit")


def say(msg=""):
    # Clear the live status line, print a message, the status line is redrawn next tick
    sys.stdout.write("\r\033[K" + msg + "\n")
    sys.stdout.flush()


def input_devices(pa):
    devs = []
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info["maxInputChannels"] > 0:
            devs.append((i, info["name"]))
    return devs


def bt_card():
    out = subprocess.run(["pactl", "list", "short", "cards"],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) > 1 and parts[1].startswith("bluez_card"):
            return parts[1]
    return None


def bt_profile(card):
    out = subprocess.run(["pactl", "list", "cards"], capture_output=True, text=True).stdout
    in_card = False
    for line in out.splitlines():
        if line.strip().startswith("Name:"):
            in_card = line.split(":", 1)[1].strip() == card
        elif in_card and "Active Profile:" in line:
            return line.split(":", 1)[1].strip()
    return "?"


def toggle_bt_profile():
    card = bt_card()
    if not card:
        say(f"{C['r']}No Bluetooth audio card found.{C['x']}")
        return
    cur = bt_profile(card)
    new = "a2dp-sink" if cur.startswith("headset") else "headset-head-unit"
    r = subprocess.run(["pactl", "set-card-profile", card, new], capture_output=True, text=True)
    if r.returncode != 0 and new == "headset-head-unit":
        new = "headset-head-unit-cvsd"
        r = subprocess.run(["pactl", "set-card-profile", card, new], capture_output=True, text=True)
    if r.returncode == 0:
        say(f"{C['c']}BT profile: {cur} -> {new}{C['x']}"
            + ("  (mic mode: lower audio quality, but the mic is active)" if new.startswith("headset")
               else "  (music mode: many headsets send NO mic audio here)"))
        # Point the default input at the BT mic if it exists now
        srcs = subprocess.run(["pactl", "list", "short", "sources"],
                              capture_output=True, text=True).stdout
        for line in srcs.splitlines():
            name = line.split()[1]
            if name.startswith("bluez_input"):
                subprocess.run(["pactl", "set-default-source", name])
                break
    else:
        say(f"{C['r']}Profile switch failed: {r.stderr.strip()}{C['x']}")


def save_and_play(frames):
    if not frames:
        say("Nothing recorded yet.")
        return
    with wave.open(PLAYBACK_FILE, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(frames))
    say(f"{C['c']}Playing back last {REPLAY_SECONDS}s of mic audio "
        f"(saved to {PLAYBACK_FILE})...{C['x']}")
    subprocess.run(["paplay", PLAYBACK_FILE])


def meter(rms_db, gain):
    # -60 dBFS .. 0 dBFS -> 30 chars
    n = int(max(0, min(30, (rms_db + 60) / 2)))
    col = C["r"] if rms_db > -6 else C["g"] if rms_db > -40 else C["y"]
    return f"{col}{'#' * n}{C['x']}{'.' * (30 - n)} {rms_db:6.1f} dB  gain x{gain:.1f}"


def main():
    if os.geteuid() == 0:
        print(f"{C['y']}Warning: running as root. Bluetooth audio usually isn't "
              f"reachable from sudo - run as your normal user.{C['x']}")

    SetLogLevel(-1)
    print("Loading Vosk model...")
    model = Model(MODEL_PATH)

    # Silence ALSA/JACK spam from PyAudio while probing devices
    devnull = os.open(os.devnull, os.O_WRONLY)
    saved_err = os.dup(2)
    os.dup2(devnull, 2)
    pa = pyaudio.PyAudio()
    os.dup2(saved_err, 2)

    devs = input_devices(pa)
    if not devs:
        print(f"{C['r']}No input devices found. Is the BT headset connected?{C['x']}")
        return
    # Prefer pulse/default (routes to PipeWire -> Bluetooth mic)
    dev_pos = next((k for k, (_, n) in enumerate(devs) if n in ("pulse", "default")), 0)

    print("Input devices:")
    for i, n in devs:
        print(f"  [{i}] {n}")
    card = bt_card()
    if card:
        prof = bt_profile(card)
        print(f"Bluetooth card: {card}  profile: {prof}")
        if not prof.startswith("headset"):
            print(f"{C['y']}  Tip: press [p] to switch to HFP if Vosk hears nothing - "
                  f"most BT headsets only send mic audio in HFP mode.{C['x']}")
    print(HELP)
    print()

    stream = None

    def open_stream():
        nonlocal stream
        if stream:
            stream.stop_stream()
            stream.close()
        idx, name = devs[dev_pos]
        stream = pa.open(rate=RATE, channels=1, format=pyaudio.paInt16, input=True,
                         input_device_index=idx, frames_per_buffer=CHUNK)
        say(f"{C['c']}Listening on [{idx}] {name} @ {RATE} Hz{C['x']}")

    open_stream()
    rec = KaldiRecognizer(model, RATE)
    rec.SetWords(True)

    gain = 1.0
    paused = False
    history = deque(maxlen=int(REPLAY_SECONDS * RATE / CHUNK))
    partial = ""
    heard = 0

    fd = sys.stdin.fileno()
    old_term = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        while True:
            # ---- keyboard ----
            if select.select([sys.stdin], [], [], 0)[0]:
                k = sys.stdin.read(1)
                if k in ("q", "Q", "\x1b"):
                    break
                elif k == " ":
                    paused = not paused
                    say(f"{C['y']}Paused{C['x']}" if paused else f"{C['g']}Resumed{C['x']}")
                elif k in ("+", "="):
                    gain = min(gain + 0.5, 10.0)
                elif k in ("-", "_"):
                    gain = max(gain - 0.5, 0.5)
                elif k == "d":
                    dev_pos = (dev_pos + 1) % len(devs)
                    open_stream()
                    rec.Reset()
                elif k == "p":
                    toggle_bt_profile()
                    time.sleep(1.0)       # let PipeWire rebuild the nodes
                    open_stream()
                    rec.Reset()
                elif k == "r":
                    save_and_play(list(history))
                    stream.read(stream.get_read_available(), exception_on_overflow=False)
                elif k == "c":
                    sys.stdout.write("\033[2J\033[H")
                    print(HELP + "\n")
                elif k == "h":
                    say(HELP)

            # ---- audio ----
            data = stream.read(CHUNK, exception_on_overflow=False)
            if paused:
                sys.stdout.write(f"\r\033[K{C['d']}[paused - space to resume]{C['x']}")
                sys.stdout.flush()
                continue

            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32)
            if gain != 1.0:
                samples = np.clip(samples * gain, -32768, 32767)
                data = samples.astype(np.int16).tobytes()
            history.append(data)

            rms = np.sqrt(np.mean(samples ** 2)) if samples.size else 0.0
            rms_db = 20 * np.log10(max(rms, 1.0) / 32768)

            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                text = res.get("text", "").strip()
                partial = ""
                if text:
                    heard += 1
                    words = res.get("result", [])
                    confs = [w.get("conf", 0) for w in words]
                    avg = sum(confs) / len(confs) if confs else 0
                    col = C["g"] if avg > 0.85 else C["y"] if avg > 0.6 else C["r"]
                    detail = " ".join(
                        f"{w['word']}{C['d']}({w.get('conf', 0):.2f}){C['x']}" for w in words)
                    say(f"{C['b']}#{heard} HEARD:{C['x']} {col}\"{text}\"{C['x']}  "
                        f"avg conf {col}{avg:.2f}{C['x']}")
                    say(f"      {detail}")
            else:
                partial = json.loads(rec.PartialResult()).get("partial", "")

            line = meter(rms_db, gain)
            if partial:
                line += f"  {C['d']}…{partial[-40:]}{C['x']}"
            sys.stdout.write("\r\033[K" + line)
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_term)
        if stream:
            stream.stop_stream()
            stream.close()
        pa.terminate()
        print("\nBye.")


if __name__ == "__main__":
    main()
