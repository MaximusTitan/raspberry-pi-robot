#!/bin/bash
# Robot control wrapper script
# This ensures the correct Python environment is used with sudo

PYENV_PYTHON="/home/admin/.pyenv/shims/python3"
ROBOT_SCRIPT="/home/admin/robot.py"

# Pass all arguments to the robot script
sudo "$PYENV_PYTHON" "$ROBOT_SCRIPT" "$@"
