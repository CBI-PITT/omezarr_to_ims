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
            f"{prefix}{entry['level']}/data": str(entry["level"])
            for entry in self.levels
        }

    def validate_shell_dataset(self, dataset_path, mapping_target, shell_shape, shell_chunks, shell_dtype):
        entry = self.level_entry(mapping_target)
        if tuple(shell_shape) != entry["promoted_shape"]:
            raise ValueError(
                f"Shape mismatch for {dataset_path}: shell {tuple(shell_shape)} vs zarr {entry['promoted_shape']}"
            )
        if tuple(shell_chunks) != entry["promoted_chunks"]:
            raise ValueError(
                f"Chunk mismatch for {dataset_path}: shell {tuple(shell_chunks)} vs zarr {entry['promoted_chunks']}"
            )
        if np.dtype(shell_dtype) != entry["dtype"]:
            raise ValueError(
                f"Dtype mismatch for {dataset_path}: shell {np.dtype(shell_dtype)} vs zarr {entry['dtype']}"
            )

    def read_chunk(self, mapping_target, chunk_origin, chunk_shape, chunk_actual_shape):
        entry = self.level_entry(mapping_target)
        self.array.resolution_level = entry["level"]
        native_slices = []
        for axis_name in entry["axis_names"]:
            promoted_index = TCZYX_AXES.index(axis_name)
            start = int(chunk_origin[promoted_index])
            extent = int(chunk_actual_shape[promoted_index])
            native_slices.append(slice(start, start + extent))
        chunk = np.asarray(self.array[tuple(native_slices)])
        promoted_shape = []
        native_iter = iter(chunk.shape)
        for axis_name in TCZYX_AXES:
            if axis_name in entry["axis_names"]:
                promoted_shape.append(next(native_iter))
            else:
                promoted_shape.append(1)
        promoted = chunk.reshape(tuple(promoted_shape))
        padded = np.zeros(tuple(chunk_shape), dtype=entry["dtype"])
        insert_slices = tuple(slice(0, extent) for extent in chunk_actual_shape)
        padded[insert_slices] = promoted
        return padded
