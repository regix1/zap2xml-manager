#!/bin/bash

# Install zap2xml-manager
# Usage: ./install.sh

set -e

echo "==================================="
echo "  zap2xml-manager installer"
echo "==================================="
echo ""

# Detect package manager
install_packages() {
    if command -v apt-get &> /dev/null; then
        echo "Detected apt package manager..."
        apt-get update
        apt-get install -y python3 python3-pip python3-venv git
    elif command -v dnf &> /dev/null; then
        echo "Detected dnf package manager..."
        dnf install -y python3 python3-pip git
    elif command -v yum &> /dev/null; then
        echo "Detected yum package manager..."
        yum install -y python3 python3-pip git
    elif command -v pacman &> /dev/null; then
        echo "Detected pacman package manager..."
        pacman -Sy --noconfirm python python-pip git
    elif command -v apk &> /dev/null; then
        echo "Detected apk package manager..."
        apk add --no-cache python3 py3-pip git
    else
        echo "Error: Could not detect package manager."
        echo "Please install python3, pip, and git manually."
        exit 1
    fi
}

# Check if running as root for package installation
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "Note: Not running as root. May need sudo for system packages."
        return 1
    fi
    return 0
}

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python3 not found. Installing..."
    if check_root; then
        install_packages
    else
        echo "Error: Python3 is not installed."
        echo "Run: sudo apt-get install python3 python3-pip python3-venv"
        exit 1
    fi
fi

# Check for pip
if ! python3 -m pip --version &> /dev/null; then
    echo "pip not found. Installing..."
    if check_root; then
        install_packages
    else
        echo "Error: pip is not installed."
        echo "Run: sudo apt-get install python3-pip"
        exit 1
    fi
fi

echo "Python3: $(python3 --version)"
echo "pip: $(python3 -m pip --version)"
echo ""

# Pull latest changes if in a git repo
if [ -d ".git" ]; then
    echo "Pulling latest updates..."
    git pull || echo "Warning: git pull failed, continuing with local files"
    echo ""
fi

# Uninstall old version first
echo "Removing old installation..."
python3 -m pip uninstall -y zap2xml-manager 2>/dev/null || true

# Install the package with force reinstall
echo "Installing zap2xml-manager..."
python3 -m pip install . --force-reinstall --no-cache-dir --break-system-packages 2>/dev/null || \
python3 -m pip install . --force-reinstall --no-cache-dir

echo ""
echo "==================================="
echo "  Installation complete!"
echo "==================================="
echo ""
echo "Usage:"
echo "  zap2xml-manager serve        # Run as background server"
echo "  zap2xml-manager download     # One-time EPG download"
echo "  zap2xml-manager config       # View/set configuration"
echo ""
echo "Quick start:"
echo "  zap2xml-manager config --lineup 'USA-LINEUP-X' --postal 12345"
echo "  zap2xml-manager serve -i 12 --refresh-now"
echo ""
