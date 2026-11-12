"""Windows inter-process leases for the flock operations used by this project."""
import errno
import msvcrt
import os
import time

LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8

def flock(fd, operation):
    if not isinstance(fd, int):
        fd = fd.fileno()
    # Lock a sentinel byte beyond the payload. Audit readers use a second handle.
    original = os.lseek(fd, 0, os.SEEK_CUR)
    try:
        os.lseek(fd, 1 << 40, os.SEEK_SET)
        if operation == LOCK_UN:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return
        if operation not in (LOCK_EX, LOCK_EX | LOCK_NB):
            raise ValueError("Unsupported file lock")
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EDEADLK):
                    raise
                if operation & LOCK_NB:
                    raise BlockingIOError("Lease held by another process") from error
                time.sleep(0.05)
    finally:
        os.lseek(fd, original, os.SEEK_SET)
