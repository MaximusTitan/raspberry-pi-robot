#!/bin/bash
# Enhanced wrapper script for the Robot Control System
# Features: Voice AI + Keyboard Motor Control with enhanced interface

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🤖 Robot Control System Launcher"
echo "================================="
echo "Features:"
echo "  • Voice commands with AI responses"
echo "  • WASD keyboard control with diagonals"
echo "  • Real-time status display"
echo "  • Speed presets and fine control"
echo "  • Comprehensive help system"
echo ""
echo "Note: GPIO access requires root privileges on Raspberry Pi"
echo ""

# Check if we're on Raspberry Pi
if [ -f /proc/device-tree/model ] && grep -q "Raspberry Pi" /proc/device-tree/model; then
    echo "✅ Raspberry Pi detected"
else
    echo "⚠️  Not running on Raspberry Pi - GPIO features may not work"
fi

# Check if running as root (for GPIO)
if [ "$EUID" -eq 0 ]; then
    echo "✅ Running with root privileges (GPIO access enabled)"
else
    echo "⚠️  Not running as root - GPIO access may fail"
    echo "   Use 'sudo $0' for full functionality"
fi

echo ""
echo "Starting Robot Control System..."
echo "Press Ctrl+C to exit safely"
echo ""

# Export audio environment variables for sudo
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native"

# Run with appropriate privileges
# Usage: ./run_combined_control.sh [piper_model] [piper_config] [--vosk vosk_path] [other args]
# If no args provided, uses defaults from Python script
if [ "$EUID" -eq 0 ]; then
    cd /home/admin/ollama_piper && ./venv/bin/python /home/admin/combined_voice_keyboard_control.py "$@"
else
    # Use sudo -E to preserve environment variables (for audio)
    cd /home/admin/ollama_piper && sudo -E --preserve-env=XDG_RUNTIME_DIR,PULSE_SERVER,DBUS_SESSION_BUS_ADDRESS ./venv/bin/python /home/admin/combined_voice_keyboard_control.py "$@"
fi
