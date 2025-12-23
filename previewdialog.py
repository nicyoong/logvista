import sys

from PySide6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QThread,
    Signal,
    Slot,
    QSize,
    QTimer,
)
from PySide6.QtGui import QAction, QFont, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QCheckBox,
    QSplitter,
    QTableView,
    QProgressBar,
    QMessageBox,
    QStatusBar,
    QComboBox,
    QDockWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
    QToolBar,
)


class TextPreviewDialog(QDialog):
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText(text)
        box.setFont(
            QFont("Consolas" if sys.platform.startswith("win") else "Monospace", 10)
        )
        layout.addWidget(box)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        btns.clicked.connect(self.accept)
        layout.addWidget(btns)
