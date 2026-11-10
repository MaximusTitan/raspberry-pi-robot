#!/bin/bash
# Run robot.py with pyenv Python (has MediaPipe installed)
# This script properly passes through environment for audio/display

# Kill any existing robot processes and free the port
sudo pkill -f "python.*robot.py" 2>/dev/null
sleep 1
sudo fuser -k 8080/tcp 2>/dev/null
sleep 1

# Run with pyenv Python, preserving environment
sudo -E env "PATH=$PATH" \
    "DISPLAY=$DISPLAY" \
    "XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}" \
    "PULSE_SERVER=${PULSE_SERVER:-unix:/run/user/$(id -u)/pulse/native}" \
    ~/.pyenv/shims/python3 ~/robot.py "$@"
