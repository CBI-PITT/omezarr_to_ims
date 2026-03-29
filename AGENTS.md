# AGENTS.md

Repository guidance for coding agents working in `/mnt/c/code/omezarr_to_ims`.

## Scope

- This repository is currently a small Python-based FUSE test harness.
- The main runtime file is `mount_test_fs.py`.
- The main launcher is `run_test_mount.sh`.
- The HDF5 shell prototype and Imaris-style shell builder live in `build_hdf5_shell.py` and `extract_chunk_map.py`.
- The affine shell helpers live in `extract_affine_manifest.py` and `affine_lookup.py`.
- The pre-FUSE routing helpers live in `read_segments.py` and `build_zarr_mapping.py`.
- The OME-Zarr bridge helpers live in `zarr_backend.py`, `materialize_read.py`, and `mount_virtual_hdf5.py`.
- There is no package layout, no formal build system, and no automated test suite yet.

## Local Environment

- Use only the Python environment at `/root/miniconda3/envs/omezarr_to_ims`.
- Prefer explicit interpreter paths over `python`, `pip`, or activated-shell assumptions.
- Expected OS is Linux with FUSE 3 available.
- `pyfuse3` is the active FUSE binding.
- `h5py` is used for the generic HDF5 shell prototype.
- `ome_zarr_multiscale_writer` provides the OME-Zarr reader backend.
- `fusermount3` is the expected unmount command.

## Existing Instruction Files

- No `.cursor/rules/` directory was found at the time this file was written.
- No `.cursorrules` file was found.
- No `.github/copilot-instructions.md` file was found.
- If any of those files are added later, treat them as higher-priority guidance and update this file.

## Repository Layout

- `mount_test_fs.py` - single-file pyfuse3 filesystem exposing a fake `test.ims` file.
- `run_test_mount.sh` - convenience wrapper that invokes the required Python interpreter.
- `build_hdf5_shell.py` - creates a sparse chunked HDF5 shell with early chunk allocation.
- `extract_chunk_map.py` - extracts chunk coordinate to file offset mappings from the shell.
- `extract_affine_manifest.py` - emits compact affine dataset descriptors instead of a full chunk map.
- `affine_lookup.py` - resolves file offsets to chunk and voxel locations in `TCZYX` order.
- `build_zarr_mapping.py` - creates a one-store mapping from shell datasets to OME-Zarr arrays.
- `read_segments.py` - splits file read ranges into metadata and chunk-backed data segments.
- `zarr_backend.py` - reads OME-Zarr level metadata and loads whole chunks with `TCZYX` promotion.
- `materialize_read.py` - materializes virtual HDF5 read bytes from shell metadata and OME-Zarr chunk data.
- `mount_virtual_hdf5.py` - pyfuse3 mount that exposes a virtual HDF5 file backed by OME-Zarr.
- `run_virtual_mount.sh` - convenience wrapper that mounts the virtual HDF5 file with the required interpreter.
- `run_from_zarr_mount.sh` - convenience wrapper that rebuilds an Imaris-style `.ims` shell from OME-Zarr and mounts it.
- `README.md` - manual setup and usage notes.
- `pyproject.toml` - editable-install metadata and console-script entry points.
- `__pycache__/` - generated artifacts; do not rely on contents.
- `.idea/` - editor metadata; avoid editing it unless specifically requested.

## Build Commands

- Install the repo in editable mode with:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/pip install -e .
```

- There is no separate build step.
- The closest build-equivalent check is Python bytecode compilation:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python -m py_compile mount_test_fs.py
/root/miniconda3/envs/omezarr_to_ims/bin/python -m py_compile build_hdf5_shell.py extract_chunk_map.py
/root/miniconda3/envs/omezarr_to_ims/bin/python -m py_compile extract_affine_manifest.py affine_lookup.py
/root/miniconda3/envs/omezarr_to_ims/bin/python -m py_compile build_zarr_mapping.py read_segments.py
/root/miniconda3/envs/omezarr_to_ims/bin/python -m py_compile zarr_backend.py materialize_read.py mount_virtual_hdf5.py
```

## Lint Commands

- No lint configuration or lint dependency is currently checked into the repo.
- Do not invent a mandatory linter in routine changes.
- If the user asks for linting, clarify or add tooling only in a way that fits the repository.

## Test Commands

- There is no formal automated test suite yet.
- Current validation is a smoke test against the mounted FUSE filesystem.
- Primary manual test flow:

```bash
mkdir -p /tmp/test-mount
./run_test_mount.sh /tmp/test-mount
```

- In a second shell, verify basic behavior:

```bash
ls -la /tmp/test-mount
cat /tmp/test-mount/test.ims
fusermount3 -u /tmp/test-mount
```

- Expect logs like `getattr`, `lookup`, `readdir`, `open`, and `read` during smoke tests.
- For HDF5 shell work, a useful smoke test is:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/example_shell.h5 --dataset /data --shape 100,200 --chunks 10,20 --dtype uint16
/root/miniconda3/envs/omezarr_to_ims/bin/python extract_chunk_map.py /tmp/example_shell.h5 --dataset /data
/root/miniconda3/envs/omezarr_to_ims/bin/python extract_affine_manifest.py /tmp/example_shell.h5
/root/miniconda3/envs/omezarr_to_ims/bin/python read_segments.py /tmp/example_shell.h5.affine_manifest.json 2048 8192
```

- For OME-Zarr-backed virtual HDF5 work, a useful smoke test is:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/from_zarr.h5 --from-zarr "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
/root/miniconda3/envs/omezarr_to_ims/bin/python extract_affine_manifest.py /tmp/from_zarr.h5
/root/miniconda3/envs/omezarr_to_ims/bin/python build_zarr_mapping.py /tmp/from_zarr.h5.affine_manifest.json "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
/root/miniconda3/envs/omezarr_to_ims/bin/python materialize_read.py /tmp/from_zarr.h5 /tmp/from_zarr.h5.affine_manifest.json /tmp/from_zarr.h5.affine_manifest.json.zarr_map.json 2048 64 --hex
```

