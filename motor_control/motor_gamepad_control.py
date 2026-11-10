#!/usr/bin/env python3
# motor_gamepad_control_v2.py
# Improved gamepad/controller support for Raspberry Pi motors using motor_a_control.py and pygame.
#
# - Auto-detects axes/hats/buttons and prints a quick mapping for debugging.
# - Two drive modes:
#     TANK (left stick -> left motor, right stick -> right motor) if >= 2 vertical axes detected
#     DIFF (one stick for forward/back + steering) fallback otherwise
# - Deadzone, invert options, and speed multiplier
# - D-PAD and buttons for quick commands (stop/quit/speed +/-)
#
# Run: sudo python3 motor_gamepad_control_v2.py
# Install pygame if needed: sudo apt install -y python3-pygame  OR  pip3 install pygame

import os
import sys
import time
import pygame
from motor_a_control import (
    left_motor_forward, left_motor_backward, left_motor_stop,
    right_motor_forward, right_motor_backward, right_motor_stop,
    all_stop
)

# ---------- Config ----------
# Choose whether to show raw debug info (True = verbose)
DEBUG_AXES = False

# Deadzone around 0 for axis noise
DEADZONE = 0.12

# Speed multiplier
speed_multiplier = 0.6
SPEED_STEP = 0.05
MIN_SPEED = 0.05
MAX_SPEED = 1.0

# Button indexes (common defaults, may differ for your controller)
BUTTON_STOP  = 0   # A
BUTTON_QUIT  = 7   # START
BUTTON_DEC   = 4   # LB
BUTTON_INC   = 5   # RB

# Hat index (D-PAD)
HAT_INDEX = 0

# Axis inversion defaults (set True if pushing stick up gives -1)
INVERT_AXIS = True

# If your controller has two vertical axes dedicated to left/right sticks, set this True.
# The script will try to auto-detect; you can override here if needed:
FORCE_TANK_MODE = None  # None => auto, True => tank, False => diff

# If your controller reports many axes, these heuristics will try to pick left/right vertical axes:
POSSIBLE_LEFT_VERT_CANDIDATES  = [1, 0]   # common: 1 on Xbox/PS, fallback 0
POSSIBLE_RIGHT_VERT_CANDIDATES = [3, 4, 2]  # common: 3 or 4 depending on controller/driver
# ----------------------------

def clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))

def deadzone_filter(v):
    if abs(v) < DEADZONE:
        return 0.0
    return v

def axis_to_speed(v, invert=False):
    """Convert axis value (-1..1) with optional invert to motor speed command (signed).
       Positive => forward, Negative => backward. Zero => stopped.
    """
    if invert:
        v = -v
    v = deadzone_filter(v)
    # keep as signed float -1..1
    return clamp(abs(v)) * (1 if v >= 0 else -1)

def left_cmd_from_signed(signed_speed):
    if signed_speed > 0:
        left_motor_forward(signed_speed)
    elif signed_speed < 0:
        left_motor_backward(-signed_speed)
    else:
        left_motor_stop()

def right_cmd_from_signed(signed_speed):
    if signed_speed > 0:
        right_motor_forward(signed_speed)
    elif signed_speed < 0:
        right_motor_backward(-signed_speed)
    else:
        right_motor_stop()

def both_forward(s):
    left_motor_forward(s)
    right_motor_forward(s)

def both_backward(s):
    left_motor_backward(s)
    right_motor_backward(s)

def spin_left(s):
    left_motor_backward(s)
    right_motor_forward(s)

def spin_right(s):
    left_motor_forward(s)
    right_motor_backward(s)

def stop_all():
    all_stop()

def print_instructions():
    print("=== Gamepad Motor Control (v2) ===")
    print("Modes: TANK (L-stick -> left motor, R-stick -> right motor) or DIFF (single-stick differential).")
    print("Controls (defaults - adjust with printed mapping if needed):")
    print(" - D-PAD Up/Down: both forward / both backward")
    print(" - D-PAD Left/Right: spin left / spin right")
    print(" - Button A (index 0): stop (panic)")
    print(" - Start (index 7): quit")
    print(" - LB / RB (4 / 5): speed - / +")
    print(" - Use CTRL-C to quit anytime.\n")

