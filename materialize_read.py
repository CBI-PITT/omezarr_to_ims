#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import json
import os
from functools import lru_cache

from affine_lookup import parse_manifest
from read_segments import resolve_read_segments
from zarr_backend import OmeZarrBackend, load_zarr_mapping

# Maximum number of fully-materialized chunk byte strings to keep in the LRU
# cache.  Each entry is one chunk worth of raw bytes (e.g. 32*128*128*2 = 1 MiB
# for uint16 with the default Imaris chunk sizes).
_CHUNK_CACHE_SIZE = 256


def _make_chunk_fetcher(backend, zarr_mapping):
    """Return a cached function that fetches and serializes a single chunk."""

    @lru_cache(maxsize=_CHUNK_CACHE_SIZE)
    def _fetch_chunk_bytes(dataset_path, chunk_origin, chunk_shape,
                           chunk_actual_shape, dtype):
        mapping_target = zarr_mapping["datasets"][dataset_path]
        chunk = backend.read_chunk(
            mapping_target,
            list(chunk_origin),
            list(chunk_shape),
            list(chunk_actual_shape),
        )
        return chunk.astype(dtype, copy=False).tobytes(order="C")

    return _fetch_chunk_bytes


def materialize_read(shell_file, manifest, zarr_mapping, backend, offset, length,
                     _chunk_cache=None):
    if _chunk_cache is None:
        _chunk_cache = _make_chunk_fetcher(backend, zarr_mapping)

    parts = []
    for segment in resolve_read_segments(manifest, offset, length):
        if segment["kind"] == "metadata":
            print(f"  metadata offset={segment['file_offset']} len={segment['length']}", flush=True)
            parts.append(os.pread(shell_file.fileno(), segment["length"], segment["file_offset"]))
            continue

        ds = segment["dataset_path"]
        grid_idx = segment["chunk_grid_index"]
        origin = segment["chunk_origin"]
        cached = (_chunk_cache.cache_info().hits if hasattr(_chunk_cache, 'cache_info') else None)
        chunk_bytes = _chunk_cache(
            ds,
            tuple(segment["chunk_origin"]),
            tuple(segment["chunk_shape"]),
            tuple(segment["chunk_actual_shape"]),
            segment["dtype"],
        )
        if cached is not None:
            hit = _chunk_cache.cache_info().hits > cached
        else:
            hit = None
        hit_label = " (cached)" if hit else " (fetched)" if hit is False else ""
        start = segment["intra_chunk_byte_offset"]
        end = start + segment["length"]
        print(f"  data {ds} chunk={grid_idx} origin={origin} "
              f"intra_offset={start} len={segment['length']}{hit_label}",
              flush=True)
        parts.append(chunk_bytes[start:end])

    return b"".join(parts)


def parse_args():
    parser = argparse.ArgumentParser(description="Materialize a virtual HDF5 file read from shell metadata and OME-Zarr data")
    parser.add_argument("shell", help="Path to the shell HDF5 file")
    parser.add_argument("manifest", help="Path to affine manifest JSON")
    parser.add_argument("zarr_map", help="Path to Zarr mapping JSON")
    parser.add_argument("offset", type=int, help="Read start byte offset")
    parser.add_argument("length", type=int, help="Read length in bytes")
    parser.add_argument(
        "--hex",
        action="store_true",
        help="Print the materialized bytes as hex instead of raw JSON metadata",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    manifest = parse_manifest(args.manifest)
    zarr_mapping = load_zarr_mapping(args.zarr_map)
    backend = OmeZarrBackend(zarr_mapping["store"])
    with open(args.shell, "rb") as shell_file:
        payload = materialize_read(shell_file, manifest, zarr_mapping, backend, args.offset, args.length)

    if args.hex:
        print(payload.hex())
    else:
        print(json.dumps({"offset": args.offset, "length": len(payload), "hex": payload.hex()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
