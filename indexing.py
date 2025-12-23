from array import array
from dataclasses import dataclass

# Detect a timestamp early in the line (common formats)
# We'll parse a compact numeric key: YYYYMMDDHHMMSS (int) and a minute bucket: YYYYMMDDHHMM (int)
def parse_ts_compact(line: str):
    """
    Returns (sec_key, minute_key) where:
      sec_key    = YYYYMMDDHHMMSS as int
      minute_key = YYYYMMDDHHMM as int
    Or (None, None) if not parseable.

    Supports:
      2025-12-24 15:04:05
      2025-12-24T15:04:05
      2025-12-24 15:04:05,123
      2025-12-24 15:04:05.123
    """
    if len(line) < 19:
        return None, None
    s = line[:19]
    # Accept space or 'T' between date/time
    if not (s[4] == "-" and s[7] == "-" and (s[10] == " " or s[10] == "T") and s[13] == ":" and s[16] == ":"):
        return None, None

    try:
        y = int(s[0:4]); mo = int(s[5:7]); d = int(s[8:10])
        hh = int(s[11:13]); mm = int(s[14:16]); ss = int(s[17:19])
        sec_key = (((((y * 100 + mo) * 100 + d) * 100 + hh) * 100 + mm) * 100 + ss)
        minute_key = ((((y * 100 + mo) * 100 + d) * 100 + hh) * 100 + mm)
        return sec_key, minute_key
    except ValueError:
        return None, None

def detect_level(line: str):
    """
    Best-effort level detection.
    Checks common tokens early in the line, then a broader search.
    """
    upper = line[:200].upper()
    # Fast path: look for " INFO " style
    for w in (" TRACE ", " DEBUG ", " INFO ", " WARN ", " WARNING ", " ERROR ", " FATAL ", " CRITICAL "):
        if w in upper:
            token = w.strip()
            return LEVEL_CANON.get(token, token)

    # Fallback: [INFO], (ERROR), INFO:
    for w in LEVEL_WORDS:
        if f"[{w}]" in upper or f"({w})" in upper or f"{w}:" in upper:
            return LEVEL_CANON.get(w, w)

    return ""

@dataclass
class LogIndex:
    offsets: array  # 'Q' line start offsets
    minute_keys: array  # 'Q' minute bucket (YYYYMMDDHHMM) or 0 if unknown
    level_ints: array  # 'B' severity enum, 255 if unknown
    total_lines: int
    file_size: int

    @staticmethod
    def empty():
        return LogIndex(array("Q"), array("Q"), array("B"), 0, 0)

class IndexWorker(QObject):
    progress = Signal(int)            # 0..100
    status = Signal(str)
    finished = Signal(object)         # LogIndex
    failed = Signal(str)

    def __init__(self, path: str, chunk_size: int = 8 * 1024 * 1024):
        super().__init__()
        self.path = path
        self.chunk_size = chunk_size
        self._cancel = False

    @Slot()
    def run(self):
        try:
            self.status.emit("Indexing file (streaming offsets)…")
            size = os.path.getsize(self.path)
            offsets = array("Q")
            minute_keys = array("Q")
            level_ints = array("B")

            offsets.append(0)
            minute_keys.append(0)
            level_ints.append(255)

            with open(self.path, "rb") as f:
                buf = b""
                pos = 0
                last_report = time.time()
                while True:
                    if self._cancel:
                        self.status.emit("Indexing cancelled.")
                        self.finished.emit(LogIndex.empty())
                        return
                    data = f.read(self.chunk_size)
                    if not data:
                        break
                    buf += data

                    # Process full lines in buffer
                    start = 0
                    while True:
                        nl = buf.find(b"\n", start)
                        if nl == -1:
                            break
                        # Next line starts at pos + nl + 1
                        line_start_offset = pos + nl + 1
                        offsets.append(line_start_offset)

                        # Lightweight metadata extraction from this line (text decode limited)
                        # We decode a small prefix only, which is cheap.
                        prefix_bytes = buf[start:min(start + 256, nl)]
                        line_prefix = prefix_bytes.decode("utf-8", errors="replace")

                        _, mk = parse_ts_compact(line_prefix)
                        minute_keys.append(mk if mk is not None else 0)

                        lvl = detect_level(line_prefix)
                        if lvl:
                            level_ints.append(LEVEL_TO_INT.get(lvl, 255))
                        else:
                            level_ints.append(255)

                        start = nl + 1

                    # Keep remainder
                    buf = buf[start:]
                    pos += len(data)

                    now = time.time()
                    if now - last_report > 0.1:
                        pct = int((pos / max(1, size)) * 100)
                        self.progress.emit(min(100, pct))
                        self.status.emit(f"Indexing… {pct}% | lines ~{len(offsets):,}")
                        last_report = now

            total_lines = max(0, len(offsets) - 1)  # last offset may be EOF start
            idx = LogIndex(offsets, minute_keys, level_ints, total_lines, size)
            self.progress.emit(100)
            self.status.emit(f"Index complete: {total_lines:,} lines")
            self.finished.emit(idx)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def cancel(self):
        self._cancel = True