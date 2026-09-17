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

# Validate the built payload before changing an existing installation.
command -v node >/dev/null 2>&1 || { echo "ERROR: Node.js is required to validate the panel."; exit 1; }
node "$SOURCE_DIR/validate-panel.mjs" "$SOURCE_DIR"

# Create CEP extensions directory if it doesn't exist
mkdir -p "$HOME/Library/Application Support/Adobe/CEP/extensions"

# Preserve an existing installation instead of deleting its files.
if [ -e "$TARGET_DIR.previous" ] || [ -L "$TARGET_DIR.previous" ]; then
    echo "ERROR: Move the previous installation backup aside first: $TARGET_DIR.previous"
    exit 1
fi
if [ -e "$TARGET_DIR" ] || [ -L "$TARGET_DIR" ]; then
    echo "Preserving existing installation at $TARGET_DIR.previous"
    mv "$TARGET_DIR" "$TARGET_DIR.previous"
fi

# Create symbolic link
echo "Creating symbolic link..."
echo "  From: $SOURCE_DIR"
echo "  To:   $TARGET_DIR"
if ! ln -s "$SOURCE_DIR" "$TARGET_DIR"; then
    echo ""
    echo "ERROR: Failed to create symbolic link."
    echo "Trying to copy files instead..."
    cp -R "$SOURCE_DIR" "$TARGET_DIR"
fi

node "$SOURCE_DIR/validate-panel.mjs" "$TARGET_DIR"

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
