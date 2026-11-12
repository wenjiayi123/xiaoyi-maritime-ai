"""Commit a flushed temporary file beside its destination."""
import os
from pathlib import Path


def publish_file(temporary: Path, target: Path) -> None:
    if temporary.parent.resolve() != target.parent.resolve():
        raise ValueError("Journal replacement requires a same-directory temporary file")
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        move = ctypes.WinDLL("kernel32", use_last_error=True).MoveFileExW
        move.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
        move.restype = wintypes.BOOL
        replace_existing, write_through = 0x1, 0x8
        if not move(str(temporary.absolute()), str(target.absolute()), replace_existing | write_through):
            raise ctypes.WinError(ctypes.get_last_error())
        return
    temporary.replace(target)
    descriptor = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
