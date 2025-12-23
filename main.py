import os
import re
import sys
import json
import time
import mmap
import math
import html
import traceback
from array import array
from dataclasses import dataclass
from datetime import datetime
from collections import OrderedDict, Counter, defaultdict

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

from export import ExportWorker
from filtering import FilterWorker, ClusterWorker
from indexing import detect_level, IndexWorker, LogIndex, parse_ts_compact, LEVEL_ORDER
from filelog import MappedLogFile, is_valid_log_file
from models import LogTableModel
from previewdialog import TextPreviewDialog
from settings import APP_NAME
from timelinewidget import TimelineWidget

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1300, 820)

        self.mf = MappedLogFile()
        self.idx = LogIndex.empty()

        self.index_thread = None
        self.filter_thread = None
        self.cluster_thread = None
        self.export_thread = None

        self.active_time_bucket = None

        # central UI
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter)

        # left panel
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        self.path_label = QLabel("No file loaded")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        left_layout.addWidget(self.path_label)

        # filter row
        filter_box = QWidget()
        fb = QVBoxLayout(filter_box)
        fb.setContentsMargins(0, 0, 0, 0)
        fb.setSpacing(6)

        row1 = QHBoxLayout()
        self.regex_input = QLineEdit()
        self.regex_input.setPlaceholderText("Regex filter (Python re). Example: ERROR|Exception|timeout")
        row1.addWidget(QLabel("Filter:"))
        row1.addWidget(self.regex_input, 1)

        self.use_regex_cb = QCheckBox("Use regex")
        self.use_regex_cb.setChecked(True)
        row1.addWidget(self.use_regex_cb)
        fb.addLayout(row1)

        # level checkboxes
        lv_row = QHBoxLayout()
        lv_row.addWidget(QLabel("Levels:"))
        self.level_cbs = {}
        for lvl in LEVEL_ORDER:
            cb = QCheckBox(lvl)
            cb.setChecked(lvl in ("INFO", "WARN", "ERROR", "FATAL", "CRITICAL"))
            self.level_cbs[lvl] = cb
            lv_row.addWidget(cb)
        lv_row.addStretch(1)
        fb.addLayout(lv_row)

        # buttons
        row2 = QHBoxLayout()
        self.apply_btn = QPushButton("Apply Filter")
        self.apply_btn.clicked.connect(self.apply_filter)
        self.clear_time_btn = QPushButton("Clear Time Bucket")
        self.clear_time_btn.clicked.connect(self.clear_time_bucket)
        row2.addWidget(self.apply_btn)
        row2.addWidget(self.clear_time_btn)
        fb.addLayout(row2)

        left_layout.addWidget(filter_box)

        # timeline
        left_layout.addWidget(QLabel("Timeline (click a bar to filter to that minute):"))
        self.timeline = TimelineWidget()
        self.timeline.bucketClicked.connect(self.on_timeline_bucket_clicked)
        left_layout.addWidget(self.timeline)

        # details pane
        left_layout.addWidget(QLabel("Selected line:"))
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setFont(QFont("Consolas" if sys.platform.startswith("win") else "Monospace", 10))
        left_layout.addWidget(self.details, 1)

        splitter.addWidget(left)

        # right panel: table
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)

        self.table = QTableView()
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.clicked.connect(self.on_table_clicked)

        self.model = LogTableModel(self.mf, self.idx)
        self.table.setModel(self.model)

        right_layout.addWidget(self.table, 1)
        splitter.addWidget(right)

        splitter.setSizes([420, 880])

        # cluster dock
        self.cluster_dock = QDockWidget("Error Clusters", self)
        self.cluster_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea)
        self.cluster_table = QTableWidget(0, 2)
        self.cluster_table.setHorizontalHeaderLabels(["Count", "Cluster Key (normalized)"])
        self.cluster_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.cluster_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.cluster_table.verticalHeader().setVisible(False)
        self.cluster_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.cluster_table.setSelectionMode(QTableWidget.SingleSelection)
        self.cluster_table.cellDoubleClicked.connect(self.on_cluster_double_clicked)
        self.cluster_dock.setWidget(self.cluster_table)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.cluster_dock)

        # status bar with progress
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.prog = QProgressBar()
        self.prog.setRange(0, 100)
        self.prog.setValue(0)
        self.prog.setFixedWidth(220)
        sb.addPermanentWidget(self.prog)
        self.status_text = QLabel("")
        sb.addWidget(self.status_text, 1)

        # actions / menu
        self._build_actions()
        self._build_toolbar()

        self._set_ui_enabled(False)

    def _build_actions(self):
        mfile = self.menuBar().addMenu("&File")

        self.act_open = QAction("&Open…", self)
        self.act_open.triggered.connect(self.open_file)
        mfile.addAction(self.act_open)

        self.act_export_csv = QAction("Export &CSV…", self)
        self.act_export_csv.triggered.connect(lambda: self.export_report("csv"))
        mfile.addAction(self.act_export_csv)

        self.act_export_jsonl = QAction("Export &JSONL…", self)
        self.act_export_jsonl.triggered.connect(lambda: self.export_report("jsonl"))
        mfile.addAction(self.act_export_jsonl)

        self.act_export_html = QAction("Export &HTML Report…", self)
        self.act_export_html.triggered.connect(lambda: self.export_report("html"))
        mfile.addAction(self.act_export_html)

        mfile.addSeparator()
        self.act_quit = QAction("&Quit", self)
        self.act_quit.triggered.connect(self.close)
        mfile.addAction(self.act_quit)

        mhelp = self.menuBar().addMenu("&Help")
        self.act_about = QAction("&About", self)
        self.act_about.triggered.connect(self.show_about)
        mhelp.addAction(self.act_about)

    def _build_toolbar(self):
        tb = QToolBar("Main")
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction(self.act_open)
        tb.addSeparator()
        tb.addAction(self.act_export_csv)
        tb.addAction(self.act_export_jsonl)
        tb.addAction(self.act_export_html)

    def _set_ui_enabled(self, enabled: bool):
        self.apply_btn.setEnabled(enabled)
        self.regex_input.setEnabled(enabled)
        self.use_regex_cb.setEnabled(enabled)
        for cb in self.level_cbs.values():
            cb.setEnabled(enabled)
        self.clear_time_btn.setEnabled(enabled)
        self.act_export_csv.setEnabled(enabled)
        self.act_export_jsonl.setEnabled(enabled)
        self.act_export_html.setEnabled(enabled)

    def _set_status(self, text: str, pct: int | None = None):
        self.status_text.setText(text)
        if pct is not None:
            self.prog.setValue(max(0, min(100, pct)))

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open log file",
            "",
            "Log files (*.log)"
        )

        if not path:
            return

        if not is_valid_log_file(path):
            QMessageBox.critical(
                self,
                "Invalid file",
                "Only plain-text .log files are supported.\n\n"
                "The selected file appears to be binary or unsupported."
            )
            return

        self.load_path(path)

    def load_path(self, path: str):
        if not is_valid_log_file(path):
            QMessageBox.critical(
                self,
                "Invalid file",
                "Refusing to load non-log file."
            )
            return
        # cancel running jobs
        self.cancel_all_workers()

        try:
            self.mf.open(path)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", str(e))
            return

        self.path_label.setText(path)
        self._set_status("Opened file. Starting index…", 0)
        self._set_ui_enabled(False)
        self.details.clear()
        self.cluster_table.setRowCount(0)
        self.timeline.set_bins([])
        self.active_time_bucket = None

        # start index worker
        w = IndexWorker(path)
        t = QThread(self)
        w.moveToThread(t)
        w.progress.connect(self.on_progress)
        w.status.connect(self.on_status)
        w.finished.connect(self.on_index_finished)
        w.failed.connect(self.on_worker_failed)

        t.started.connect(w.run)
        # cleanups
        w.finished.connect(t.quit)
        w.finished.connect(w.deleteLater)
        t.finished.connect(t.deleteLater)
        w.failed.connect(t.quit)
        w.failed.connect(w.deleteLater)

        self.index_thread = (t, w)
        t.start()

    @Slot(int)
    def on_progress(self, value: int):
        self.prog.setValue(value)

    @Slot(str)
    def on_status(self, text: str):
        self.status_text.setText(text)

    @Slot(object)
    def on_index_finished(self, idx: LogIndex):
        self.idx = idx
        self.model.log_index = idx
        self._set_ui_enabled(True)

        # default view is all lines
        all_rows = list(range(idx.total_lines))
        self.model.set_view_rows(all_rows)

        # compute timeline bins (fast: uses minute_keys already computed)
        self.update_timeline_bins(all_rows)
        # compute clusters
        self.start_clustering()

        self._set_status(f"Ready. Lines: {idx.total_lines:,}", 100)

    def cancel_all_workers(self):
        for obj in (self.index_thread, self.filter_thread, self.cluster_thread, self.export_thread):
            if obj:
                t, w = obj
                try:
                    w.cancel()
                except Exception:
                    pass

    def selected_levels(self) -> set:
        return {lvl for lvl, cb in self.level_cbs.items() if cb.isChecked()}

    def apply_filter(self):
        if self.idx.total_lines <= 0:
            return
        self.cancel_filter_cluster_export()

        regex_text = self.regex_input.text()
        use_regex = self.use_regex_cb.isChecked()
        level_mask = self.selected_levels()
        bucket = self.active_time_bucket

        w = FilterWorker(self.mf, self.idx, regex_text, use_regex, level_mask, bucket)
        t = QThread(self)
        w.moveToThread(t)
        w.progress.connect(self.on_progress)
        w.status.connect(self.on_status)
        w.finished.connect(self.on_filter_finished)
        w.failed.connect(self.on_worker_failed)

        t.started.connect(w.run)
        w.finished.connect(t.quit)
        w.finished.connect(w.deleteLater)
        t.finished.connect(t.deleteLater)
        w.failed.connect(t.quit)
        w.failed.connect(w.deleteLater)

        self.filter_thread = (t, w)
        self._set_status("Filtering…", 0)
        t.start()
    
    def cancel_filter_cluster_export(self):
        for obj_name in ("filter_thread", "cluster_thread", "export_thread"):
            obj = getattr(self, obj_name)
            if obj:
                t, w = obj
                try:
                    w.cancel()
                except Exception:
                    pass
    
    @Slot(object)
    def on_filter_finished(self, rows: list[int]):
        self.model.set_view_rows(rows)
        self.update_timeline_bins(rows)
        self.start_clustering()
        suffix = ""
        if self.active_time_bucket is not None:
            suffix = f" | time bucket {self.active_time_bucket}"
        self._set_status(f"Filtered: {len(rows):,} rows{suffix}", 100)

    def clear_time_bucket(self):
        if self.active_time_bucket is None:
            return
        self.active_time_bucket = None
        self.apply_filter()

    def on_timeline_bucket_clicked(self, minute_key: int):
        # Click-to-filter to that minute
        self.active_time_bucket = minute_key
        self.apply_filter()
    
    def update_timeline_bins(self, view_rows: list[int], max_bins: int = 240):
        """
        Uses minute_keys. If there are too many distinct minutes, it compresses into larger bins.
        """
        mk = self.idx.minute_keys
        counts = Counter()
        unknown = 0
        for r in view_rows:
            v = int(mk[r]) if r < len(mk) else 0
            if v == 0:
                unknown += 1
            else:
                counts[v] += 1

        if not counts:
            self.timeline.set_bins([])
            return

        minutes_sorted = sorted(counts.items())  # (minute_key, count)

        # compress if too many bins: group into blocks
        if len(minutes_sorted) > max_bins:
            block = math.ceil(len(minutes_sorted) / max_bins)
            compressed = []
            for i in range(0, len(minutes_sorted), block):
                chunk = minutes_sorted[i:i+block]
                mk0 = chunk[0][0]
                csum = sum(c for _, c in chunk)
                compressed.append((mk0, csum))
            minutes_sorted = compressed

        self.timeline.set_bins(minutes_sorted)

    def start_clustering(self):
        self.cancel_filter_cluster_export()
        rows = self.model.view_rows
        if not rows:
            self.cluster_table.setRowCount(0)
            return

        w = ClusterWorker(self.mf, self.idx, rows, only_errors=True, max_clusters=60)
        t = QThread(self)
        w.moveToThread(t)
        w.progress.connect(self.on_progress)
        w.status.connect(self.on_status)
        w.finished.connect(self.on_cluster_finished)
        w.failed.connect(self.on_worker_failed)

        t.started.connect(w.run)
        w.finished.connect(t.quit)
        w.finished.connect(w.deleteLater)
        t.finished.connect(t.deleteLater)
        w.failed.connect(t.quit)
        w.failed.connect(w.deleteLater)

        self.cluster_thread = (t, w)
        t.start()

    @Slot(object)
    def on_cluster_finished(self, clusters):
        # clusters: list[(count, key, sample)]
        self.cluster_table.setRowCount(0)
        for count, key, sample in clusters:
            row = self.cluster_table.rowCount()
            self.cluster_table.insertRow(row)
            it0 = QTableWidgetItem(str(count))
            it0.setData(Qt.UserRole, (key, sample))
            it1 = QTableWidgetItem(key)
            self.cluster_table.setItem(row, 0, it0)
            self.cluster_table.setItem(row, 1, it1)

    def on_cluster_double_clicked(self, row: int, col: int):
        it = self.cluster_table.item(row, 0)
        if not it:
            return
        key, sample = it.data(Qt.UserRole)

        # show sample + optionally apply a regex-ish filter that searches for key tokens
        dlg = TextPreviewDialog(f"Cluster Sample (count={it.text()})", sample, self)
        dlg.exec()

        # Apply token filter: build a fuzzy contains regex from cluster key
        # This makes drill-down feel “magical” but still explainable.
        tokens = [t for t in re.split(r"\W+", key) if t and t not in ("<num>", "<guid>", "<hex>", "<path>", "<str>", "<ip>", "<email>")]
        if not tokens:
            return
        pattern = ".*".join(map(re.escape, tokens[:8]))
        self.regex_input.setText(pattern)
        self.use_regex_cb.setChecked(True)
        self.apply_filter()

    def on_table_clicked(self, idx: QModelIndex):
        row = idx.row()
        txt = self.model.get_row_text(row)
        self.details.setPlainText(txt)

    def export_report(self, fmt: str):
        if not self.model.view_rows:
            QMessageBox.information(self, "Export", "No rows to export (current view is empty).")
            return

        if fmt == "csv":
            path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "report.csv", "CSV (*.csv)")
        elif fmt == "jsonl":
            path, _ = QFileDialog.getSaveFileName(self, "Export JSONL", "report.jsonl", "JSONL (*.jsonl)")
        else:
            path, _ = QFileDialog.getSaveFileName(self, "Export HTML Report", "report.html", "HTML (*.html)")

        if not path:
            return

        self.cancel_filter_cluster_export()

        # Export potentially huge view: let user cap rows
        cap = self._ask_export_cap()
        if cap == 0:
            return
        max_rows = None if cap < 0 else cap

        w = ExportWorker(fmt, path, self.mf, self.idx, self.model.view_rows, max_rows=max_rows)
        t = QThread(self)
        w.moveToThread(t)
        w.progress.connect(self.on_progress)
        w.status.connect(self.on_status)
        w.finished.connect(self.on_export_finished)
        w.failed.connect(self.on_worker_failed)

        t.started.connect(w.run)
        w.finished.connect(t.quit)
        w.finished.connect(w.deleteLater)
        t.finished.connect(t.deleteLater)
        w.failed.connect(t.quit)
        w.failed.connect(w.deleteLater)

        self.export_thread = (t, w)
        self._set_status("Exporting…", 0)
        t.start()

    def _ask_export_cap(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Export options")
        layout = QVBoxLayout(dlg)

        form = QFormLayout()
        spin = QSpinBox()
        spin.setRange(1, 10_000_000)
        spin.setValue(200_000)
        form.addRow("Max rows (streamed). Use a big number or choose 'All'.", QLabel(""))
        form.addRow("Max rows:", spin)
        layout.addLayout(form)

        all_cb = QCheckBox("Export ALL matched rows (can be very large)")
        all_cb.setChecked(False)
        layout.addWidget(all_cb)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        layout.addWidget(btns)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec() != QDialog.Accepted:
            return 0
        if all_cb.isChecked():
            return -1
        return int(spin.value())