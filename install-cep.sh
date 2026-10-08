#!/bin/bash
# Python 3.10+ is already required by the server.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/install_cep.py"