def detect_layout(joystick):
    """
    Print axes/hats/buttons and try to pick vertical axes for left/right sticks.
    Returns (mode, left_axis_index or None, right_axis_index or None).
      mode: 'TANK' or 'DIFF'
      For DIFF, we will return primary_axis and secondary_axis where:
         primary -> forward/back
         secondary -> left/right (turn)
    """
    n_axes = joystick.get_numaxes()
    n_buttons = joystick.get_numbuttons()
    n_hats = joystick.get_numhats()
    name = joystick.get_name()
    print(f"Detected joystick: {name}")
    print(f"Axes: {n_axes}, Buttons: {n_buttons}, Hats: {n_hats}")

    # Print axis indexes and current values (snapshot)
    axes_snapshot = {}
    for i in range(n_axes):
        try:
            axes_snapshot[i] = joystick.get_axis(i)
        except Exception:
            axes_snapshot[i] = 0.0
    print("Axis snapshot (index: value):")
    for i, v in axes_snapshot.items():
        print(f"  {i}: {v:.3f}")

    print("Buttons count:", n_buttons)
    print("Hats count:", n_hats)
    if n_hats > 0:
        print("Hat example:", joystick.get_hat(0))

    # Heuristic: If there are at least 4 axes, assume tank mode with left vertical at candidate[0] and right vertical candidate[0]
    if FORCE_TANK_MODE is True:
        mode = "TANK"
    elif FORCE_TANK_MODE is False:
        mode = "DIFF"
    else:
        mode = "TANK" if n_axes >= 4 else "DIFF"

    left_axis = None
    right_axis = None

    if mode == "TANK":
        # choose best matching left and right vertical axes using candidates list
        for cand in POSSIBLE_LEFT_VERT_CANDIDATES:
            if cand < n_axes:
                left_axis = cand
                break
        for cand in POSSIBLE_RIGHT_VERT_CANDIDATES:
            if cand < n_axes:
                right_axis = cand
                break

        # If still ambiguous, fallback to axis 1 and 3 if available
        if left_axis is None and n_axes > 1:
            left_axis = 1
        if right_axis is None and n_axes > 3:
            right_axis = 3
        # If right not present, maybe controller exposes only two axes (0/1) -> fall back to DIFF
        if right_axis is None:
            print("Could not find a good right-stick vertical axis; switching to DIFF mode.")
            mode = "DIFF"

    if mode == "DIFF":
        # Primary axis: forward/back. Prefer axis 1 or 0
        primary = None
        for cand in POSSIBLE_LEFT_VERT_CANDIDATES:
            if cand < n_axes:
                primary = cand
                break
        if primary is None and n_axes > 0:
            primary = 1 if n_axes > 1 else 0
        # Secondary axis: turn (left/right). Prefer axis 0 or 2
        secondary = None
        for cand in POSSIBLE_RIGHT_VERT_CANDIDATES:
            if cand < n_axes:
                secondary = cand
                break
        if secondary is None:
            # try a different fallback
            secondary = 0 if primary != 0 else (1 if n_axes > 1 else None)
        left_axis = primary
        right_axis = secondary

    print(f"Selected mode: {mode}")
    print(f"Left-axis index: {left_axis}    Right/Turn-axis index: {right_axis}")
    print("If these are wrong, set FORCE_TANK_MODE or edit POSSIBLE_* lists in the script.\n")
    return mode, left_axis, right_axis

def apply_tank_mode(joystick, left_axis_idx, right_axis_idx, speed_mul):
    # read axis values, map each to signed speed, apply
    lv = joystick.get_axis(left_axis_idx) if left_axis_idx is not None else 0.0
    rv = joystick.get_axis(right_axis_idx) if right_axis_idx is not None else 0.0
    lsigned = axis_to_speed(lv, invert=INVERT_AXIS) * speed_mul
    rsigned = axis_to_speed(rv, invert=INVERT_AXIS) * speed_mul
    # axis_to_speed returns signed magnitude with sign (positive forward)
    left_cmd_from_signed(lsigned)
    right_cmd_from_signed(rsigned)
    return lsigned, rsigned, lv, rv

def apply_diff_mode(joystick, primary_idx, secondary_idx, speed_mul):
    # primary axis: forward/back control (signed)
    # secondary axis: left/right turning control (signed)
    pv = joystick.get_axis(primary_idx) if primary_idx is not None else 0.0
    sv = joystick.get_axis(secondary_idx) if secondary_idx is not None else 0.0
    forward = axis_to_speed(pv, invert=INVERT_AXIS)  # -1..1 signed
    turn    = axis_to_speed(sv, invert=False)        # treat turning as signed
    # Combine for left/right: left = forward + turn, right = forward - turn
    # clamp to [-1,1]
    left = clamp(forward + turn, -1.0, 1.0) * speed_mul
    right = clamp(forward - turn, -1.0, 1.0) * speed_mul
    left_cmd_from_signed(left)
    right_cmd_from_signed(right)
    return left, right, pv, sv

