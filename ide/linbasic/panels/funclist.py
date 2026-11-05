"""Function List panel (resource 3400)."""
import bisect
import re

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QLineEdit,
                             QToolButton, QMenu, QApplication)

from .. import funcparser


class FunctionListPanel(QWidget):
    def __init__(self, main, name):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.textChanged.connect(self.apply_filter)
        self.sort_btn = QToolButton()
        self.sort_btn.setText("A↓")
        self.sort_btn.setCheckable(True)
        self.sort_btn.setToolTip("Sort")
        self.sort_btn.toggled.connect(lambda: self.populate(self.items))
        reload_btn = QToolButton()
        reload_btn.setText("⟳")
        reload_btn.setToolTip("Reload")
        reload_btn.clicked.connect(self.reparse)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.sort_btn)
        bar.addWidget(reload_btn)
        lay.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self.jump)
        self.tree.itemActivated.connect(self.jump)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context)
        lay.addWidget(self.tree)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(800)
        self.timer.timeout.connect(self.reparse)
        self.items = []
        self.reparse()

    def on_event(self, kind, ed):
        if kind in ("current", "lang", "shown"):
            self.reparse()
        elif kind == "text" and self.isVisible():
            self.timer.start()

    def reparse(self):
        if not self.isVisible() and self.items:
            return
        b = self.main.buf()
        self.tree.clear()
        self.items = []
        if b is None:
            return
        ed = self.main.editor()
        text = ed.get_bytes().decode("utf-8", "replace")
        res = funcparser.parse(text, b.lang)
        if res is None:
            it = QTreeWidgetItem([b.name()])
            self.tree.addTopLevelItem(it)
            return
        starts = [0] + [m.end() for m in re.finditer(r"\r\n|\r|\n", text)]
        self.items = [(c, f, bisect.bisect_right(starts, off) - 1) for c, f, off in res]
        self.populate(self.items)

    def populate(self, items):
        self.tree.clear()
        b = self.main.buf()
        root = QTreeWidgetItem([b.name() if b else ""])
        self.tree.addTopLevelItem(root)
        classes = {}
        seq = sorted(items, key=lambda x: ((x[0] or "").lower(), (x[1] or "").lower())) if self.sort_btn.isChecked() else items
        for c, f, line in seq:
            parent = root
            if c:
                if c not in classes:
                    ci = QTreeWidgetItem([c])
                    ci.setData(0, Qt.ItemDataRole.UserRole, line)
                    f0 = ci.font(0)
                    f0.setBold(True)
                    ci.setFont(0, f0)
                    root.addChild(ci)
                    classes[c] = ci
                parent = classes[c]
            if f:
                fi = QTreeWidgetItem([f])
                fi.setData(0, Qt.ItemDataRole.UserRole, line)
                parent.addChild(fi)
        self.tree.expandAll()
        self.apply_filter()

    def apply_filter(self):
        t = self.search.text().lower()

        def walk(it):
            any_vis = False
            for i in range(it.childCount()):
                c = it.child(i)
                vis = walk(c) or (not t or t in c.text(0).lower())
                c.setHidden(not vis)
                any_vis = any_vis or vis
            return any_vis
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def jump(self, item, col=0):
        line = item.data(0, Qt.ItemDataRole.UserRole)
        if line is None:
            return
        ed = self.main.editor()
        ed.goto_line(line)
        ed.setFocus()

    def context(self, pos):
        menu = QMenu(self)
        menu.addAction("Copy").triggered.connect(
            lambda: QApplication.clipboard().setText(self.tree.currentItem().text(0) if self.tree.currentItem() else ""))
        menu.addAction("Expand all").triggered.connect(self.tree.expandAll)
        menu.addAction("Collapse all").triggered.connect(self.tree.collapseAll)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def showEvent(self, e):
        super().showEvent(e)
        self.reparse()
