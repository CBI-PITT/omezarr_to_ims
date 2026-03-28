# omezarr_to_ims

Basic FUSE test mount for exposing a fake `test.ims` file and printing filesystem operations.

This repo should use the Python environment at `/root/miniconda3/envs/omezarr_to_ims`.

## Requirements

- Linux with FUSE support installed
- `libfuse3` runtime and development files
- Python from `/root/miniconda3/envs/omezarr_to_ims`
- `pyfuse3`

Install the Python dependency with:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/pip install pyfuse3
```

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