def main():
    global speed_multiplier
    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("No joystick/gamepad detected. Please connect one and try again.")
        pygame.joystick.quit()
        pygame.quit()
        sys.exit(1)

    js = pygame.joystick.Joystick(0)
    js.init()

    print_instructions()
    mode, left_axis_idx, right_axis_idx = detect_layout(js)

    last_print = time.time()
    last_left = 0.0
    last_right = 0.0

    try:
        clock = pygame.time.Clock()
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.JOYBUTTONDOWN:
                    b = event.button
                    if DEBUG_AXES:
                        print(f"[E] Button down: {b}")
                    if b == BUTTON_STOP:
                        stop_all()
                        if DEBUG_AXES:
                            print("[E] STOP button pressed")
                    elif b == BUTTON_QUIT:
                        running = False
                        if DEBUG_AXES:
                            print("[E] QUIT button pressed")
                    elif b == BUTTON_DEC:
                        speed_multiplier = clamp(speed_multiplier - SPEED_STEP, MIN_SPEED, MAX_SPEED)
                        print(f"speed_multiplier -> {speed_multiplier:.2f}")
                    elif b == BUTTON_INC:
                        speed_multiplier = clamp(speed_multiplier + SPEED_STEP, MIN_SPEED, MAX_SPEED)
                        print(f"speed_multiplier -> {speed_multiplier:.2f}")

                elif event.type == pygame.JOYHATMOTION:
                    hat = js.get_hat(HAT_INDEX)
                    x, y = hat
                    if y == 1:
                        both_forward(speed_multiplier)
                        if DEBUG_AXES:
                            print("[E] Hat UP -> both forward")
                    elif y == -1:
                        both_backward(speed_multiplier)
                        if DEBUG_AXES:
                            print("[E] Hat DOWN -> both backward")
                    elif x == -1:
                        spin_left(speed_multiplier)
                        if DEBUG_AXES:
                            print("[E] Hat LEFT -> spin left")
                    elif x == 1:
                        spin_right(speed_multiplier)
                        if DEBUG_AXES:
                            print("[E] Hat RIGHT -> spin right")

            # Poll axes and apply selected mode
            if mode == "TANK":
                # If right axis missing (None) but we are in tank mode, fallback to DIFF
                if right_axis_idx is None:
                    left_speed, right_speed, _, _ = apply_diff_mode(js, left_axis_idx, left_axis_idx, speed_multiplier)
                else:
                    left_speed, right_speed, lv_raw, rv_raw = apply_tank_mode(js, left_axis_idx, right_axis_idx, speed_multiplier)
                    if DEBUG_AXES:
                        # Print raw values sometimes
                        now = time.time()
                        if now - last_print > 0.25:
                            print(f"RAW axes L[{left_axis_idx}]={lv_raw:.3f} R[{right_axis_idx}]={rv_raw:.3f}")
                            last_print = now
            else:
                left_speed, right_speed, p_raw, s_raw = apply_diff_mode(js, left_axis_idx, right_axis_idx, speed_multiplier)
                if DEBUG_AXES:
                    now = time.time()
                    if now - last_print > 0.25:
                        print(f"RAW primary[{left_axis_idx}]={p_raw:.3f} secondary[{right_axis_idx}]={s_raw:.3f}")
                        last_print = now

            # Optionally print concise change-only feedback
            if (abs(left_speed - last_left) > 0.02) or (abs(right_speed - last_right) > 0.02):
                print(f"LEFT {left_speed:+.2f}  |  RIGHT {right_speed:+.2f}  |  mult={speed_multiplier:.2f}")
                last_left = left_speed
                last_right = right_speed

            clock.tick(30)  # 30 Hz loop

    except KeyboardInterrupt:
        print("\nInterrupted by user (Ctrl-C).")

    finally:
        stop_all()
        print("Motors stopped. Cleaning up pygame.")
        js.quit()
        pygame.joystick.quit()
        pygame.quit()

if __name__ == "__main__":
    main()
