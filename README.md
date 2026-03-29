# omezarr_to_ims

Basic FUSE test mount for exposing a fake `test.ims` file and printing filesystem operations.

This repo should use the Python environment at `/root/miniconda3/envs/omezarr_to_ims`.

The repo also now includes a generic HDF5 shell prototype for building a sparse chunked file and extracting chunk offsets for later virtualization work.

## Requirements

- Linux with FUSE support installed
- `libfuse3` runtime and development files
- Python from `/root/miniconda3/envs/omezarr_to_ims`
- `pyfuse3`
- `h5py`

Install the Python dependency with:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/pip install pyfuse3
/root/miniconda3/envs/omezarr_to_ims/bin/pip install h5py
```

## Build a generic HDF5 shell

Create a sparse chunked HDF5 file with allocated chunk addresses and no meaningful chunk payloads:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/example_shell.h5 --dataset /data --shape 128,128,64 --chunks 32,32,16 --dtype uint16
```

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
