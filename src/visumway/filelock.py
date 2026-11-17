"""Process locks that the OS releases when a process exits."""
from __future__ import annotations

import errno
import os
from contextlib import contextmanager


class LockBusy(OSError):
    pass


@contextmanager
def exclusive(path, *, blocking=True):
    with path.open("a+b") as file:
        file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(file.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
                fcntl.flock(file.fileno(), flags)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise LockBusy(f"Another VisumWay process is using {path.name}") from exc
            raise
        yield  # Closing the handle releases the lock, including on error.
