#!/bin/bash

# Install zap2xml-manager
# Usage: ./install.sh

set -e

INSTALL_DIR="/opt/zap2xml-manager"
VENV_DIR="$INSTALL_DIR/venv"
BIN_LINK="/usr/local/bin/zap2xml-manager"

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

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: Please run as root (sudo ./install.sh)"
    exit 1
fi

# Check for Python
if ! command -v python3 &> /dev/null; then
    echo "Python3 not found. Installing..."
    install_packages
fi

# Check for venv module
if ! python3 -m venv --help &> /dev/null; then
    echo "python3-venv not found. Installing..."
    install_packages
fi

echo "Python3: $(python3 --version)"
echo ""

# Pull latest changes if in a git repo
if [ -d ".git" ]; then
    echo "Pulling latest updates..."
    git pull || echo "Warning: git pull failed, continuing with local files"
    echo ""
fi

# Create install directory
echo "Setting up installation directory..."
mkdir -p "$INSTALL_DIR"

# Copy source files
cp -r zap2xml_manager "$INSTALL_DIR/"
cp pyproject.toml "$INSTALL_DIR/"

# Create/update virtual environment
echo "Creating virtual environment..."
python3 -m venv "$VENV_DIR" --clear

# Install package in venv
echo "Installing zap2xml-manager..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install "$INSTALL_DIR"

# Create symlink for easy access
echo "Creating command symlink..."
rm -f "$BIN_LINK"
ln -s "$VENV_DIR/bin/zap2xml-manager" "$BIN_LINK"

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
