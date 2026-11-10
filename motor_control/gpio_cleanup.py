#!/usr/bin/env python3

from gpiozero import PWMOutputDevice, OutputDevice
import time

# Force cleanup of GPIO pins used by motors
pins = [12, 13, 23, 24, 16, 21]

print("Cleaning up GPIO pins...")

try:
    # Try to create devices to claim and then close them
    devices = []
    for pin in pins:
        try:
            # Try PWM first
            device = PWMOutputDevice(pin)
            device.value = 0
            device.close()
        except:
            try:
                # Try regular output device
                device = OutputDevice(pin)
                device.off()
                device.close()
            except Exception as e:
                print(f"Could not clean pin {pin}: {e}")

    print("GPIO cleanup completed.")
    time.sleep(1)

except Exception as e:
    print(f"Error during cleanup: {e}")




