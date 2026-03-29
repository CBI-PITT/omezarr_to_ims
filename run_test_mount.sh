#!/usr/bin/env bash

set -euo pipefail

PYTHON_BIN="/root/miniconda3/envs/omezarr_to_ims/bin/python"

if [ "$#" -ne 1 ]; then
    printf 'Usage: %s <mountpoint>\n' "$0"
    exit 1
fi

exec "$PYTHON_BIN" -m mount_test_fs "$1"
