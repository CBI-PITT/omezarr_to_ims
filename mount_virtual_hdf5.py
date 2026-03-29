#!/root/miniconda3/envs/omezarr_to_ims/bin/python

import argparse
import errno
import os
import stat
import sys
import time

import pyfuse3
import trio

from affine_lookup import parse_manifest
from materialize_read import materialize_read
from zarr_backend import OmeZarrBackend, load_zarr_mapping


class VirtualHDF5Filesystem(pyfuse3.Operations):
    def __init__(self, shell_path, manifest_path, zarr_map_path):
        super().__init__()
        self.root_inode = pyfuse3.ROOT_INODE
        self.file_inode = pyfuse3.InodeT(self.root_inode + 1)
        self.shell_path = shell_path
        self.filename = os.path.basename(shell_path).encode("utf-8")
        self.shell_file = open(shell_path, "rb")
        self.file_size = os.path.getsize(shell_path)
        self.manifest = parse_manifest(manifest_path)
        self.zarr_mapping = load_zarr_mapping(zarr_map_path)
        self.backend = OmeZarrBackend(self.zarr_mapping["store"])
        for dataset in self.manifest["datasets"]:
            target = self.zarr_mapping["datasets"][dataset["path"]]
            self.backend.validate_shell_dataset(
                dataset["path"],
                target,
                dataset["shape"],
                dataset["chunks"],
                dataset["dtype"],
            )
        self.now_ns = int(time.time() * 1_000_000_000)

    def close(self):
        self.shell_file.close()

    def _log(self, operation, **details):
        if details:
            detail_text = " ".join(f"{key}={value}" for key, value in details.items())
            print(f"{operation} {detail_text}", flush=True)
        else:
            print(operation, flush=True)

    def _make_attrs(self, inode):
        attrs = pyfuse3.EntryAttributes()
        attrs.st_ino = inode
        attrs.generation = 0
        attrs.entry_timeout = 0
        attrs.attr_timeout = 0
        attrs.st_uid = os.getuid()
        attrs.st_gid = os.getgid()
        attrs.st_rdev = 0
        attrs.st_blksize = 4096
        attrs.st_atime_ns = self.now_ns
        attrs.st_mtime_ns = self.now_ns
        attrs.st_ctime_ns = self.now_ns

        if inode == self.root_inode:
            attrs.st_mode = stat.S_IFDIR | 0o555
            attrs.st_nlink = 2
            attrs.st_size = 0
            attrs.st_blocks = 0
            return attrs

        if inode == self.file_inode:
            attrs.st_mode = stat.S_IFREG | 0o444
            attrs.st_nlink = 1
            attrs.st_size = self.file_size
            attrs.st_blocks = (attrs.st_size + 511) // 512
            return attrs

        raise pyfuse3.FUSEError(errno.ENOENT)

    async def lookup(self, parent_inode, name, ctx):
        self._log("lookup", parent_inode=parent_inode, name=name.decode("utf-8", "replace"))
        if parent_inode == self.root_inode and name in (b".", b".."):
            return self._make_attrs(self.root_inode)
        if parent_inode == self.root_inode and name == self.filename:
            return self._make_attrs(self.file_inode)
        raise pyfuse3.FUSEError(errno.ENOENT)

    async def forget(self, inode_list):
        self._log("forget", inode_list=inode_list)

    async def getattr(self, inode, ctx=None):
        self._log("getattr", inode=inode)
        return self._make_attrs(inode)

    async def opendir(self, inode, ctx):
        self._log("opendir", inode=inode)
        if inode != self.root_inode:
            raise pyfuse3.FUSEError(errno.ENOENT)
        return pyfuse3.FileHandleT(inode)

    async def readdir(self, fh, start_id, token):
        self._log("readdir", fh=fh, start_id=start_id)
        if fh != self.root_inode:
            raise pyfuse3.FUSEError(errno.ENOENT)
        if start_id == 0:
            pyfuse3.readdir_reply(token, self.filename, self._make_attrs(self.file_inode), 1)

    async def releasedir(self, fh):
        self._log("releasedir", fh=fh)

    async def open(self, inode, flags, ctx):
        self._log("open", inode=inode, flags=flags)
        if inode != self.file_inode:
            raise pyfuse3.FUSEError(errno.ENOENT)
        if (flags & os.O_ACCMODE) != os.O_RDONLY:
            raise pyfuse3.FUSEError(errno.EROFS)
        return pyfuse3.FileInfo(fh=pyfuse3.FileHandleT(inode))

    async def read(self, fh, off, size):
        self._log("read", fh=fh, offset=off, size=size)
        if fh != self.file_inode:
            raise pyfuse3.FUSEError(errno.ENOENT)
        return materialize_read(self.shell_file, self.manifest, self.zarr_mapping, self.backend, off, size)

    async def release(self, fh):
        self._log("release", fh=fh)

    async def access(self, inode, mode, ctx):
        self._log("access", inode=inode, mode=mode)
        self._make_attrs(inode)
        if inode == self.file_inode and mode & os.W_OK:
            return False
        return True

    async def statfs(self, ctx):
        self._log("statfs")
        stats = pyfuse3.StatvfsData()
        stats.f_bsize = 4096
        stats.f_frsize = 4096
        stats.f_blocks = max(1, (self.file_size + 4095) // 4096)
        stats.f_bfree = 0
        stats.f_bavail = 0
        stats.f_files = 2
        stats.f_ffree = 0
        stats.f_favail = 0
        stats.f_namemax = 255
        return stats


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Mount a virtual read-only HDF5 file backed by OME-Zarr")
    parser.add_argument("mountpoint", help="Directory to mount the virtual HDF5 file on")
    parser.add_argument("shell", help="Path to the shell HDF5 file")
    parser.add_argument("manifest", help="Path to the affine manifest JSON")
    parser.add_argument("zarr_map", help="Path to the one-store Zarr mapping JSON")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not os.path.isdir(args.mountpoint):
        print(f"Mountpoint does not exist or is not a directory: {args.mountpoint}")
        return 1

    operations = VirtualHDF5Filesystem(args.shell, args.manifest, args.zarr_map)
    fuse_options = set(pyfuse3.default_options)
    fuse_options.add("fsname=virtual_hdf5")
    fuse_options.add("ro")
    fuse_options.discard("default_permissions")

    print(f"Mounting virtual HDF5 file at {args.mountpoint}", flush=True)
    print(f"Exposing read-only file /{operations.filename.decode('utf-8')}", flush=True)

    pyfuse3.init(operations, args.mountpoint, fuse_options)
    try:
        trio.run(pyfuse3.main)
    except BaseException as exc:
        interrupted = isinstance(exc, KeyboardInterrupt)
        if not interrupted and isinstance(exc, BaseExceptionGroup):
            matched, remainder = exc.split(KeyboardInterrupt)
            interrupted = matched is not None and remainder is None

        if interrupted:
            print("Received interrupt, unmounting...", flush=True)
            pyfuse3.close()
            operations.close()
            return 130

        pyfuse3.close(unmount=False)
        operations.close()
        raise

    pyfuse3.close()
    operations.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
