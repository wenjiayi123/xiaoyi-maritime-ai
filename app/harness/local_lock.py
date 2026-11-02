"""OS releases this local executor lease on process exit, including a crash."""
from __future__ import annotations

import fcntl

from app.harness.store import Conflict


class ProcessLease:
    def __init__(self, path):
        self.path = path
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            raise Conflict("当前进程已持有执行资源")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            raise Conflict("另一进程仍在执行任务，未重复启动或误判中断") from None
        self.handle = handle
        return self

    def release(self):
        if self.handle is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None
