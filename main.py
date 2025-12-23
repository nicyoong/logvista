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