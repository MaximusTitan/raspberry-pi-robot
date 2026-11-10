#!/usr/bin/env python3
"""
sensor.py  -- Dual HC-SR04 support using gpiozero + pigpio pin factory.

Wiring (exact GPIO names used in code):
  SENSOR1_TRIG: GPIO20
  SENSOR1_ECHO: GPIO19  (via level shifter / 1k/2k divider)
  SENSOR2_TRIG: GPIO5
  SENSOR2_ECHO: GPIO6   (via level shifter / 1k/2k divider)
  LED:           GPIO18

Notes:
 - Ensure pigpiod is running: sudo systemctl start pigpiod
 - VCC and GND are shared between sensors (as you stated).
"""

import time
from gpiozero import DistanceSensor, LED, Device
from gpiozero.pins.pigpio import PiGPIOFactory
from gpiozero.exc import GPIOZeroError

# Force use of pigpio for accurate timing
Device.pin_factory = PiGPIOFactory()

# --- GPIO assignments (exact names) ---
SENSOR1_TRIG = "GPIO20"
SENSOR1_ECHO = "GPIO19"
SENSOR2_TRIG = "GPIO5"
SENSOR2_ECHO = "GPIO6"
LED_GPIO = "GPIO18"

# --- parameters ---
MAX_DISTANCE_METERS = 3.0
DETECTION_THRESHOLD_M = 0.30
SAMPLE_INTERVAL = 0.20

# Create sensors and LED
try:
    sensor1 = DistanceSensor(echo=SENSOR1_ECHO, trigger=SENSOR1_TRIG,
                             max_distance=MAX_DISTANCE_METERS,
                             threshold_distance=DETECTION_THRESHOLD_M)
    sensor2 = DistanceSensor(echo=SENSOR2_ECHO, trigger=SENSOR2_TRIG,
                             max_distance=MAX_DISTANCE_METERS,
                             threshold_distance=DETECTION_THRESHOLD_M)
    led = LED(LED_GPIO)
except GPIOZeroError as e:
    print("GPIOZero error creating devices:", e)
    raise
except Exception as e:
    print("Unexpected error creating devices:", e)
    raise

def quick_check(timeout=1.2):
    """Quick ping both sensors to ensure they respond."""
    deadline = time.time() + timeout
    s1_ok = False
    s2_ok = False
    s1_m = None
    s2_m = None
    while time.time() < deadline and (not s1_ok or not s2_ok):
        try:
            v1 = sensor1.value
            if v1 is not None:
                meters1 = v1 * MAX_DISTANCE_METERS
                if 0.01 < meters1 <= MAX_DISTANCE_METERS:
                    s1_ok = True
                    s1_m = meters1
        except Exception:
            pass

        try:
            v2 = sensor2.value
            if v2 is not None:
                meters2 = v2 * MAX_DISTANCE_METERS
                if 0.01 < meters2 <= MAX_DISTANCE_METERS:
                    s2_ok = True
                    s2_m = meters2
        except Exception:
            pass

        time.sleep(0.05)

    return (s1_ok, s1_m), (s2_ok, s2_m)

def format_distance(value):
    if value is None:
        return "no reading"
    return f"{value:.03f} m"

def main():
    print("Forcing pigpio pin factory. Ensure pigpiod is running (sudo systemctl start pigpiod).")
    print(f"SENSOR1: TRIG={SENSOR1_TRIG}, ECHO={SENSOR1_ECHO}")
    print(f"SENSOR2: TRIG={SENSOR2_TRIG}, ECHO={SENSOR2_ECHO}")
    ok1, ok2 = quick_check()
    (s1_ok, s1_m), (s2_ok, s2_m) = ok1, ok2

    if not s1_ok:
        print("Warning: Sensor1 did not respond during quick check.")
        print(" - Check Sensor1 TRIG/ECHO wiring and level shifter/divider.")
    if not s2_ok:
        print("Warning: Sensor2 did not respond during quick check.")
        print(" - Check Sensor2 TRIG/ECHO wiring and level shifter/divider.")
    if not (s1_ok or s2_ok):
        print("No sensors responded. Verify wiring, common ground, and pigpiod.")
        # continue anyway to allow hot-plugging; you can return here if prefer:
        # return

    print("Starting loop. Ctrl+C to stop.")
    try:
        while True:
            try:
                v1 = sensor1.value
                m1 = None if v1 is None else v1 * MAX_DISTANCE_METERS
            except Exception as e:
                m1 = None
                print("Sensor1 read error:", e)

            try:
                v2 = sensor2.value
                m2 = None if v2 is None else v2 * MAX_DISTANCE_METERS
            except Exception as e:
                m2 = None
                print("Sensor2 read error:", e)

            detected1 = (m1 is not None and 0.01 < m1 <= DETECTION_THRESHOLD_M)
            detected2 = (m2 is not None and 0.01 < m2 <= DETECTION_THRESHOLD_M)

            # LED on if either sensor detects
            if detected1 or detected2:
                led.on()
            else:
                led.off()

            # Print neat per-sensor output with detection marker
            s1_text = format_distance(m1)
            s2_text = format_distance(m2)
            mark1 = "<-- DETECTED" if detected1 else ""
            mark2 = "<-- DETECTED" if detected2 else ""
            print(f"S1: {s1_text:10} {mark1}    |    S2: {s2_text:10} {mark2}")

            time.sleep(SAMPLE_INTERVAL)
    except KeyboardInterrupt:
        print("Stopping.")
    finally:
        led.off()

if __name__ == "__main__":
    main()
