#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import json
from pathlib import Path

import h5py
import numpy as np
from h5py import h5d, h5p, h5s, h5t

from zarr_backend import OmeZarrBackend


IMS_FORMAT_VERSION = "5.5.0"
IMARIS_WRITER_VERSION = "10.2.0"


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
    parser.add_argument(
        "--imaris-from-zarr",
        help="Path to an OME-Zarr store to mirror into an Imaris-style HDF5 shell.",
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
    if args.imaris_from_zarr:
        raise ValueError("load_level_specs should not be used with --imaris-from-zarr")

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


def set_string_attr(h5obj, name, value):
    h5obj.attrs[name] = str(value)


def set_imaris_string_attr(h5obj, name, value):
    text = str(value)
    h5obj.attrs.create(name, np.frombuffer(text.encode("ascii"), dtype="S1"))


def set_imaris_uint32_attr(h5obj, name, value):
    h5obj.attrs.create(name, np.asarray([value], dtype=np.uint32))


def compute_integer_histogram(data):
    flat = np.asarray(data).reshape(-1)
    if flat.size == 0:
        return 0, 0, np.zeros(1, dtype=np.uint64)
    minimum = int(flat.min())
    maximum = int(flat.max())
    counts = np.bincount((flat.astype(np.int64) - minimum), minlength=(maximum - minimum + 1))
    return minimum, maximum, counts.astype(np.uint64)


def compute_imaris_histograms(data):
    flat = np.asarray(data).reshape(-1)
    if flat.size == 0:
        empty = np.zeros(256, dtype=np.uint64)
        return 0, 0, empty, np.zeros(1024, dtype=np.uint64)

    minimum = int(flat.min())
    maximum = int(flat.max())
    if minimum == maximum:
        histogram_256 = np.zeros(256, dtype=np.uint64)
        histogram_256[0] = flat.size
        histogram_1024 = np.zeros(1024, dtype=np.uint64)
        histogram_1024[0] = flat.size
        return minimum, maximum, histogram_256, histogram_1024

    value_range = (minimum, maximum)
    histogram_256, _ = np.histogram(flat, bins=256, range=value_range)
    histogram_1024, _ = np.histogram(flat, bins=1024, range=value_range)
    return minimum, maximum, histogram_256.astype(np.uint64), histogram_1024.astype(np.uint64)


def pad_shape_to_chunks(shape, chunks):
    return tuple(((dim + chunk - 1) // chunk) * chunk for dim, chunk in zip(shape, chunks))


def build_imaris_shell(output_path, store_path, dtype=None):
    backend = OmeZarrBackend(store_path)
    if dtype is None:
        dtype = backend.levels[0]["dtype"]
    dtype = np.dtype(dtype)
    lowest_level = backend.levels[-1]["level"]
    max_t = max(spec["promoted_shape"][0] for spec in backend.levels)
    max_c = max(spec["promoted_shape"][1] for spec in backend.levels)

    channel_histograms = {}
    for t_index in range(max_t):
        for c_index in range(max_c):
            volume = backend.read_volume(lowest_level, t=t_index, c=c_index)
            channel_histograms[(t_index, c_index)] = compute_imaris_histograms(volume)

    with h5py.File(output_path, "w", libver="latest") as h5file:
        set_imaris_string_attr(h5file, "DataSetDirectoryName", "DataSet")
        set_imaris_string_attr(h5file, "DataSetInfoDirectoryName", "DataSetInfo")
        set_imaris_string_attr(h5file, "ImarisDataSet", "ImarisDataSet")
        set_imaris_string_attr(h5file, "ImarisVersion", IMS_FORMAT_VERSION)
        set_imaris_uint32_attr(h5file, "NumberOfDataSets", 1)
        set_imaris_string_attr(h5file, "ThumbnailDirectoryName", "Thumbnail")

        dataset_group = h5file.require_group("DataSet")
        dataset_info = h5file.require_group("DataSetInfo")
        thumbnail_group = h5file.require_group("Thumbnail")
        log_group = dataset_info.require_group("Log")

        info_imaris_dataset = dataset_info.require_group("ImarisDataSet")
        set_imaris_string_attr(info_imaris_dataset, "Creator", "ImarisConvert")
        set_imaris_string_attr(info_imaris_dataset, "NumberOfImages", 1)
        set_imaris_string_attr(info_imaris_dataset, "Version", IMARIS_WRITER_VERSION)

        info_imaris = dataset_info.require_group("Imaris")
        set_imaris_string_attr(info_imaris, "Version", IMARIS_WRITER_VERSION)

        level0_shape = backend.levels[0]["promoted_shape"]
        image_group = dataset_info.require_group("Image")
        set_imaris_string_attr(image_group, "Description", "(description not specified)")
        set_imaris_string_attr(image_group, "Name", "(name not specified)")
        set_imaris_string_attr(image_group, "OriginalFormat", "OME-Zarr")
        set_imaris_string_attr(image_group, "OriginalFormatFileIOVersion", "virtual-hdf5")
        set_imaris_string_attr(image_group, "RecordingDate", "1970-01-01 00:00:00")
        set_imaris_string_attr(image_group, "ResampleDimensionX", "true")
        set_imaris_string_attr(image_group, "ResampleDimensionY", "true")
        set_imaris_string_attr(image_group, "ResampleDimensionZ", "true")
        set_imaris_string_attr(image_group, "Unit", "um")
        set_imaris_string_attr(image_group, "X", level0_shape[4])
        set_imaris_string_attr(image_group, "Y", level0_shape[3])
        set_imaris_string_attr(image_group, "Z", level0_shape[2])
        set_imaris_string_attr(image_group, "ExtMin0", "0.0000000000")
        set_imaris_string_attr(image_group, "ExtMin1", "0.0000000000")
        set_imaris_string_attr(image_group, "ExtMin2", "0.0000000000")
        set_imaris_string_attr(image_group, "ExtMax0", f"{float(level0_shape[4]):.10f}")
        set_imaris_string_attr(image_group, "ExtMax1", f"{float(level0_shape[3]):.10f}")
        set_imaris_string_attr(image_group, "ExtMax2", f"{float(level0_shape[2]):.10f}")

        time_info = dataset_info.require_group("TimeInfo")
        set_imaris_string_attr(time_info, "DatasetTimePoints", max_t)
        set_imaris_string_attr(time_info, "FileTimePoints", max_t)
        for t_index in range(max_t):
            set_imaris_string_attr(time_info, f"TimePoint{t_index + 1}", f"1970-01-01 00:00:{t_index:02d}")

        set_imaris_string_attr(log_group, "Entries", 0)

        thumbnail_group.create_dataset("Data", data=np.zeros((256, 1024), dtype=np.uint8), dtype=np.uint8)

        colors = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1)]
        for c_index in range(max_c):
            channel_group = dataset_info.require_group(f"Channel {c_index}")
            hist_min, hist_max, _, _ = channel_histograms[(0, c_index)]
            color = colors[c_index % len(colors)]
            set_imaris_string_attr(channel_group, "Name", c_index)
            set_imaris_string_attr(channel_group, "Description", f"Channel {c_index}")
            set_imaris_string_attr(channel_group, "ColorMode", "BaseColor")
            set_imaris_string_attr(channel_group, "Color", f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f}")
            set_imaris_string_attr(channel_group, "ColorOpacity", "1.000")
            set_imaris_string_attr(channel_group, "ColorRange", f"{hist_min:.3f} {hist_max:.3f}")
            set_imaris_string_attr(channel_group, "GammaCorrection", "1.000")

        dataset_summaries = []
        for level_spec in backend.levels:
            level = level_spec["level"]
            logical_zyx_shape = level_spec["promoted_shape"][2:]
            zyx_chunks = level_spec["promoted_chunks"][2:]
            stored_zyx_shape = pad_shape_to_chunks(logical_zyx_shape, zyx_chunks)
            level_group = dataset_group.require_group(f"ResolutionLevel {level}")
            for t_index in range(level_spec["promoted_shape"][0]):
                time_group = level_group.require_group(f"TimePoint {t_index}")
                for c_index in range(level_spec["promoted_shape"][1]):
                    channel_group = time_group.require_group(f"Channel {c_index}")
                    hist_min, hist_max, histogram_256, histogram_1024 = channel_histograms[(t_index, c_index)]
                    set_imaris_string_attr(channel_group, "ImageSizeX", logical_zyx_shape[2])
                    set_imaris_string_attr(channel_group, "ImageSizeY", logical_zyx_shape[1])
                    set_imaris_string_attr(channel_group, "ImageSizeZ", logical_zyx_shape[0])
                    set_imaris_string_attr(channel_group, "HistogramMin", f"{hist_min:.3f}")
                    set_imaris_string_attr(channel_group, "HistogramMax", f"{hist_max:.3f}")
                    set_imaris_string_attr(channel_group, "HistogramMin1024", f"{hist_min:.3f}")
                    set_imaris_string_attr(channel_group, "HistogramMax1024", f"{hist_max:.3f}")

                    data_dataset = create_chunked_dataset(channel_group, "Data", stored_zyx_shape, zyx_chunks, dtype)
                    data_dataset.attrs["virtual_shell"] = True
                    data_dataset.attrs["axis_order"] = "ZYX"
                    data_dataset.attrs["logical_shape"] = np.asarray(logical_zyx_shape, dtype=np.int64)
                    data_dataset.attrs["source_layout"] = "imaris"
                    data_dataset.attrs["source_level"] = level
                    data_dataset.attrs["source_t"] = t_index
                    data_dataset.attrs["source_c"] = c_index

                    channel_group.create_dataset("Histogram", data=histogram_256, dtype=np.uint64)
                    channel_group.create_dataset("Histogram1024", data=histogram_1024, dtype=np.uint64)
                    dataset_summaries.append(
                        {
                            "path": data_dataset.name,
                            "shape": stored_zyx_shape,
                            "logical_shape": logical_zyx_shape,
                            "chunks": zyx_chunks,
                            "dtype": np.dtype(dtype).str,
                            "chunk_bytes": int(np.prod(zyx_chunks, dtype=np.int64)) * dtype.itemsize,
                            "storage_size": int(data_dataset.id.get_storage_size()),
                        }
                    )

        h5file.flush()

    return dataset_summaries


def main():
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dtype = np.dtype(args.dtype)

    if args.imaris_from_zarr:
        dataset_summaries = build_imaris_shell(output_path, args.imaris_from_zarr, None)
        print(f"Created Imaris-style HDF5 shell: {output_path}")
        print(f"Dtype: {dataset_summaries[0]['dtype'] if dataset_summaries else dtype.str}")
        print(f"Dataset count: {len(dataset_summaries)}")
        for summary in dataset_summaries[:8]:
            print(f"Dataset path: {summary['path']}")
            print(f"  Shape: {summary['shape']}")
            print(f"  Chunks: {summary['chunks']}")
            print(f"  Chunk byte size: {summary['chunk_bytes']}")
            print(f"  Allocated storage size: {summary['storage_size']}")
        if len(dataset_summaries) > 8:
            print(f"... {len(dataset_summaries) - 8} more datasets omitted")
        return

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