- For Imaris-style shell work, a useful smoke test is:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/from_zarr.ims --imaris-from-zarr "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
/root/miniconda3/envs/omezarr_to_ims/bin/python extract_affine_manifest.py /tmp/from_zarr.ims
/root/miniconda3/envs/omezarr_to_ims/bin/python build_zarr_mapping.py /tmp/from_zarr.ims.affine_manifest.json "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
/root/miniconda3/envs/omezarr_to_ims/bin/python materialize_read.py /tmp/from_zarr.ims /tmp/from_zarr.ims.affine_manifest.json /tmp/from_zarr.ims.affine_manifest.json.zarr_map.json 11826310624 64 --hex
```

## Running A Single Test

- Since no test framework exists, a “single test” means running one targeted smoke-check command.
- Directory listing only:

```bash
ls -la /tmp/test-mount
```

- File read only:

```bash
cat /tmp/test-mount/test.ims
```

- Syntax-only single check:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python -m py_compile mount_test_fs.py
```

- Shell builder single check:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/example_shell.h5 --dataset /data --shape 100,200 --chunks 10,20 --dtype uint16
```

- From-Zarr shell single check:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/from_zarr.h5 --from-zarr "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
```

- Imaris-style shell single check:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python build_hdf5_shell.py /tmp/from_zarr.ims --imaris-from-zarr "/mnt/c/code/test_data/Mag16_Tile0_Ch488_Flt525_50_(GFP)_Sh1_Rot0.0.ome.zarr"
```

- Affine lookup single check:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python affine_lookup.py /tmp/example_shell.h5.affine_manifest.json 2048
```

- Read segmentation single check:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python read_segments.py /tmp/example_shell.h5.affine_manifest.json 2048 8192
```

- Materialized read single check:

```bash
/root/miniconda3/envs/omezarr_to_ims/bin/python materialize_read.py /tmp/from_zarr.h5 /tmp/from_zarr.h5.affine_manifest.json /tmp/from_zarr.h5.affine_manifest.json.zarr_map.json 2048 64 --hex
```

- If a future test framework is introduced, replace this section with the exact single-test invocation.

## Preferred Validation Workflow

- First run `py_compile` on edited Python files.
- Then run the smallest relevant smoke test.
- For filesystem logic changes, prefer a fresh temporary mountpoint such as `/tmp/testmount_agent`.
- Always unmount the filesystem after manual validation.
- If a mount crashes, inspect the foreground logs before changing code.

## Python Style

- Follow PEP 8 unless the repository establishes a different convention later.
- Use 4-space indentation.
- Keep lines readable; avoid dense one-liners.
- Prefer straightforward control flow over clever compression.
- Use ASCII by default unless a file already requires Unicode.

## Imports

- Group imports in this order: standard library, third-party, local.
- Separate import groups with a single blank line.
- Avoid unused imports.
- If a dependency is optional or platform-sensitive, make that explicit in code or docs.

## Formatting

- Match the existing repository style before introducing new formatting patterns.
- Preserve simple blank-line spacing around top-level definitions.
- Do not add comments for obvious code.
- Add short comments only when a FUSE or pyfuse3 behavior is non-obvious.

## Types

- The current codebase uses little to no explicit type annotation.
- It is acceptable to add type hints where they improve clarity, especially around pyfuse3 handlers.
- Keep new types consistent within a file; do not partially over-annotate in a noisy way.

## Naming Conventions

- Use `snake_case` for functions, variables, and helper methods.
- Use `PascalCase` for classes.
- Use descriptive names for FUSE handlers and helper methods.
- Avoid abbreviations unless they match domain terminology like FUSE, inode, or fh.

## Error Handling

- For FUSE request handlers, raise `pyfuse3.FUSEError` with the correct `errno` value.
- Return read-only errors consistently for write attempts.
- Prefer explicit `ENOENT`, `EROFS`, `EACCES`, or other accurate errno values over generic failures.
- Keep mount startup failures user-readable.

## Logging And Output

- This repository currently uses plain `print(...)` logging for FUSE operations.
- Preserve that lightweight approach unless the user asks for structured logging.
- Flush output when immediate visibility matters.
- Keep operation logs short and argument-focused.

## Shell Script Conventions

- Use `#!/usr/bin/env bash` and `set -euo pipefail` for helper scripts.
- Quote variable expansions.
- Validate argument count early.
- Use `exec` when the script should hand off directly to Python.

## Dependency Changes

- Avoid changing Python runtimes.
- Do not switch away from `/root/miniconda3/envs/omezarr_to_ims` unless explicitly requested.
- Prefer minimal dependencies.
- If a new dependency is required, update `README.md` and this file.

## Editing Guidance

- Keep the repository simple.
- Prefer small, surgical edits over broad rewrites.
- Do not add a new framework, package manager, or test runner without a clear request.
- Do not edit generated files in `__pycache__/`.
- Ignore unrelated editor metadata unless the task is about editor setup.

## Before Finishing A Change

- Confirm the code uses the required conda environment paths.
- Run `py_compile` on changed Python files.
- If runtime behavior changed, run a focused mount smoke test.
- Update `README.md` when setup or usage changes.
- If new repo-specific instruction files appear, mirror their guidance here.
