# omezarr_to_ims

Basic FUSE test mount for exposing a fake `test.ims` file and printing filesystem operations.

This repo should use the Python environment at `/root/miniconda3/envs/omezarr_to_ims`.

The repo includes both a generic HDF5 shell prototype and an Imaris-style `.ims` shell backed by OME-Zarr.

## Requirements

- Linux with FUSE support installed
- `libfuse3` runtime and development files
- Python from `/root/miniconda3/envs/omezarr_to_ims`
- `pyfuse3`
- `h5py`
- `ome_zarr_multiscale_writer` installed in the same environment

Install the runtime dependencies and this repo itself with:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/pip install pyfuse3
/root/miniconda3/envs/omezarr_to_ims/bin/pip install h5py
/root/miniconda3/envs/omezarr_to_ims/bin/pip install numpy trio
/root/miniconda3/envs/omezarr_to_ims/bin/pip install -e /mnt/c/code/ome_zarr_multiscale_writer
/root/miniconda3/envs/omezarr_to_ims/bin/pip install -e /mnt/c/code/omezarr_to_ims
```

The editable install exposes console scripts including `build-hdf5-shell`,
`extract-affine-manifest`, `build-zarr-mapping`, `materialize-read`,
`mount-test-fs`, and `mount-virtual-hdf5`. The examples below mostly use
`python -m ...` so they also work directly against the installed modules.

## Build a generic HDF5 shell

Create a sparse chunked HDF5 file with allocated chunk addresses and no meaningful chunk payloads:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/example_shell.h5 --dataset /data --shape 128,128,64 --chunks 32,32,16 --dtype uint16
```

Create a multi-level generic shell using `TCZYX`-style 5D datasets:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/example_shell.h5 \
  --level "/level0/data|1,1,64,512,512|1,1,32,256,256" \
  --level "/level1/data|1,1,32,256,256|1,1,16,128,128" \
  --dtype uint16
```

Or build the shell directly from an OME-Zarr multiscale store. Lower-dimensional levels are promoted to `TCZYX` by adding leading singleton dimensions:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/from_zarr.h5 \
  --from-zarr "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
```

Build an Imaris-style shell from the same OME-Zarr store:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/from_zarr.ims \
  --imaris-from-zarr "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
```

This creates an HDF5-based `.ims` file with an Imaris-style hierarchy:

- `/DataSet/ResolutionLevel N/TimePoint T/Channel C/Data`
- `/DataSet/ResolutionLevel N/TimePoint T/Channel C/Histogram`
- `/DataSetInfo/...`

Extract the chunk coordinate to file offset mapping:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python extract_chunk_map.py /tmp/example_shell.h5 --dataset /data
```

This writes a sidecar JSON file next to the HDF5 shell with the chunk offsets reported by HDF5.

Extract a compact affine manifest instead of a full chunk map:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python extract_affine_manifest.py /tmp/example_shell.h5
```

This writes per-dataset metadata describing the affine chunk-slot layout, including `base_offset`, `chunk_slot_size`, `shape`, `chunks`, and `TCZYX` axis order.

Resolve a file byte offset to the corresponding voxel or chunk location:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python affine_lookup.py /tmp/example_shell.h5.affine_manifest.json 2048
/root/miniconda3/envs/omezarr_to_ims/bin/python affine_lookup.py /tmp/example_shell.h5.affine_manifest.json 2048 --chunk-only
```

The default lookup resolves all the way to the containing dataset voxel index in `TCZYX` order when the byte falls inside the logical chunk payload. Edge-chunk padding bytes are reported as padding.

Build an explicit one-store OME-Zarr mapping manifest:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_zarr_mapping.py /tmp/example_shell.h5.affine_manifest.json /data/example.ome.zarr
```

By default, datasets are mapped in order to Zarr arrays `0`, `1`, `2`, and so on. You can override individual paths with `--map`, for example `--map /level0/data=0`.

For Imaris-style shells, the generated mapping records the source resolution level, timepoint, and channel for each `.../Data` dataset automatically.

Resolve a file read into metadata, data, and padding segments:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python read_segments.py /tmp/example_shell.h5.affine_manifest.json 2048 8192
```

This is the intended pre-FUSE helper for splitting a virtual HDF5 file read into chunk-backed and metadata-backed regions. Edge-chunk padding is handled later during byte materialization.

Materialize a virtual read directly from shell metadata plus OME-Zarr chunk data:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python materialize_read.py \
  /tmp/from_zarr.h5 \
  /tmp/from_zarr.h5.affine_manifest.json \
  /tmp/from_zarr.h5.affine_manifest.json.zarr_map.json \
  2048 64 --hex
```

Mount a virtual HDF5 file backed by OME-Zarr:

```bash
mkdir -p /tmp/virtual-hdf5-mount
./run_virtual_mount.sh \
  /tmp/virtual-hdf5-mount \
  /tmp/from_zarr.h5 \
  /tmp/from_zarr.h5.affine_manifest.json \
  /tmp/from_zarr.h5.affine_manifest.json.zarr_map.json
```

Then read it with standard HDF5 tools, for example:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python - <<'PY'
import h5py
with h5py.File('/tmp/virtual-hdf5-mount/from_zarr.h5', 'r') as f:
    print(f['/level5/data'][0, 0, 0:2, 0:3, 0:4])
PY
fusermount3 -u /tmp/virtual-hdf5-mount
```

Mount an Imaris-style virtual file backed by OME-Zarr:

```bash
mkdir -p /tmp/virtual-ims-mount
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/from_zarr.ims \
  --imaris-from-zarr "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
/root/miniconda3/envs/omezarr_to_ims/bin/python extract_affine_manifest.py /tmp/from_zarr.ims
/root/miniconda3/envs/omezarr_to_ims/bin/python build_zarr_mapping.py /tmp/from_zarr.ims.affine_manifest.json \
  "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
./run_virtual_mount.sh \
  /tmp/virtual-ims-mount \
  /tmp/from_zarr.ims \
  /tmp/from_zarr.ims.affine_manifest.json \
  /tmp/from_zarr.ims.affine_manifest.json.zarr_map.json
```

Or rebuild everything and mount directly from an OME-Zarr store in one step:

```bash
mkdir -p /tmp/virtual-hdf5-mount
./run_from_zarr_mount.sh \
  /tmp/virtual-hdf5-mount \
  "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
```

This helper now rebuilds an Imaris-style `.ims` shell, affine manifest, and Zarr mapping in `/tmp` before mounting.

## Run the test mount

Create a mountpoint:

```bash
mkdir -p /tmp/test-mount
```

Start the filesystem in the foreground:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python mount_test_fs.py /tmp/test-mount
```

Or use the helper script:

```bash
./run_test_mount.sh /tmp/test-mount
```

The mount exposes a single read-only file:

- `/tmp/test-mount/test.ims`

Every filesystem operation is printed to stdout, so commands like these are useful for testing:

```bash
ls -la /tmp/test-mount
cat /tmp/test-mount/test.ims
```

Unmount when finished:

```bash
fusermount3 -u /tmp/test-mount
```
