"""Clipboard History panel (resource 2800)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QMenu, QApplication


class ClipHistoryPanel(QWidget):
    def __init__(self, main, name):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self.paste)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.context)
        lay.addWidget(self.list)
        self.refresh()

    def on_event(self, kind, ed):
        if kind in ("clipboard", "shown"):
            self.refresh()

    def refresh(self):
        self.list.clear()
        for t in self.main.clip_history:
            label = t.replace("\r", "").replace("\n", " ↵ ")
            if len(label) > 64:
                label = label[:64] + "…"
            it = QListWidgetItem(label)
            it.setData(Qt.ItemDataRole.UserRole, t)
            it.setToolTip(t[:2000])
            self.list.addItem(it)

    def paste(self, it):
        ed = self.main.editor()
        ed.replaceSelectedText(it.data(Qt.ItemDataRole.UserRole))
        ed.setFocus()

    def context(self, pos):
        it = self.list.itemAt(pos)
        menu = QMenu(self)
        if it is not None:
            menu.addAction("Paste").triggered.connect(lambda: self.paste(it))
            menu.addAction("Remove").triggered.connect(lambda: (self.main.clip_history.remove(it.data(Qt.ItemDataRole.UserRole)), self.refresh()))
        menu.addAction("Clear all").triggered.connect(lambda: (self.main.clip_history.clear(), self.refresh()))
        menu.exec(self.list.viewport().mapToGlobal(pos))
