import re
import time
import traceback

from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QObject, QThread, Signal, Slot, QSize,
    QTimer
)

from indexing import detect_level, IndexWorker, LogIndex, parse_ts_compact
from filelog import MappedLogFile, is_valid_log_file

RE_GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
RE_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
RE_NUM = re.compile(r"\b\d+\b")
RE_QUOTED = re.compile(r"(['\"]).*?\1")
RE_PATH = re.compile(r"([A-Za-z]:\\|/)[\w\-/\\\.]+")
RE_MULTI_WS = re.compile(r"\s+")
RE_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
RE_EMAIL = re.compile(r"\b[\w\.-]+@[\w\.-]+\.\w+\b")
RE_BRACKETS = re.compile(r"\[[^\]]*\]|\([^\)]*\)|\{[^\}]*\}")

def normalize_message_for_cluster(msg: str) -> str:
    """
    Turn a message into a stable-ish cluster key by removing variable parts.
    """
    s = msg.strip()
    s = RE_QUOTED.sub("<str>", s)
    s = RE_GUID.sub("<guid>", s)
    s = RE_HEX.sub("<hex>", s)
    s = RE_IP.sub("<ip>", s)
    s = RE_EMAIL.sub("<email>", s)
    s = RE_PATH.sub("<path>", s)
    s = RE_NUM.sub("<num>", s)
    s = RE_BRACKETS.sub(" ", s)  # gets rid of noisy bracket blobs
    s = RE_MULTI_WS.sub(" ", s).strip()
    # Keep it short to avoid monstrous keys
    if len(s) > 180:
        s = s[:180] + "…"
    return s

class FilterWorker(QObject):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(object)     # list[int] row_ids
    failed = Signal(str)

    def __init__(self, mapped_file: MappedLogFile, index: LogIndex,
                 regex_text: str, use_regex: bool,
                 level_mask: set,
                 time_bucket_minute: int | None):
        super().__init__()
        self.mf = mapped_file
        self.idx = index
        self.regex_text = regex_text
        self.use_regex = use_regex
        self.level_mask = level_mask
        self.time_bucket_minute = time_bucket_minute
        self._cancel = False

    @Slot()
    def run(self):
        try:
            self.status.emit("Filtering…")
            rx = None
            if self.use_regex and self.regex_text.strip():
                try:
                    rx = re.compile(self.regex_text)
                except re.error as e:
                    self.failed.emit(f"Regex error: {e}")
                    return

            out = []
            total = self.idx.total_lines
            last_report = time.time()

            # Iterate by line number; read message on demand only if needed
            for i in range(total):
                if self._cancel:
                    self.status.emit("Filtering cancelled.")
                    self.finished.emit(out)
                    return

                # Level filter from precomputed metadata
                lvl_int = int(self.idx.level_ints[i]) if i < len(self.idx.level_ints) else 255
                if self.level_mask and lvl_int != 255 and INT_TO_LEVEL.get(lvl_int) not in self.level_mask:
                    continue
                if self.level_mask and lvl_int == 255:
                    # Unknown level: keep it (common in raw logs); comment out to drop unknown:
                    pass

                # Time bucket filter (minute key)
                if self.time_bucket_minute is not None:
                    mk = int(self.idx.minute_keys[i]) if i < len(self.idx.minute_keys) else 0
                    if mk != self.time_bucket_minute:
                        continue

                # Regex filter reads full line only if rx is active
                if rx is not None:
                    offset = int(self.idx.offsets[i])
                    line = self.mf.readline_at(offset)
                    if not rx.search(line):
                        continue

                out.append(i)

                now = time.time()
                if now - last_report > 0.12:
                    pct = int((i / max(1, total)) * 100)
                    self.progress.emit(pct)
                    self.status.emit(f"Filtering… {pct}% | matches {len(out):,}")
                    last_report = now

            self.progress.emit(100)
            self.status.emit(f"Filtering done: {len(out):,} matches")
            self.finished.emit(out)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def cancel(self):
        self._cancel = True

class ClusterWorker(QObject):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(object)     # list[tuple[count, cluster_key, sample_line]]
    failed = Signal(str)

    def __init__(self, mapped_file: MappedLogFile, index: LogIndex, view_rows: list[int],
                 only_errors: bool = True, max_clusters: int = 50):
        super().__init__()
        self.mf = mapped_file
        self.idx = index
        self.view_rows = view_rows
        self.only_errors = only_errors
        self.max_clusters = max_clusters
        self._cancel = False

    @Slot()
    def run(self):
        try:
            self.status.emit("Clustering…")
            counts = Counter()
            sample = {}
            n = len(self.view_rows)
            last_report = time.time()

            for j, row in enumerate(self.view_rows):
                if self._cancel:
                    self.status.emit("Clustering cancelled.")
                    self.finished.emit([])
                    return

                lvl_int = int(self.idx.level_ints[row]) if row < len(self.idx.level_ints) else 255
                lvl = INT_TO_LEVEL.get(lvl_int, "")
                line = None

                if self.only_errors:
                    # Conservative error heuristic: level ERROR+ or contains exception keywords
                    if lvl not in ("ERROR", "FATAL", "CRITICAL"):
                        # peek a small prefix, cheap-ish
                        offset = int(self.idx.offsets[row])
                        prefix = self.mf.readline_at(offset, max_bytes=4096)
                        up = prefix.upper()
                        if "EXCEPTION" not in up and "TRACEBACK" not in up and "FAILED" not in up and "ERROR" not in up:
                            continue
                        line = prefix

                if line is None:
                    offset = int(self.idx.offsets[row])
                    line = self.mf.readline_at(offset, max_bytes=64 * 1024)

                # Remove timestamp/level prefix in a naive way
                # Keep the "meat" for clustering
                msg = line
                if len(msg) > 32:
                    # if timestamp detected, cut after it
                    if parse_ts_compact(msg)[0] is not None:
                        msg = msg[19:].lstrip(" -\t|")
                # Normalize
                key = normalize_message_for_cluster(msg)
                if not key:
                    continue

                counts[key] += 1
                if key not in sample:
                    sample[key] = line[:5000]

                now = time.time()
                if now - last_report > 0.15:
                    pct = int((j / max(1, n)) * 100)
                    self.progress.emit(pct)
                    self.status.emit(f"Clustering… {pct}% | unique {len(counts):,}")
                    last_report = now

            top = counts.most_common(self.max_clusters)
            results = [(c, k, sample.get(k, "")) for (k, c) in top]
            self.progress.emit(100)
            self.status.emit(f"Clustering done: {len(results)} clusters")
            self.finished.emit(results)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def cancel(self):
        self._cancel = True
