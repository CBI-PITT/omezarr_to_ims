#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import json
from bisect import bisect_right
from pathlib import Path


AXIS_ORDER = "TCZYX"


def ceil_div(a, b):
    return (a + b - 1) // b


def product(values):
    result = 1
    for value in values:
        result *= value
    return result


def parse_manifest(path):
    payload = json.loads(Path(path).read_text(encoding="ascii"))
    datasets = sorted(payload["datasets"], key=lambda item: item["file_offset_start"])
    payload["datasets"] = datasets
    payload["dataset_starts"] = [item["file_offset_start"] for item in datasets]
    return payload


def unravel_index(linear_index, shape):
    coords = [0] * len(shape)
    for axis in range(len(shape) - 1, -1, -1):
        extent = shape[axis]
        coords[axis] = linear_index % extent
        linear_index //= extent
    return tuple(coords)


def ravel_index(indexes, shape):
    linear = 0
    for index, extent in zip(indexes, shape):
        linear = linear * extent + index
    return linear


def chunk_actual_shape(dataset, chunk_grid_index):
    actual = []
    for dim, chunk, grid_index in zip(dataset["shape"], dataset["chunks"], chunk_grid_index):
        start = grid_index * chunk
        actual.append(min(chunk, dim - start))
    return tuple(actual)


def dataset_for_offset(manifest, file_offset):
    index = bisect_right(manifest["dataset_starts"], file_offset) - 1
    if index < 0:
        return None
    dataset = manifest["datasets"][index]
    if file_offset >= dataset["file_offset_end"]:
        return None
    return dataset


def offset_to_chunk_location(manifest, file_offset):
    dataset = dataset_for_offset(manifest, file_offset)
    if dataset is None:
        return None

    dataset_relative_offset = file_offset - dataset["file_offset_start"]
    chunk_slot_size = dataset["chunk_slot_size"]
    linear_chunk_index = dataset_relative_offset // chunk_slot_size
    intra_chunk_byte_offset = dataset_relative_offset % chunk_slot_size
    chunk_grid_index = unravel_index(linear_chunk_index, dataset["grid_shape"])
    chunk_origin = tuple(index * chunk for index, chunk in zip(chunk_grid_index, dataset["chunks"]))
    actual_shape = chunk_actual_shape(dataset, chunk_grid_index)
    logical_chunk_bytes = product(actual_shape) * dataset["itemsize"]

    return {
        "dataset_path": dataset["path"],
        "axis_order": dataset["axis_order"],
        "shape": tuple(dataset["shape"]),
        "chunks": tuple(dataset["chunks"]),
        "grid_shape": tuple(dataset["grid_shape"]),
        "dtype": dataset["dtype"],
        "itemsize": dataset["itemsize"],
        "file_offset": file_offset,
        "dataset_relative_offset": dataset_relative_offset,
        "chunk_slot_size": chunk_slot_size,
        "chunk_linear_index": linear_chunk_index,
        "chunk_grid_index": chunk_grid_index,
        "chunk_origin": chunk_origin,
        "chunk_actual_shape": actual_shape,
        "logical_chunk_bytes": logical_chunk_bytes,
        "intra_chunk_byte_offset": intra_chunk_byte_offset,
        "is_padding_byte": intra_chunk_byte_offset >= logical_chunk_bytes,
    }


def offset_to_voxel_location(manifest, file_offset):
    chunk_location = offset_to_chunk_location(manifest, file_offset)
    if chunk_location is None:
        return None

    location = dict(chunk_location)
    itemsize = location["itemsize"]
    byte_offset = location["intra_chunk_byte_offset"]

    if location["is_padding_byte"]:
        location["voxel_index"] = None
        location["voxel_index_in_chunk"] = None
        location["byte_offset_within_element"] = None
        return location

    element_linear_index = byte_offset // itemsize
    byte_offset_within_element = byte_offset % itemsize
    voxel_index_in_chunk = unravel_index(element_linear_index, location["chunk_actual_shape"])
    voxel_index = tuple(origin + local for origin, local in zip(location["chunk_origin"], voxel_index_in_chunk))

    location["voxel_index_in_chunk"] = voxel_index_in_chunk
    location["voxel_index"] = voxel_index
    location["byte_offset_within_element"] = byte_offset_within_element
    return location


def parse_args():
    parser = argparse.ArgumentParser(description="Resolve an HDF5 file byte offset to chunk and voxel coordinates")
    parser.add_argument("manifest", help="Path to affine manifest JSON")
    parser.add_argument("offset", type=int, help="File byte offset to resolve")
    parser.add_argument(
        "--chunk-only",
        action="store_true",
        help="Resolve only to chunk location instead of voxel location",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    manifest = parse_manifest(args.manifest)
    if args.chunk_only:
        location = offset_to_chunk_location(manifest, args.offset)
    else:
        location = offset_to_voxel_location(manifest, args.offset)

    if location is None:
        print(f"Offset {args.offset} is outside the tracked dataset payload ranges")
        return 1

    print(json.dumps(location, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
