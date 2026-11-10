#!/usr/bin/env python3
# motor_gamepad_control_swapped.py
# RT = Backward, LT = Forward
# Left Stick = steering with swapped spin directions

import pygame
import sys

from motor_a_control import (
    left_motor_forward, left_motor_backward, left_motor_stop,
    right_motor_forward, right_motor_backward, right_motor_stop
)

# CONFIG
DEADZONE = 0.15
MAX_SPEED = 0.8

# XBOX COMMON MAPPING
AXIS_LX = 0
AXIS_RT = 5
AXIS_LT = 2

def dz(v):
    return 0 if abs(v) < DEADZONE else v

def stop_all_motors():
    left_motor_stop()
    right_motor_stop()

def main():
    pygame.init()
    pygame.joystick.init()

    if pygame.joystick.get_count() == 0:
        print("No gamepad detected.")
        sys.exit(1)

    js = pygame.joystick.Joystick(0)
    js.init()

    print("=== SWAPPED MOTOR CONTROL ===")
    print("RT = Backward")
    print("LT = Forward")
    print("Left Stick (X axis): right spin / left spin (swapped)")
    print("----------------------------------------------")

    clock = pygame.time.Clock()

    try:
        while True:
            pygame.event.pump()

            lx = js.get_axis(AXIS_LX)
            rt = js.get_axis(AXIS_RT)
            lt = js.get_axis(AXIS_LT)

            # Normalize triggers
            if rt < 0: rt = (rt + 1) / 2
            if lt < 0: lt = (lt + 1) / 2

            lx = dz(lx)

            # SAFETY: if both pressed -> STOP
            if rt > 0.2 and lt > 0.2:
                stop_all_motors()
                print("STOP (RT + LT pressed)")
                clock.tick(30)
                continue

            # ─────────────────────────────
            # LT → FORWARD (SWAPPED LOGIC)
            # ─────────────────────────────
            if lt > 0.1:
                speed = lt * MAX_SPEED

                if lx > 0.2:
                    # Stick right = spin LEFT (SWAPPED)
                    left_motor_backward(speed)
                    right_motor_forward(speed)
                    print(f"Spin LEFT (Forward) | speed={speed:.2f}")

                elif lx < -0.2:
                    # Stick left = spin RIGHT (SWAPPED)
                    left_motor_forward(speed)
                    right_motor_backward(speed)
                    print(f"Spin RIGHT (Forward) | speed={speed:.2f}")

                else:
                    # Straight FORWARD
                    left_motor_forward(speed)
                    right_motor_forward(speed)
                    print(f"FORWARD | speed={speed:.2f}")

            # ─────────────────────────────
            # RT → BACKWARD (SWAPPED LOGIC)
            # ─────────────────────────────
            elif rt > 0.1:
                speed = rt * MAX_SPEED

                if lx > 0.2:
                    # Stick right = spin LEFT while reversing
                    left_motor_forward(speed)
                    right_motor_backward(speed)
                    print(f"Spin LEFT (Backward) | speed={speed:.2f}")

                elif lx < -0.2:
                    # Stick left = spin RIGHT while reversing
                    left_motor_backward(speed)
                    right_motor_forward(speed)
                    print(f"Spin RIGHT (Backward) | speed={speed:.2f}")

                else:
                    # Straight BACKWARD
                    left_motor_backward(speed)
                    right_motor_backward(speed)
                    print(f"BACKWARD | speed={speed:.2f}")

            # ─────────────────────────────
            # NO TRIGGER → STOP
            # ─────────────────────────────
            else:
                stop_all_motors()

            clock.tick(30)

    except KeyboardInterrupt:
        print("Interrupted.")

    finally:
        stop_all_motors()
        pygame.quit()
        print("Motors stopped.")

if __name__ == "__main__":
    main()
