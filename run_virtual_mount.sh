#!/usr/bin/env bash

set -euo pipefail

PYTHON_BIN="/root/miniconda3/envs/omezarr_to_ims/bin/python"

if [ "$#" -ne 4 ]; then
    printf 'Usage: %s <mountpoint> <shell.h5> <affine_manifest.json> <zarr_map.json>\n' "$0"
    exit 1
fi

exec "$PYTHON_BIN" -m mount_virtual_hdf5 "$1" "$2" "$3" "$4"
