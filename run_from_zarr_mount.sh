#!/usr/bin/env bash

set -euo pipefail

PYTHON_BIN="/root/miniconda3/envs/omezarr_to_ims/bin/python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -ne 2 ]; then
    printf 'Usage: %s <mountpoint> <store.ome.zarr>\n' "$0"
    exit 1
fi

MOUNTPOINT="$1"
STORE_PATH="$2"

if [ ! -d "$MOUNTPOINT" ]; then
    printf 'Mountpoint does not exist or is not a directory: %s\n' "$MOUNTPOINT"
    exit 1
fi

if [ ! -e "$STORE_PATH" ]; then
    printf 'OME-Zarr store path does not exist: %s\n' "$STORE_PATH"
    exit 1
fi

STORE_NAME="$(basename "$STORE_PATH")"
BASE_NAME="${STORE_NAME%.ome.zarr}"
if [ "$BASE_NAME" = "$STORE_NAME" ]; then
    BASE_NAME="${STORE_NAME%.zarr}"
fi

SAFE_NAME="$(printf '%s' "$BASE_NAME" | tr ' /' '__')"
SHELL_PATH="/tmp/${SAFE_NAME}.ims"
MANIFEST_PATH="${SHELL_PATH}.affine_manifest.json"
ZARR_MAP_PATH="${MANIFEST_PATH}.zarr_map.json"

printf 'Rebuilding shell artifacts for %s\n' "$STORE_PATH"
printf 'Shell file: %s\n' "$SHELL_PATH"
printf 'Affine manifest: %s\n' "$MANIFEST_PATH"
printf 'Zarr map: %s\n' "$ZARR_MAP_PATH"

"$PYTHON_BIN" -m build_hdf5_shell "$SHELL_PATH" --imaris-from-zarr "$STORE_PATH"
"$PYTHON_BIN" -m extract_affine_manifest "$SHELL_PATH"
"$PYTHON_BIN" -m build_zarr_mapping "$MANIFEST_PATH" "$STORE_PATH"

exec "$SCRIPT_DIR/run_virtual_mount.sh" "$MOUNTPOINT" "$SHELL_PATH" "$MANIFEST_PATH" "$ZARR_MAP_PATH"
