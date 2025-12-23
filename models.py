from collections import OrderedDict, Counter, defaultdict

from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QObject, QThread, Signal, Slot, QSize,
    QTimer
)

from indexing import detect_level, IndexWorker, LogIndex, parse_ts_compact
from filelog import MappedLogFile, is_valid_log_file

class LogTableModel(QAbstractTableModel):
    COLS = ["Timestamp", "Level", "Message"]
    def __init__(self, mf: MappedLogFile, index: LogIndex):
        super().__init__()
        self.mf = mf
        self.log_index = index
        self.view_rows = []  # list[int] underlying row ids
        self._cache = OrderedDict()  # row_id -> (ts, lvl, msg)
        self._cache_cap = 4000

    def set_view_rows(self, rows: list[int]):
        self.beginResetModel()
        self.view_rows = rows
        self._cache.clear()
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.view_rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLS[section]
        return str(section + 1)

    def _get_fields(self, row_id: int):
        if row_id in self._cache:
            self._cache.move_to_end(row_id)
            return self._cache[row_id]

        offset = int(self.log_index.offsets[row_id])
        line = self.mf.readline_at(offset, max_bytes=256 * 1024)

        sec_key, _ = parse_ts_compact(line)
        ts = line[:19] if sec_key is not None else ""

        lvl_int = int(self.log_index.level_ints[row_id]) if row_id < len(self.log_index.level_ints) else 255
        lvl = INT_TO_LEVEL.get(lvl_int, "")

        msg = line
        if ts:
            msg = line[19:].lstrip(" -\t|")

        # Cache
        self._cache[row_id] = (ts, lvl, msg)
        if len(self._cache) > self._cache_cap:
            self._cache.popitem(last=False)
        return ts, lvl, msg

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if row < 0 or row >= len(self.view_rows):
            return None

        row_id = self.view_rows[row]
        ts, lvl, msg = self._get_fields(row_id)

        if role == Qt.DisplayRole:
            if col == 0:
                return ts
            if col == 1:
                return lvl
            if col == 2:
                # avoid huge paint operations on monster lines
                return msg if len(msg) <= 5000 else msg[:5000] + "…"
        elif role == Qt.ToolTipRole:
            return msg
        elif role == Qt.ForegroundRole and col == 1:
            if lvl in ("ERROR", "FATAL", "CRITICAL"):
                return QColor(180, 30, 30)
            if lvl in ("WARN",):
                return QColor(160, 110, 0)
        return None

    def get_row_text(self, view_row: int):
        """Return full text for selected row (for details panel)."""
        if view_row < 0 or view_row >= len(self.view_rows):
            return ""
        row_id = self.view_rows[view_row]
        offset = int(self.log_index.offsets[row_id])
        return self.mf.readline_at(offset, max_bytes=1024 * 1024)