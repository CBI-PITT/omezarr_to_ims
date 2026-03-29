#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import json
from pathlib import Path

import h5py
import numpy as np
from h5py import h5d, h5p, h5s, h5t

from zarr_backend import OmeZarrBackend


def parse_shape(text):
    values = tuple(int(part.strip()) for part in text.split(",") if part.strip())
    if not values:
        raise argparse.ArgumentTypeError("Expected a comma-separated list of integers")
    if any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("All dimensions must be positive")
    return values


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a sparse HDF5 shell file with early-allocated chunk addresses"
    )
    parser.add_argument("output", help="Path to the HDF5 file to create")
    parser.add_argument(
        "--dataset",
        default="/data",
        help="Dataset path to create inside the HDF5 file (default: /data)",
    )
    parser.add_argument(
        "--shape",
        type=parse_shape,
        help="Dataset shape as comma-separated integers, e.g. 256,256,64",
    )
    parser.add_argument(
        "--chunks",
        type=parse_shape,
        help="Chunk shape as comma-separated integers, e.g. 64,64,16",
    )
    parser.add_argument(
        "--dtype",
        default="uint16",
        help="NumPy dtype string for the dataset (default: uint16)",
    )
    parser.add_argument(
        "--level",
        action="append",
        dest="levels",
        help=(
            "Level specification as path|shape|chunks, for example "
            "'/level0/data|1,1,64,512,512|1,1,32,256,256'. May be passed multiple times."
        ),
    )
    parser.add_argument(
        "--levels-json",
        help="Path to a JSON file containing a list of level objects with path, shape, and chunks fields.",
    )
    parser.add_argument(
        "--from-zarr",
        help="Path to an OME-Zarr store to use as the source of truth for level metadata.",
    )
    parser.add_argument(
        "--dataset-prefix",
        default="/level",
        help="Prefix for auto-generated shell dataset paths when using --from-zarr (default: /level)",
    )
    return parser.parse_args()


def ensure_parent_groups(h5file, dataset_path):
    parent_path = Path(dataset_path).parent.as_posix()
    if parent_path in ("", ".", "/"):
        return h5file["/"]
    return h5file.require_group(parent_path)


def parse_level_spec(text):
    parts = [part.strip() for part in text.split("|")]
    if len(parts) != 3:
        raise ValueError(f"Invalid --level value: {text}")
    return {
        "path": Path(parts[0]).as_posix(),
        "shape": parse_shape(parts[1]),
        "chunks": parse_shape(parts[2]),
    }


def load_level_specs(args):
    if args.from_zarr:
        backend = OmeZarrBackend(args.from_zarr)
        return backend.level_specs(prefix=args.dataset_prefix)

    levels = []

    if args.levels_json:
        payload = json.loads(Path(args.levels_json).read_text(encoding="ascii"))
        for entry in payload:
            levels.append(
                {
                    "path": Path(entry["path"]).as_posix(),
                    "shape": tuple(int(value) for value in entry["shape"]),
                    "chunks": tuple(int(value) for value in entry["chunks"]),
                }
            )

    if args.levels:
        levels.extend(parse_level_spec(text) for text in args.levels)

    if levels:
        return levels

    if args.shape is None or args.chunks is None:
        raise ValueError("Single-dataset mode requires both --shape and --chunks")

    return [
        {
            "path": Path(args.dataset).as_posix(),
            "shape": args.shape,
            "chunks": args.chunks,
        }
    ]


def create_chunked_dataset(parent_group, dataset_name, shape, chunks, dtype):
    if len(shape) != len(chunks):
        raise ValueError("Shape rank and chunk rank must match")
    if any(chunk > dim for chunk, dim in zip(chunks, shape)):
        raise ValueError("Each chunk dimension must be less than or equal to its dataset dimension")

    dataspace = h5s.create_simple(shape, shape)
    dcpl = h5p.create(h5p.DATASET_CREATE)
    dcpl.set_chunk(chunks)
    dcpl.set_alloc_time(h5d.ALLOC_TIME_EARLY)
    dcpl.set_fill_time(h5d.FILL_TIME_NEVER)

    dataset_id = h5d.create(
        parent_group.id,
        dataset_name.encode("utf-8"),
        h5t.py_create(np.dtype(dtype)),
        dataspace,
        dcpl=dcpl,
    )
    return h5py.Dataset(dataset_id)


def main():
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dtype = np.dtype(args.dtype)
    level_specs = load_level_specs(args)

    with h5py.File(output_path, "w", libver="latest") as h5file:
        dataset_summaries = []
        for level in level_specs:
            dataset_path = level["path"]
            dataset_name = Path(dataset_path).name
            if dataset_name in ("", "/"):
                raise ValueError(f"Dataset path must include a dataset name: {dataset_path}")

            parent_group = ensure_parent_groups(h5file, dataset_path)
            dataset = create_chunked_dataset(parent_group, dataset_name, level["shape"], level["chunks"], dtype)
            dataset.attrs["virtual_shell"] = True
            dataset.attrs["chunk_layout"] = np.asarray(level["chunks"], dtype=np.int64)
            dataset.attrs["axis_order"] = "TCZYX" if len(level["shape"]) == 5 else "generic"
            dataset.attrs["source_layout"] = "generic"
            dataset_summaries.append(
                {
                    "path": dataset_path,
                    "shape": level["shape"],
                    "chunks": level["chunks"],
                    "chunk_bytes": int(np.prod(level["chunks"], dtype=np.int64)) * dtype.itemsize,
                    "storage_size": int(dataset.id.get_storage_size()),
                }
            )

        h5file.flush()

    print(f"Created HDF5 shell: {output_path}")
    print(f"Dtype: {dtype.str}")
    print(f"Dataset count: {len(level_specs)}")
    for summary in dataset_summaries:
        print(f"Dataset path: {summary['path']}")
        print(f"  Shape: {summary['shape']}")
        print(f"  Chunks: {summary['chunks']}")
        print(f"  Chunk byte size: {summary['chunk_bytes']}")
        print(f"  Allocated storage size: {summary['storage_size']}")


if __name__ == "__main__":
    raise SystemExit(main())
