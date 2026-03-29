#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import json

from affine_lookup import parse_manifest, offset_to_chunk_location


def dataset_next_start(manifest, dataset_index):
    starts = manifest["dataset_starts"]
    if dataset_index + 1 < len(starts):
        return starts[dataset_index + 1]
    return manifest.get("file_size")


def dataset_index_for_offset(manifest, offset):
    for index, dataset in enumerate(manifest["datasets"]):
        if dataset["file_offset_start"] <= offset < dataset["file_offset_end"]:
            return index
    return None


def resolve_read_segments(manifest, file_offset, length):
    if length < 0:
        raise ValueError("length must be non-negative")
    if length == 0:
        return []

    file_size = manifest.get("file_size")
    if file_size is not None and file_offset >= file_size:
        return []

    request_end = file_offset + length
    if file_size is not None:
        request_end = min(request_end, file_size)

    segments = []
    current = file_offset
    while current < request_end:
        dataset_index = dataset_index_for_offset(manifest, current)
        if dataset_index is None:
            next_starts = [start for start in manifest["dataset_starts"] if start > current]
            next_boundary = min(next_starts) if next_starts else manifest.get("file_size", request_end)
            segment_end = min(request_end, next_boundary)
            segments.append(
                {
                    "kind": "metadata",
                    "file_offset": current,
                    "length": segment_end - current,
                }
            )
            current = segment_end
            continue

        dataset = manifest["datasets"][dataset_index]
        location = offset_to_chunk_location(manifest, current)
        chunk_end = min(request_end, dataset["file_offset_end"])
        chunk_boundary = current + (location["chunk_slot_size"] - location["intra_chunk_byte_offset"])
        segment_end = min(chunk_end, chunk_boundary)

        segments.append(
            {
                "kind": "data",
                "dataset_path": dataset["path"],
                "file_offset": current,
                "length": segment_end - current,
                "chunk_grid_index": list(location["chunk_grid_index"]),
                "chunk_origin": list(location["chunk_origin"]),
                "chunk_shape": list(location["chunk_shape"]),
                "chunk_actual_shape": list(location["chunk_actual_shape"]),
                "intra_chunk_byte_offset": location["intra_chunk_byte_offset"],
                "dtype": location["dtype"],
                "itemsize": location["itemsize"],
            }
        )
        current = segment_end

    return [segment for segment in segments if segment["length"] > 0]


def parse_args():
    parser = argparse.ArgumentParser(description="Resolve a file read into metadata, data, and padding segments")
    parser.add_argument("manifest", help="Path to affine manifest JSON")
    parser.add_argument("offset", type=int, help="Read start byte offset")
    parser.add_argument("length", type=int, help="Read length in bytes")
    return parser.parse_args()


def main():
    args = parse_args()
    manifest = parse_manifest(args.manifest)
    segments = resolve_read_segments(manifest, args.offset, args.length)
    print(json.dumps(segments, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
