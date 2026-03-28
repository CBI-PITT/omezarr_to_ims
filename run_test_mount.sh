#!/usr/bin/env bash

set -euo pipefail

PYTHON_BIN="/root/miniconda3/envs/omezarr_to_ims/bin/python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -ne 1 ]; then
    printf 'Usage: %s <mountpoint>\n' "$0"
    exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/mount_test_fs.py" "$1"
