#!/usr/bin/env python3 deez

from gpiozero import PWMOutputDevice, OutputDevice
from time import sleep

# ----------------------------------------
# GPIO PIN SETUP (BCM mode)
# ----------------------------------------

# LEFT MOTOR (Motor A)
ENA = PWMOutputDevice(12)   # Speed control (PWM)
IN1 = OutputDevice(23)      # Direction +
IN2 = OutputDevice(24)      # Direction -

# RIGHT MOTOR (Motor B)
ENB = PWMOutputDevice(13)   # Speed control (PWM)
IN3 = OutputDevice(16)      # Direction +
IN4 = OutputDevice(21)      # Direction -

# ----------------------------------------
# MOTOR FUNCTIONS
# ----------------------------------------

def left_motor_forward(speed=0.2):
    IN1.on()
    IN2.off()
    ENA.value = speed

def left_motor_backward(speed=0.2):
    IN1.off()
    IN2.on()
    ENA.value = speed

def left_motor_stop():
    IN1.off()
    IN2.off()
    ENA.value = 0

def right_motor_forward(speed=0.2):
    IN3.on()
    IN4.off()
    ENB.value = speed

def right_motor_backward(speed=0.2):
    IN3.off()
    IN4.on()
    ENB.value = speed

def right_motor_stop():
    IN3.off()
    IN4.off()
    ENB.value = 0

def all_stop():
    left_motor_stop()
    right_motor_stop()

# ----------------------------------------
# TEST SEQUENCE
# ----------------------------------------

if __name__ == "__main__":
    try:
        print("FORWARD both motors for 6 seconds")
        left_motor_forward(0.2)
        right_motor_forward(0.2)
        sleep(6)

        print("STOP for 2 seconds")
        all_stop()
        sleep(1)

        print("BACKWARD both motors for 6 seconds")
        left_motor_backward(0.2)
        right_motor_backward(0.2)
        sleep(6)

        print("STOP for 2 seconds")
        all_stop()
        sleep(2)

        print("Done.")

    except KeyboardInterrupt:
        all_stop()
        print("Stopped by user.")
