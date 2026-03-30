#!/usr/bin/env bash

set -euo pipefail

PYTHON_BIN="/h20/home/lab/miniconda3/envs/omezarr_to_ims/bin/python"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
    printf 'Usage: %s [options] <mountpoint> <store.ome.zarr>\n' "$0"
    printf '\nOptions:\n'
    printf '  --imaris-chunks     Use fixed Imaris chunk sizes (32x128x128) instead of Zarr native\n'
    printf '  --full-histograms   Compute histograms from every resolution level\n'
    exit 1
}

SHELL_EXTRA_ARGS=()
POSITIONAL=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        --imaris-chunks)
            SHELL_EXTRA_ARGS+=("--imaris-chunks")
            shift
            ;;
        --full-histograms)
            SHELL_EXTRA_ARGS+=("--full-histograms")
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            POSITIONAL+=("$1")
            shift
            ;;
    esac
done

if [ "${#POSITIONAL[@]}" -ne 2 ]; then
    usage
fi

MOUNTPOINT="${POSITIONAL[0]}"
STORE_PATH="${POSITIONAL[1]}"

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

"$PYTHON_BIN" -m build_hdf5_shell "$SHELL_PATH" --imaris-from-zarr "$STORE_PATH" "${SHELL_EXTRA_ARGS[@]+"${SHELL_EXTRA_ARGS[@]}"}"
"$PYTHON_BIN" -m extract_affine_manifest "$SHELL_PATH"
"$PYTHON_BIN" -m build_zarr_mapping "$MANIFEST_PATH" "$STORE_PATH"

exec "$SCRIPT_DIR/run_virtual_mount.sh" "$MOUNTPOINT" "$SHELL_PATH" "$MANIFEST_PATH" "$ZARR_MAP_PATH"
