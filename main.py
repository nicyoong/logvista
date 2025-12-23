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