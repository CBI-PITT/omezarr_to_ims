#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import json
import re
from pathlib import Path


IMARIS_DATASET_PATH = re.compile(
    r"^/DataSet/ResolutionLevel (?P<level>\d+)/TimePoint (?P<t>\d+)/Channel (?P<c>\d+)/Data$"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build a one-store mapping from HDF5 shell datasets to OME-Zarr array paths"
    )
    parser.add_argument("manifest", help="Path to affine manifest JSON")
    parser.add_argument("store", help="Path to the OME-Zarr store backing this virtual HDF5 file")
    parser.add_argument(
        "--map",
        action="append",
        dest="maps",
        help="Explicit mapping as hdf5_dataset_path=zarr_array_path. May be passed multiple times.",
    )
    parser.add_argument(
        "--output",
        help="Path to write the Zarr mapping JSON (default: <manifest>.zarr_map.json)",
    )
    return parser.parse_args()


def load_affine_manifest(path):
    return json.loads(Path(path).read_text(encoding="ascii"))


def parse_explicit_mappings(values):
    mapping = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"Invalid --map value: {value}")
        key, mapped = value.split("=", 1)
        mapping[key.strip()] = mapped.strip()
    return mapping


def infer_mapping_target(dataset_path, index):
    match = IMARIS_DATASET_PATH.match(dataset_path)
    if match is not None:
        return {
            "level": int(match.group("level")),
            "t": int(match.group("t")),
            "c": int(match.group("c")),
        }
    return {"level": index, "t": 0, "c": 0}


def build_mapping(affine_manifest, store, explicit):
    dataset_paths = [dataset["path"] for dataset in affine_manifest["datasets"]]
    dataset_map = {}
    dataset_entries = {dataset["path"]: dataset for dataset in affine_manifest["datasets"]}
    for index, dataset_path in enumerate(dataset_paths):
        if dataset_path in explicit:
            dataset_map[dataset_path] = explicit[dataset_path]
            continue
        dataset = dataset_entries[dataset_path]
        inferred = infer_mapping_target(dataset_path, index)
        dataset_map[dataset_path] = {
            "level": int(dataset.get("source_level", inferred["level"])),
            "t": int(dataset.get("source_t", inferred["t"])),
            "c": int(dataset.get("source_c", inferred["c"])),
        }

    unknown = sorted(set(explicit) - set(dataset_paths))
    if unknown:
        raise ValueError(f"Mappings provided for unknown datasets: {', '.join(unknown)}")

    return {
        "store": store,
        "source_affine_manifest": affine_manifest["file"],
        "axis_order": affine_manifest["axis_order"],
        "datasets": dataset_map,
    }


def main():
    args = parse_args()
    manifest_path = Path(args.manifest)
    output_path = Path(args.output) if args.output else manifest_path.with_suffix(manifest_path.suffix + ".zarr_map.json")

    affine_manifest = load_affine_manifest(manifest_path)
    explicit = parse_explicit_mappings(args.maps)
    payload = build_mapping(affine_manifest, args.store, explicit)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")

    print(f"Wrote Zarr mapping: {output_path}")
    print(f"Store: {payload['store']}")
    for dataset_path, zarr_array in payload["datasets"].items():
        print(f"{dataset_path} -> {zarr_array}")


if __name__ == "__main__":
    raise SystemExit(main())
