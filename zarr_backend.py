#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import json
from pathlib import Path

import numpy as np

from ome_zarr_multiscale_writer.zarr_reader import OmeZarrArray


TCZYX_AXES = ("t", "c", "z", "y", "x")


def normalize_axis_names(axis_names, ndim):
    names = [name.lower() for name in axis_names]
    if names:
        return names
    fallback = {
        5: ["t", "c", "z", "y", "x"],
        4: ["c", "z", "y", "x"],
        3: ["z", "y", "x"],
        2: ["y", "x"],
    }
    return fallback.get(ndim, [f"axis_{index}" for index in range(ndim)])


def promote_to_tczyx(shape, chunks, axis_names):
    promoted_shape = []
    promoted_chunks = []
    axis_to_index = {name: index for index, name in enumerate(axis_names)}
    for axis in TCZYX_AXES:
        index = axis_to_index.get(axis)
        if index is None:
            promoted_shape.append(1)
            promoted_chunks.append(1)
        else:
            promoted_shape.append(int(shape[index]))
            promoted_chunks.append(int(chunks[index]))
    return tuple(promoted_shape), tuple(promoted_chunks)


def load_zarr_mapping(path):
    return json.loads(Path(path).read_text(encoding="ascii"))


def mapping_level(mapping_target):
    if isinstance(mapping_target, dict):
        return int(mapping_target["level"])
    if isinstance(mapping_target, int):
        return mapping_target
    if isinstance(mapping_target, str) and mapping_target.isdigit():
        return int(mapping_target)
    raise ValueError(f"Unsupported mapping target: {mapping_target!r}")


def mapping_timepoint(mapping_target):
    if isinstance(mapping_target, dict):
        return int(mapping_target.get("t", 0))
    return 0


def mapping_channel(mapping_target):
    if isinstance(mapping_target, dict):
        return int(mapping_target.get("c", 0))
    return 0


class OmeZarrBackend:
    def __init__(self, store_path):
        self.store_path = store_path
        self.array = OmeZarrArray(store_path, verbose=False)
        self.levels = []
        for level in range(self.array.ResolutionLevels):
            self.array.resolution_level = level
            axis_names = normalize_axis_names(self.array.axis_names, self.array.ndim)
            promoted_shape, promoted_chunks = promote_to_tczyx(
                self.array.shape,
                self.array.chunks,
                axis_names,
            )
            self.levels.append(
                {
                    "level": level,
                    "dataset_path": self.array._get_dataset_path(),
                    "axis_names": axis_names,
                    "shape": tuple(int(value) for value in self.array.shape),
                    "chunks": tuple(int(value) for value in self.array.chunks),
                    "promoted_shape": promoted_shape,
                    "promoted_chunks": promoted_chunks,
                    "dtype": np.dtype(self.array.dtype),
                }
            )
        self.array.resolution_level = 0
        self.path_to_level = {entry["dataset_path"]: entry for entry in self.levels}
        self.level_to_entry = {entry["level"]: entry for entry in self.levels}

    def level_entry(self, target):
        if isinstance(target, dict):
            return self.level_to_entry[int(target["level"])]
        if isinstance(target, int):
            return self.level_to_entry[target]
        if isinstance(target, str) and target.isdigit():
            return self.level_to_entry[int(target)]
        return self.path_to_level[target]

    def level_specs(self, prefix="/level"):
        specs = []
        for entry in self.levels:
            specs.append(
                {
                    "path": f"{prefix}{entry['level']}/data",
                    "shape": entry["promoted_shape"],
                    "chunks": entry["promoted_chunks"],
                }
            )
        return specs

    def default_mapping(self, prefix="/level"):
        return {
            f"{prefix}{entry['level']}/data": {"level": entry["level"], "t": 0, "c": 0}
            for entry in self.levels
        }

    def read_volume(self, level, t=0, c=0):
        entry = self.level_entry(level)
        self.array.resolution_level = entry["level"]
        native_slices = []
        for axis_name, extent in zip(entry["axis_names"], entry["shape"]):
            if axis_name == "t":
                native_slices.append(t)
            elif axis_name == "c":
                native_slices.append(c)
            else:
                native_slices.append(slice(0, extent))
        data = np.asarray(self.array[tuple(native_slices)])
        if data.ndim != 3:
            raise ValueError(f"Expected 3D ZYX data after TC extraction, got shape {data.shape}")
        return data

    def validate_shell_dataset(self, dataset_path, mapping_target, shell_shape,
                               shell_chunks, shell_dtype, source_layout=None):
        entry = self.level_entry(mapping_target)
        expected_shape = entry["promoted_shape"][2:]
        if tuple(shell_shape) != expected_shape:
            raise ValueError(
                f"Shape mismatch for {dataset_path}: shell {tuple(shell_shape)} vs zarr {expected_shape}"
            )
        # Imaris shells use their own fixed chunk sizes independent of the
        # Zarr store's native chunking.  Only enforce chunk equality for
        # generic (non-Imaris) shells.
        if source_layout != "imaris":
            expected_chunks = entry["promoted_chunks"][2:]
            if tuple(shell_chunks) != expected_chunks:
                raise ValueError(
                    f"Chunk mismatch for {dataset_path}: shell {tuple(shell_chunks)} vs zarr {expected_chunks}"
                )
        if np.dtype(shell_dtype) != entry["dtype"]:
            raise ValueError(
                f"Dtype mismatch for {dataset_path}: shell {np.dtype(shell_dtype)} vs zarr {entry['dtype']}"
            )

    def read_chunk(self, mapping_target, chunk_origin, chunk_shape, chunk_actual_shape):
        entry = self.level_entry(mapping_target)
        self.array.resolution_level = entry["level"]
        native_slices = []
        target_t = mapping_timepoint(mapping_target)
        target_c = mapping_channel(mapping_target)
        if len(chunk_origin) == 3:
            spatial_index = {"z": 0, "y": 1, "x": 2}
        else:
            spatial_index = {axis: index for index, axis in enumerate(TCZYX_AXES)}
        for axis_name in entry["axis_names"]:
            if axis_name == "t":
                native_slices.append(target_t)
                continue
            if axis_name == "c":
                native_slices.append(target_c)
                continue
            promoted_index = spatial_index[axis_name]
            start = int(chunk_origin[promoted_index])
            extent = int(chunk_actual_shape[promoted_index])
            native_slices.append(slice(start, start + extent))
        chunk = np.asarray(self.array[tuple(native_slices)])
        if chunk.ndim != 3:
            raise ValueError(f"Expected 3D chunk after TC selection, got shape {chunk.shape}")
        padded = np.zeros(tuple(chunk_shape), dtype=entry["dtype"])
        insert_slices = tuple(slice(0, extent) for extent in chunk_actual_shape)
        padded[insert_slices] = chunk
        return padded
