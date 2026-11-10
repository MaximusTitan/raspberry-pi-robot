#!/usr/bin/env python3
"""
sensor_raw.py -- Dual HC-SR04 using RPi.GPIO (no pigpio required)

Pins (BCM numbers used in code):
  SENSOR1_TRIG: GPIO20
  SENSOR1_ECHO: GPIO19  (via 1k/2k divider)
  SENSOR2_TRIG: GPIO5
  SENSOR2_ECHO: GPIO6   (via 1k/2k divider)
  LED:           GPIO18

Run: sudo python3 sensor_raw.py
"""

import time
import RPi.GPIO as GPIO

# --- Pins (BCM numbers) ---
SENSOR1_TRIG = 20  # GPIO20
SENSOR1_ECHO = 19  # GPIO19
SENSOR2_TRIG = 5   # GPIO5
SENSOR2_ECHO = 6   # GPIO6
LED_PIN = 18       # GPIO18

# --- Parameters ---
SPEED_OF_SOUND = 343.0  # m/s
MAX_DISTANCE_M = 3.0
DETECTION_THRESHOLD_M = 0.30
SAMPLE_INTERVAL = 0.20
TIMEOUT_SEC = 0.03  # 30ms timeout

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

# Setup pins
for trig in (SENSOR1_TRIG, SENSOR2_TRIG):
    GPIO.setup(trig, GPIO.OUT)
    GPIO.output(trig, GPIO.LOW)

for echo in (SENSOR1_ECHO, SENSOR2_ECHO):
    GPIO.setup(echo, GPIO.IN)

GPIO.setup(LED_PIN, GPIO.OUT)
GPIO.output(LED_PIN, GPIO.LOW)

def pulse_out(trig_pin):
    GPIO.output(trig_pin, GPIO.HIGH)
    time.sleep(0.00001)  # 10 microseconds
    GPIO.output(trig_pin, GPIO.LOW)

def wait_for_level(pin, level, timeout_s):
    deadline = time.monotonic_ns() + int(timeout_s * 1e9)
    while time.monotonic_ns() < deadline:
        if GPIO.input(pin) == level:
            return time.monotonic_ns()
    return None

def measure_distance(trig_pin, echo_pin):
    GPIO.output(trig_pin, GPIO.LOW)
    time.sleep(0.00005)
    pulse_out(trig_pin)
    t_rise = wait_for_level(echo_pin, 1, TIMEOUT_SEC)
    if t_rise is None:
        return None
    t_fall = wait_for_level(echo_pin, 0, TIMEOUT_SEC)
    if t_fall is None or t_fall <= t_rise:
        return None
    pulse_ns = t_fall - t_rise
    pulse_s = pulse_ns / 1e9
    distance_m = (pulse_s * SPEED_OF_SOUND) / 2.0
    if distance_m <= 0 or distance_m > MAX_DISTANCE_M:
        return None
    return distance_m

def format_distance(v):
    return "no reading" if v is None else f"{v:.03f} m"

def quick_check():
    d1 = measure_distance(SENSOR1_TRIG, SENSOR1_ECHO)
    d2 = measure_distance(SENSOR2_TRIG, SENSOR2_ECHO)
    return d1, d2

def main():
    try:
        print(f"SENSOR1: TRIG=GPIO{SENSOR1_TRIG}, ECHO=GPIO{SENSOR1_ECHO}")
        print(f"SENSOR2: TRIG=GPIO{SENSOR2_TRIG}, ECHO=GPIO{SENSOR2_ECHO}")
        d1, d2 = quick_check()
        if d1 is None:
            print("Warning: Sensor1 quick check returned no reading.")
        else:
            print(f"Sensor1 quick check: {d1:.03f} m")
        if d2 is None:
            print("Warning: Sensor2 quick check returned no reading.")
        else:
            print(f"Sensor2 quick check: {d2:.03f} m")

        print("Starting loop. Ctrl+C to stop.")
        while True:
            m1 = measure_distance(SENSOR1_TRIG, SENSOR1_ECHO)
            m2 = measure_distance(SENSOR2_TRIG, SENSOR2_ECHO)

            detected1 = (m1 is not None and 0.01 < m1 <= DETECTION_THRESHOLD_M)
            detected2 = (m2 is not None and 0.01 < m2 <= DETECTION_THRESHOLD_M)

            if detected1 or detected2:
                GPIO.output(LED_PIN, GPIO.HIGH)
            else:
                GPIO.output(LED_PIN, GPIO.LOW)

            s1_text = format_distance(m1)
            s2_text = format_distance(m2)
            mark1 = "<-- DETECTED" if detected1 else ""
            mark2 = "<-- DETECTED" if detected2 else ""
            print(f"S1: {s1_text:10} {mark1}    |    S2: {s2_text:10} {mark2}")

            time.sleep(SAMPLE_INTERVAL)
    except KeyboardInterrupt:
        print("Stopping.")
    finally:
        GPIO.output(LED_PIN, GPIO.LOW)
        GPIO.cleanup()

if __name__ == "__main__":
    main()
