#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
from pathlib import Path

import h5py
import numpy as np
from h5py import h5d, h5p, h5s, h5t


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
        required=True,
        type=parse_shape,
        help="Dataset shape as comma-separated integers, e.g. 256,256,64",
    )
    parser.add_argument(
        "--chunks",
        required=True,
        type=parse_shape,
        help="Chunk shape as comma-separated integers, e.g. 64,64,16",
    )
    parser.add_argument(
        "--dtype",
        default="uint16",
        help="NumPy dtype string for the dataset (default: uint16)",
    )
    return parser.parse_args()


def ensure_parent_groups(h5file, dataset_path):
    parent_path = Path(dataset_path).parent.as_posix()
    if parent_path in ("", ".", "/"):
        return h5file["/"]
    return h5file.require_group(parent_path)


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

    dataset_path = Path(args.dataset).as_posix()
    dataset_name = Path(dataset_path).name
    if dataset_name in ("", "/"):
        raise ValueError("Dataset path must include a dataset name")

    dtype = np.dtype(args.dtype)

    with h5py.File(output_path, "w", libver="latest") as h5file:
        parent_group = ensure_parent_groups(h5file, dataset_path)
        dataset = create_chunked_dataset(parent_group, dataset_name, args.shape, args.chunks, dtype)
        dataset.attrs["virtual_shell"] = True
        dataset.attrs["chunk_layout"] = np.asarray(args.chunks, dtype=np.int64)
        dataset.attrs["source_layout"] = "generic"
        h5file.flush()

        storage_size = dataset.id.get_storage_size()
        chunk_bytes = int(np.prod(args.chunks, dtype=np.int64)) * dtype.itemsize

    print(f"Created HDF5 shell: {output_path}")
    print(f"Dataset path: {dataset_path}")
    print(f"Shape: {args.shape}")
    print(f"Chunks: {args.chunks}")
    print(f"Dtype: {dtype.str}")
    print(f"Chunk byte size: {chunk_bytes}")
    print(f"Allocated storage size: {storage_size}")


if __name__ == "__main__":
    raise SystemExit(main())
