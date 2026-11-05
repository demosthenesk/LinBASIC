"""Document List panel (resource 3000)."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QMenu, QAbstractItemView

from .. import paths


class DocListPanel(QWidget):
    def __init__(self, main, name):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "Ext.", "Path"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setSortingEnabled(False)
        self.tree.itemClicked.connect(self.activate)
        self.tree.itemActivated.connect(self.activate)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context)
        self.tree.header().setStretchLastSection(True)
        lay.addWidget(self.tree)
        self.icons = {k: QIcon(paths.icon("misc/%s.png" % k)) for k in ("tab_saved", "tab_unsaved", "tab_readonly", "tab_monitor")}
        self.refresh()

    def on_event(self, kind, ed):
        if kind in ("buffers", "current", "dirty", "shown"):
            self.refresh()

    def refresh(self):
        if not self.isVisible() and self.tree.topLevelItemCount():
            return
        self.tree.clear()
        cur = self.main.buf()
        for v in self.main.views:
            for b in v.buffers:
                name = b.name()
                ext = os.path.splitext(name)[1].lstrip(".")
                it = QTreeWidgetItem([name, ext, b.path or ""])
                ic = "tab_monitor" if b.monitoring else "tab_readonly" if b.readonly() else "tab_unsaved" if b.dirty else "tab_saved"
                it.setIcon(0, self.icons[ic])
                it.setData(0, Qt.ItemDataRole.UserRole, (v.index, b))
                if v.index == 1:
                    it.setToolTip(0, "Second view")
                self.tree.addTopLevelItem(it)
                if b is cur and v is self.main.active_view:
                    self.tree.setCurrentItem(it)
        self.tree.resizeColumnToContents(0)

    def activate(self, item, col=0):
        vi, b = item.data(0, Qt.ItemDataRole.UserRole)
        v = self.main.views[vi]
        if b in v.buffers:
            v.activate(b)
            self.main.set_active_view(v)
            v.editor.setFocus()

    def context(self, pos):
        sel = [it.data(0, Qt.ItemDataRole.UserRole) for it in self.tree.selectedItems()]
        if not sel:
            return
        menu = QMenu(self)
        menu.addAction("Close Selected").triggered.connect(lambda: [self.main.close_buffer(b, self.main.views[vi]) for vi, b in sel])
        menu.addAction("Save Selected").triggered.connect(lambda: [self.main.save_buffer(b) for vi, b in sel])
        menu.exec(self.tree.viewport().mapToGlobal(pos))
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
