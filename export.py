import html
import json
import traceback
from collections import OrderedDict, Counter, defaultdict
from datetime import datetime

from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QObject, QThread, Signal, Slot, QSize,
    QTimer
)

from indexing import detect_level, IndexWorker, LogIndex, parse_ts_compact, INT_TO_LEVEL
from filelog import MappedLogFile, is_valid_log_file
from settings import APP_NAME

class ExportWorker(QObject):
    progress = Signal(int)
    status = Signal(str)
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, fmt: str, out_path: str,
                 mapped_file: MappedLogFile, index: LogIndex, view_rows: list[int],
                 max_rows: int | None = None):
        super().__init__()
        self.fmt = fmt  # 'csv', 'jsonl', 'html'
        self.out_path = out_path
        self.mf = mapped_file
        self.idx = index
        self.view_rows = view_rows
        self.max_rows = max_rows
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _line_fields(self, row: int):
        offset = int(self.idx.offsets[row])
        line = self.mf.readline_at(offset, max_bytes=256 * 1024)

        sec_key, _ = parse_ts_compact(line)
        ts = line[:19] if sec_key is not None else ""

        lvl_int = int(self.idx.level_ints[row]) if row < len(self.idx.level_ints) else 255
        lvl = INT_TO_LEVEL.get(lvl_int, "")

        # Message (trim potential timestamp)
        msg = line
        if ts:
            msg = line[19:].lstrip(" -\t|")
        return ts, lvl, msg

    @Slot()
    def run(self):
        try:
            rows = self.view_rows
            if self.max_rows is not None:
                rows = rows[: self.max_rows]

            n = len(rows)
            self.status.emit(f"Exporting {n:,} rows…")

            if self.fmt == "csv":
                import csv
                with open(self.out_path, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["timestamp", "level", "message"])
                    for i, row in enumerate(rows):
                        if self._cancel:
                            self.finished.emit("Export cancelled.")
                            return
                        ts, lvl, msg = self._line_fields(row)
                        w.writerow([ts, lvl, msg])

                        if i % 2000 == 0:
                            self.progress.emit(int((i / max(1, n)) * 100))
                self.progress.emit(100)
                self.finished.emit(f"CSV exported: {self.out_path}")

            elif self.fmt == "jsonl":
                with open(self.out_path, "w", encoding="utf-8") as f:
                    for i, row in enumerate(rows):
                        if self._cancel:
                            self.finished.emit("Export cancelled.")
                            return
                        ts, lvl, msg = self._line_fields(row)
                        obj = {"timestamp": ts, "level": lvl, "message": msg}
                        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                        if i % 2500 == 0:
                            self.progress.emit(int((i / max(1, n)) * 100))
                self.progress.emit(100)
                self.finished.emit(f"JSONL exported: {self.out_path}")

            elif self.fmt == "html":
                # lightweight HTML report: summary + first N table
                max_preview = min(n, 5000)
                counts_by_level = Counter()
                for row in rows:
                    lvl_int = int(self.idx.level_ints[row]) if row < len(self.idx.level_ints) else 255
                    lvl = INT_TO_LEVEL.get(lvl_int, "UNKNOWN" if lvl_int == 255 else "")
                    counts_by_level[lvl] += 1

                def esc(x): return html.escape(x or "")

                with open(self.out_path, "w", encoding="utf-8") as f:
                    f.write("<!doctype html><html><head><meta charset='utf-8'>")
                    f.write(f"<title>{esc(APP_NAME)} Report</title>")
                    f.write("""
<style>
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:20px;}
h1{margin:0 0 8px 0;}
.small{color:#666;font-size:12px;}
table{border-collapse:collapse;width:100%;margin-top:12px;}
th,td{border:1px solid #ddd;padding:6px;font-size:12px;vertical-align:top;}
th{background:#f6f6f6;text-align:left;position:sticky;top:0;}
code{background:#f2f2f2;padding:1px 4px;border-radius:4px;}
</style>
</head><body>
""")
                    f.write(f"<h1>{esc(APP_NAME)} Report</h1>")
                    f.write(f"<div class='small'>Generated: {esc(datetime.now().isoformat(sep=' ', timespec='seconds'))}</div>")
                    f.write("<h2>Summary</h2>")
                    f.write("<ul>")
                    f.write(f"<li>Total matched rows: <code>{n:,}</code></li>")
                    for lvl, c in counts_by_level.most_common():
                        f.write(f"<li>{esc(lvl)}: <code>{c:,}</code></li>")
                    f.write("</ul>")

                    f.write("<h2>Preview (first up to 5000 rows)</h2>")
                    f.write("<table><thead><tr><th>#</th><th>Timestamp</th><th>Level</th><th>Message</th></tr></thead><tbody>")
                    for i, row in enumerate(rows[:max_preview]):
                        if self._cancel:
                            self.finished.emit("Export cancelled.")
                            return
                        ts, lvl, msg = self._line_fields(row)
                        f.write("<tr>")
                        f.write(f"<td>{i+1}</td><td>{esc(ts)}</td><td>{esc(lvl)}</td><td>{esc(msg)}</td>")
                        f.write("</tr>")
                        if i % 1000 == 0:
                            self.progress.emit(int((i / max(1, max_preview)) * 100))
                    f.write("</tbody></table>")
                    f.write("</body></html>")

                self.progress.emit(100)
                self.finished.emit(f"HTML report exported: {self.out_path}")

            else:
                self.failed.emit(f"Unknown export format: {self.fmt}")

        except Exception:
            self.failed.emit(traceback.format_exc())