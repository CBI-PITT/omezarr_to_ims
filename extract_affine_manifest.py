#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import json
import re
from pathlib import Path

import h5py

from affine_lookup import AXIS_ORDER, ceil_div, product


IMARIS_DATASET_PATH = re.compile(
    r"^/DataSet/ResolutionLevel (?P<level>\d+)/TimePoint (?P<t>\d+)/Channel (?P<c>\d+)/Data$"
)


def parse_imaris_dataset_path(dataset_path):
    match = IMARIS_DATASET_PATH.match(dataset_path)
    if match is None:
        return None
    return {
        "source_layout": "imaris",
        "source_level": int(match.group("level")),
        "source_t": int(match.group("t")),
        "source_c": int(match.group("c")),
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract affine chunk-layout metadata from a sparse HDF5 shell"
    )
    parser.add_argument("input", help="Path to the HDF5 shell file")
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        help="Dataset path to inspect; may be passed multiple times. Defaults to all chunked datasets.",
    )
    parser.add_argument(
        "--output",
        help="Path to write manifest JSON output (default: <input>.affine_manifest.json)",
    )
    return parser.parse_args()


def iter_chunked_datasets(h5file):
    discovered = []

    def visitor(name, obj):
        if isinstance(obj, h5py.Dataset) and obj.chunks is not None:
            discovered.append("/" + name)

    h5file.visititems(visitor)
    return sorted(discovered)


def select_sample_origins(shape, chunks):
    grid_shape = tuple(ceil_div(dim, chunk) for dim, chunk in zip(shape, chunks))
    last_index = tuple(max(0, extent - 1) for extent in grid_shape)
    indexes = {
        tuple(0 for _ in grid_shape),
        tuple(min(1, max(0, extent - 1)) for extent in grid_shape),
        last_index,
    }
    for axis in range(len(grid_shape)):
        point = [0] * len(grid_shape)
        point[axis] = last_index[axis]
        indexes.add(tuple(point))
    if len(grid_shape) >= 2:
        point = [0] * len(grid_shape)
        point[-1] = last_index[-1]
        point[-2] = last_index[-2]
        indexes.add(tuple(point))
    if len(grid_shape) >= 3:
        point = [0] * len(grid_shape)
        point[-1] = last_index[-1]
        point[-2] = last_index[-2]
        point[-3] = last_index[-3]
        indexes.add(tuple(point))
    return [tuple(index * chunk for index, chunk in zip(indexes_item, chunks)) for indexes_item in sorted(indexes)]


def dataset_manifest_entry(dataset_path, dataset):
    shape = tuple(int(value) for value in dataset.shape)
    chunks = tuple(int(value) for value in dataset.chunks)
    grid_shape = tuple(ceil_div(dim, chunk) for dim, chunk in zip(shape, chunks))
    dtype = dataset.dtype
    source_info = parse_imaris_dataset_path(dataset_path)
    logical_shape = None
    if "logical_shape" in dataset.attrs:
        logical_shape = tuple(int(value) for value in dataset.attrs["logical_shape"])
    elif source_info is not None:
        image_size_keys = ("ImageSizeZ", "ImageSizeY", "ImageSizeX")
        parent_attrs = dataset.parent.attrs
        if all(key in parent_attrs for key in image_size_keys):
            logical_shape = []
            for key in image_size_keys:
                value = parent_attrs[key]
                if getattr(value, "dtype", None) is not None and str(value.dtype) == "|S1":
                    value = b"".join(value.tolist()).decode("ascii")
                logical_shape.append(int(float(value)))
            logical_shape = tuple(logical_shape)

    first_origin = tuple(0 for _ in shape)
    first_info = dataset.id.get_chunk_info_by_coord(first_origin)
    base_offset = int(first_info.byte_offset)
    chunk_slot_size = int(first_info.size)
    chunk_count = product(grid_shape)
    file_offset_end = base_offset + chunk_count * chunk_slot_size

    samples = []
    affine_ok = True
    for origin in select_sample_origins(shape, chunks):
        info = dataset.id.get_chunk_info_by_coord(origin)
        chunk_index = tuple(origin_axis // chunk_axis for origin_axis, chunk_axis in zip(origin, chunks))
        linear_chunk_index = 0
        for index, extent in zip(chunk_index, grid_shape):
            linear_chunk_index = linear_chunk_index * extent + index
        expected_offset = base_offset + linear_chunk_index * chunk_slot_size
        sample = {
            "origin": list(origin),
            "chunk_index": list(chunk_index),
            "offset": int(info.byte_offset),
            "expected_offset": int(expected_offset),
            "reported_size": int(info.size),
        }
        samples.append(sample)
        if int(info.byte_offset) != expected_offset or int(info.size) != chunk_slot_size:
            affine_ok = False

    entry = {
        "path": dataset_path,
        "axis_order": "ZYX" if source_info is not None and len(shape) == 3 else dataset.attrs.get("axis_order", AXIS_ORDER),
        "shape": list(shape),
        "chunks": list(chunks),
        "grid_shape": list(grid_shape),
        "dtype": dtype.str,
        "itemsize": dtype.itemsize,
        "chunk_slot_size": chunk_slot_size,
        "chunk_count": chunk_count,
        "file_offset_start": base_offset,
        "file_offset_end": file_offset_end,
        "storage_size": int(dataset.id.get_storage_size()),
        "affine_verified_on_samples": affine_ok,
        "verification_samples": samples,
    }
    if logical_shape is not None:
        entry["logical_shape"] = list(logical_shape)
    if source_info is not None:
        entry.update(source_info)
    for attr_name in ("source_layout", "source_level", "source_t", "source_c"):
        if attr_name in dataset.attrs:
            value = dataset.attrs[attr_name]
            if hasattr(value, "item"):
                value = value.item()
            entry[attr_name] = value
    return entry


def build_manifest(input_path, dataset_paths):
    with h5py.File(input_path, "r") as h5file:
        entries = [dataset_manifest_entry(path, h5file[path]) for path in dataset_paths]

    entries.sort(key=lambda item: item["file_offset_start"])
    return {
        "file": str(input_path),
        "file_size": input_path.stat().st_size,
        "axis_order": AXIS_ORDER,
        "dataset_count": len(entries),
        "datasets": entries,
    }


def main():
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix(input_path.suffix + ".affine_manifest.json")

    with h5py.File(input_path, "r") as h5file:
        dataset_paths = args.datasets if args.datasets else iter_chunked_datasets(h5file)

    if not dataset_paths:
        raise ValueError("No chunked datasets found in input file")

    manifest = build_manifest(input_path, dataset_paths)
    output_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="ascii")

    print(f"Wrote affine manifest: {output_path}")
    print(f"Dataset count: {manifest['dataset_count']}")
    for dataset in manifest["datasets"]:
        print(
            f"{dataset['path']}: base_offset={dataset['file_offset_start']} "
            f"chunk_slot_size={dataset['chunk_slot_size']} chunk_count={dataset['chunk_count']}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
