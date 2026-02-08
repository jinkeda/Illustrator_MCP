#!/bin/bash
# ============================================
# Illustrator MCP CEP Extension Installer (macOS)
# ============================================

set -e

# Configuration
EXTENSION_ID="com.illustrator.mcp.panel"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/cep-extension"
TARGET_DIR="$HOME/Library/Application Support/Adobe/CEP/extensions/$EXTENSION_ID"

echo ""
echo "============================================="
echo " Illustrator MCP CEP Extension Installer"
echo "============================================="
echo ""

# Check if source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    echo "ERROR: Source directory not found: $SOURCE_DIR"
    echo "Make sure you're running this from the project root folder."
    exit 1
fi

# Check if dist folder exists (requires npm run build)
if [ ! -d "$SOURCE_DIR/dist" ]; then
    echo "ERROR: dist folder not found. You must build the extension first!"
    echo ""
    echo "Run these commands:"
    echo "  cd cep-extension"
    echo "  npm install"
    echo "  npm run build"
    echo "  cd .."
    echo ""
    echo "Then run this script again."
    exit 1
fi

# Create CEP extensions directory if it doesn't exist
mkdir -p "$HOME/Library/Application Support/Adobe/CEP/extensions"

# Remove existing installation if present
if [ -e "$TARGET_DIR" ]; then
    echo "Removing existing installation..."
    rm -rf "$TARGET_DIR"
fi

# Create symbolic link
echo "Creating symbolic link..."
echo "  From: $SOURCE_DIR"
echo "  To:   $TARGET_DIR"
ln -s "$SOURCE_DIR" "$TARGET_DIR"

if [ $? -ne 0 ]; then
    echo ""
    echo "ERROR: Failed to create symbolic link."
    echo "Trying to copy files instead..."
    cp -R "$SOURCE_DIR" "$TARGET_DIR"
fi

# Enable debug mode for both CSXS.11 and CSXS.12
echo ""
echo "Enabling CEP debug mode..."
defaults write com.adobe.CSXS.11 PlayerDebugMode 1
defaults write com.adobe.CSXS.12 PlayerDebugMode 1

echo ""
echo "============================================="
echo " Installation Complete!"
echo "============================================="
echo ""
echo "Next steps:"
echo "1. Open Adobe Illustrator"
echo "2. Go to Window > Extensions > MCP Control"
echo "3. Click 'Connect' in the panel"
echo ""
echo "To debug the panel, open Chrome and navigate to:"
echo "  http://localhost:8088"
echo ""
