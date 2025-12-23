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
        