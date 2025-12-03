#!/bin/bash

# Install zap2xml-manager
# Usage: ./install.sh

set -e

echo "Installing zap2xml-manager..."

# Check if pip is available
if ! command -v pip &> /dev/null; then
    echo "Error: pip is not installed"
    exit 1
fi

# Install the package in editable mode (for development) or regular mode
if [ "$1" == "--dev" ]; then
    echo "Installing in development mode..."
    pip install -e ".[dev]"
else
    echo "Installing package..."
    pip install .
fi

echo ""
echo "Installation complete!"
echo ""
echo "Usage:"
echo "  zap2xml-manager              # Launch TUI (if textual installed)"
echo "  zap2xml-manager serve        # Run as background server"
echo "  zap2xml-manager download     # One-time EPG download"
echo "  zap2xml-manager config       # View/set configuration"
echo ""
echo "Examples:"
echo "  zap2xml-manager config --lineup 'USA-LINEUP-X' --postal 12345"
echo "  zap2xml-manager serve -i 12 --refresh-now"
