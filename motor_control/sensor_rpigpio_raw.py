#!/usr/bin/env python3
import time
import RPi.GPIO as GPIO

TRIG = 20   # GPIO20
ECHO = 19   # GPIO19 (via resistor divider)
LED = 18

GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIG, GPIO.OUT)
GPIO.setup(ECHO, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
GPIO.setup(LED, GPIO.OUT)
GPIO.output(TRIG, False)
GPIO.output(LED, False)

SAMPLE_INTERVAL = 0.5
DETECTION_THRESHOLD_M = 0.30
SPEED_OF_SOUND = 343.0  # m/s

def get_distance(timeout=0.03):
    # Send 10µs pulse
    GPIO.output(TRIG, True)
    time.sleep(0.00001)
    GPIO.output(TRIG, False)

    start_time = time.perf_counter()
    # wait for echo high
    while GPIO.input(ECHO) == 0:
        if (time.perf_counter() - start_time) > timeout:
            return None
    pulse_start = time.perf_counter()

    # wait for echo low
    while GPIO.input(ECHO) == 1:
        if (time.perf_counter() - pulse_start) > 0.05:
            return None
    pulse_end = time.perf_counter()

    pulse_duration = pulse_end - pulse_start
    distance_m = (pulse_duration * SPEED_OF_SOUND) / 2.0
    return distance_m

try:
    print("Raw measurement loop. Ctrl+C to stop.")
    while True:
        dist = get_distance(timeout=0.03)
        if dist is None:
            print("DEBUG: No echo detected (None).")
            GPIO.output(LED, False)
        else:
            print(f"Distance: {dist:.3f} m")
            GPIO.output(LED, dist <= DETECTION_THRESHOLD_M)
        time.sleep(SAMPLE_INTERVAL)
except KeyboardInterrupt:
    print("Exiting.")
finally:
    GPIO.output(LED, False)
    GPIO.cleanup()
