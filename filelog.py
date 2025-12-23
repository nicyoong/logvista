import mmap
import os


class MappedLogFile:
    def __init__(self):
        self.path = None
        self.size = 0
        self._fh = None
        self._mm = None

    def open(self, path: str):
        self.close()
        self.path = path
        self.size = os.path.getsize(path)
        self._fh = open(path, "rb")
        # 0 maps the whole file; OS handles paging (works with multi-GB)
        self._mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)

    def close(self):
        if self._mm is not None:
            try:
                self._mm.close()
            except Exception:
                pass
        self._mm = None
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
        self._fh = None
        self.path = None
        self.size = 0

    def readline_at(self, offset: int, max_bytes: int = 1024 * 1024):
        """
        Read a single line starting at byte offset (0-based), up to the next newline.
        Safeguard max_bytes to avoid accidental huge memory if file has a single mega-line.
        Returns decoded text (utf-8 with replacement).
        """
        if self._mm is None:
            return ""
        end = self._mm.find(b"\n", offset)
        if end == -1:
            end = self.size
        if end - offset > max_bytes:
            end = offset + max_bytes
        b = self._mm[offset:end]
        # trim possible \r
        if b.endswith(b"\r"):
            b = b[:-1]
        return b.decode("utf-8", errors="replace")

    def slice_bytes(self, start: int, end: int):
        if self._mm is None:
            return b""
        end = min(end, self.size)
        return self._mm[start:end]


def is_valid_log_file(path: str) -> bool:
    """
    Accepts ONLY readable, text-based .log files.
    """
    if not path:
        return False

    if not os.path.isfile(path):
        return False

    if not path.lower().endswith(".log"):
        return False

    # Reject symlinks (safety)
    if os.path.islink(path):
        return False

    # Quick binary check: read first 8KB
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
            if b"\x00" in chunk:
                return False  # binary file
    except Exception:
        return False

    return True
