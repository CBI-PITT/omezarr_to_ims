#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import json
from itertools import product
from pathlib import Path

import h5py
import numpy as np


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract chunk coordinates and file offsets from a chunked HDF5 dataset"
    )
    parser.add_argument("input", help="Path to the HDF5 shell file")
    parser.add_argument(
        "--dataset",
        default="/data",
        help="Dataset path to inspect inside the HDF5 file (default: /data)",
    )
    parser.add_argument(
        "--output",
        help="Path to write JSON chunk map output (default: <input>.chunk_map.json)",
    )
    return parser.parse_args()


def chunk_origins(shape, chunks):
    axes = [range(0, dim, chunk) for dim, chunk in zip(shape, chunks)]
    for coord in product(*axes):
        yield tuple(int(value) for value in coord)


def main():
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(input_path.suffix + ".chunk_map.json")

    with h5py.File(input_path, "r") as h5file:
        dataset = h5file[args.dataset]
        if dataset.chunks is None:
            raise ValueError(f"Dataset is not chunked: {args.dataset}")

        shape = tuple(int(value) for value in dataset.shape)
        chunks = tuple(int(value) for value in dataset.chunks)
        dtype = np.dtype(dataset.dtype)

        chunk_entries = []
        for coord in chunk_origins(shape, chunks):
            info = dataset.id.get_chunk_info_by_coord(coord)
            chunk_entries.append(
                {
                    "coord": list(coord),
                    "file_offset": int(info.byte_offset),
                    "size": int(info.size),
                    "filter_mask": int(info.filter_mask),
                }
            )

    chunk_entries.sort(key=lambda entry: entry["file_offset"])
    payload = {
        "file": str(input_path),
        "dataset": args.dataset,
        "shape": list(shape),
        "chunks": list(chunks),
        "dtype": dtype.str,
        "chunk_count": len(chunk_entries),
        "entries": chunk_entries,
    }

    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    print(f"Wrote chunk map: {output_path}")
    print(f"Chunk count: {len(chunk_entries)}")
    if chunk_entries:
        print(f"First chunk offset: {chunk_entries[0]['file_offset']}")
        print(f"Last chunk offset: {chunk_entries[-1]['file_offset']}")


if __name__ == "__main__":
    raise SystemExit(main())
