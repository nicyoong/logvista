import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QVBoxLayout,
    QTextEdit,
    QDialog,
    QDialogButtonBox,
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
