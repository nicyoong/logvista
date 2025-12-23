from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QObject, QThread, Signal, Slot, QSize,
    QTimer
)
from PySide6.QtGui import QAction, QFont, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QHBoxLayout, QVBoxLayout,
    QLineEdit, QPushButton, QLabel, QCheckBox, QSplitter, QTableView,
    QProgressBar, QMessageBox, QStatusBar, QComboBox, QDockWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QTextEdit, QDialog, QDialogButtonBox, QFormLayout,
    QSpinBox, QToolBar
)

class TimelineWidget(QWidget):
    bucketClicked = Signal(int)  # minute_key

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(90)
        self._bins = []      # list[(minute_key, count)]
        self._max = 1
        self._hover = -1

    def set_bins(self, bins: list[tuple[int, int]]):
        self._bins = bins
        self._max = max([c for _, c in bins], default=1)
        self._hover = -1
        self.update()

    def sizeHint(self):
        return QSize(400, 110)

    def paintEvent(self, ev):
        p = QPainter()
        p.begin(self)
        p.fillRect(self.rect(), QColor(250, 250, 250))

        r = self.rect().adjusted(10, 10, -10, -28)
        p.setPen(QPen(QColor(200, 200, 200)))
        p.drawRect(r)

        if not self._bins:
            p.setPen(QPen(QColor(120, 120, 120)))
            p.drawText(self.rect(), Qt.AlignCenter, "Timeline: (no data)")
            return

        n = len(self._bins)
        bar_w = max(1, r.width() // n)
        # draw bars
        for i, (_, c) in enumerate(self._bins):
            x = r.left() + i * bar_w
            h = int((c / max(1, self._max)) * r.height())
            y = r.bottom() - h + 1
            bar = (x, y, bar_w, h)
            if i == self._hover:
                p.fillRect(*bar, QColor(120, 180, 255))
            else:
                p.fillRect(*bar, QColor(160, 160, 160))

        # axis labels (first/last minute)
        p.setPen(QPen(QColor(90, 90, 90)))
        first = self._bins[0][0]
        last = self._bins[-1][0]
        p.drawText(10, self.height() - 8, self._format_minute(first))
        txt = self._format_minute(last)
        p.drawText(self.width() - 10 - p.fontMetrics().horizontalAdvance(txt), self.height() - 8, txt)
        p.end()

    def _format_minute(self, mk: int) -> str:
        # mk = YYYYMMDDHHMM
        s = str(mk).rjust(12, "0")
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"

    def mouseMoveEvent(self, ev):
        if not self._bins:
            return
        r = self.rect().adjusted(10, 10, -10, -28)
        if not r.contains(ev.position().toPoint()):
            if self._hover != -1:
                self._hover = -1
                self.update()
            return
        n = len(self._bins)
        bar_w = max(1, r.width() // n)
        i = (ev.position().toPoint().x() - r.left()) // bar_w
        i = int(max(0, min(n - 1, i)))
        if i != self._hover:
            self._hover = i
            self.update()

    def leaveEvent(self, ev):
        if self._hover != -1:
            self._hover = -1
            self.update()

    def mousePressEvent(self, ev):
        if not self._bins:
            return
        if ev.button() != Qt.LeftButton:
            return
        r = self.rect().adjusted(10, 10, -10, -28)
        if not r.contains(ev.position().toPoint()):
            return
        n = len(self._bins)
        bar_w = max(1, r.width() // n)
        i = (ev.position().toPoint().x() - r.left()) // bar_w
        i = int(max(0, min(n - 1, i)))
        mk = self._bins[i][0]
        self.bucketClicked.emit(mk)
