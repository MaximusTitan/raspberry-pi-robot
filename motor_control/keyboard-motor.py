#!/usr/bin/env python3
# keyboard-motor.py
# Keyboard control for WASD to drive motors defined in motor_a_control.py
# Run with: sudo python3 keyboard-motor.py

import sys
import termios
import tty
import select
import time
from motor_a_control import (
    left_motor_forward, left_motor_backward, left_motor_stop,
    right_motor_forward, right_motor_backward, right_motor_stop,
    all_stop
)

# Default speed (0.0 - 1.0)
SPEED = 0.4

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
    # all_stop() can be used if defined to stop everything; using per-motor stop is explicit
    # all_stop()

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
    print("WASD keyboard control (press Q to quit):")
    print("  W: BACKWARD (swapped)")
    print("  S: FORWARD  (swapped)")
    print("  A: turn/ spin left")
    print("  D: turn/ spin right")
    print("  Space: stop")
    print("  + / - : increase / decrease speed")
    print("  Q or Ctrl-C: quit and stop motors")
    print(f"Starting speed: {SPEED}\n")

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

if __name__ == "__main__":
    try:
        print_instructions()
        speed = SPEED
        last_action = "stopped"
        last_printed = None
        # ensure motors are stopped on start
        stop_all()
        print(f">>> {last_action} (speed={speed:.2f})")

        while True:
            ch = getch(timeout=0.05)

            if ch is None:
                # No key currently pressed — ensure motors stopped if they were running
                if last_action != "stopped":
                    stop_all()
                    last_action = "stopped"
                    print(f">>> {last_action} (speed={speed:.2f})")
                # continue loop waiting for a real key press
                continue

            # Normalize to uppercase to accept lowercase letters too
            c = ch.upper()

            # NOTE: W and S intentionally swapped: W => backward, S => forward
            if c == "W":
                # W now moves BACKWARD
                set_both_backward(speed)
                last_action = "backward"
            elif c == "S":
                # S now moves FORWARD
                set_both_forward(speed)
                last_action = "forward"
            elif c == "A":
                spin_left(speed)
                last_action = "spin_left"
            elif c == "D":
                spin_right(speed)
                last_action = "spin_right"
            elif c == " ":
                stop_all()
                last_action = "stopped"
            elif c == "+" or c == "=":
                old_speed = speed
                speed = clamp(speed + 0.05)
                if speed != old_speed:
                    print(f"speed increased -> {speed:.2f}")
                # if a movement key is being held, motors will be driven on next key event;
                # do not reapply motors here unless a movement key is currently active.
                # (We only act on explicit key input to satisfy "only do it on key input")
            elif c == "-":
                old_speed = speed
                speed = clamp(speed - 0.05)
                if speed != old_speed:
                    print(f"speed decreased -> {speed:.2f}")
            elif c == "Q":
                print("Quitting...")
                break
            else:
                # ignore other keys
                continue

            # Print status when action changes (or after recognized key)
            print(f">>> {last_action} (speed={speed:.2f})")

            # small sleep so terminal isn't overwhelmed; keep responsive
            time.sleep(0.01)

    except KeyboardInterrupt:
        # Ctrl-C: stop motors
        print("\nInterrupted by user (Ctrl-C).")
    finally:
        stop_all()
        print("Motors stopped. Exiting.")
