"""Folder as Workspace panel (resource 3500)."""
import os
import shutil

from PyQt6.QtCore import Qt, QFileSystemWatcher, QFileInfo
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem, QMenu, QToolButton,
                             QApplication, QFileIconProvider)

ROLE = Qt.ItemDataRole.UserRole


class WorkspacePanel(QWidget):
    def __init__(self, main, name):
        super().__init__()
        self.main = main
        self.icons = QFileIconProvider()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        for text, tip, fn in (("⊟", "Collapse all", lambda: self.tree.collapseAll()),
                              ("◎", "Locate current file", self.locate),
                              ("+", "Add folder...", self.main.cmd_open_folder_workspace)):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemExpanded.connect(self.expand)
        self.tree.itemActivated.connect(self.open_item)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context)
        lay.addWidget(self.tree)
        self.watch = QFileSystemWatcher(self)
        self.watch.directoryChanged.connect(self.dir_changed)
        for r in list(main.S["workspace_roots"]):
            if os.path.isdir(r):
                self.add_root(r, save=False)

    def roots(self):
        return [self.tree.topLevelItem(i).data(0, ROLE) for i in range(self.tree.topLevelItemCount())]

    def add_root(self, path, save=True):
        path = os.path.abspath(path)
        if path in self.roots():
            return
        it = self._item(path, os.path.basename(path) or path, True)
        self.tree.addTopLevelItem(it)
        it.setExpanded(True)
        if save:
            self.main.S["workspace_roots"] = self.roots()

    def _item(self, path, label, is_dir):
        it = QTreeWidgetItem([label])
        it.setData(0, ROLE, path)
        it.setIcon(0, self.icons.icon(QFileInfo(path)))
        it.setToolTip(0, path)
        if is_dir:
            it.setChildIndicatorPolicy(QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator)
            it.addChild(QTreeWidgetItem(["…"]))
        return it

    def expand(self, it):
        path = it.data(0, ROLE)
        if not os.path.isdir(path):
            return
        it.takeChildren()
        try:
            names = os.listdir(path)
        except OSError:
            return
        dirs = sorted([n for n in names if os.path.isdir(os.path.join(path, n))], key=str.lower)
        files = sorted([n for n in names if not os.path.isdir(os.path.join(path, n))], key=str.lower)
        for n in dirs:
            it.addChild(self._item(os.path.join(path, n), n, True))
        for n in files:
            it.addChild(self._item(os.path.join(path, n), n, False))
        if path not in self.watch.directories():
            self.watch.addPath(path)

    def dir_changed(self, path):
        def walk(it):
            if it.data(0, ROLE) == path and it.isExpanded():
                self.expand(it)
                return
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def open_item(self, it, col=0):
        p = it.data(0, ROLE)
        if p and os.path.isfile(p):
            self.main.open_file(p)

    def locate(self):
        b = self.main.buf()
        if b is None or not b.path:
            return
        target = b.path
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            rp = root.data(0, ROLE)
            if target.startswith(rp + os.sep):
                rel = os.path.relpath(target, rp).split(os.sep)
                it = root
                for part in rel:
                    it.setExpanded(True)
                    nxt = None
                    for j in range(it.childCount()):
                        if it.child(j).text(0) == part:
                            nxt = it.child(j)
                            break
                    if nxt is None:
                        return
                    it = nxt
                self.tree.setCurrentItem(it)
                return

    def context(self, pos):
        it = self.tree.itemAt(pos)
        menu = QMenu(self)
        if it is None:
            menu.addAction("Add folder...").triggered.connect(self.main.cmd_open_folder_workspace)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        p = it.data(0, ROLE)
        is_root = it.parent() is None
        if os.path.isfile(p):
            menu.addAction("Open").triggered.connect(lambda: self.main.open_file(p))
            menu.addAction("Run by system").triggered.connect(lambda: self.main._spawn(["xdg-open", p]))
        if is_root:
            menu.addAction("Remove").triggered.connect(lambda: self._remove(it))
            menu.addAction("Remove all").triggered.connect(self._remove_all)
        menu.addSeparator()
        menu.addAction("Copy path").triggered.connect(lambda: QApplication.clipboard().setText(p))
        menu.addAction("Copy file name").triggered.connect(lambda: QApplication.clipboard().setText(os.path.basename(p)))
        d = p if os.path.isdir(p) else os.path.dirname(p)
        menu.addSeparator()
        menu.addAction("Find in Files...").triggered.connect(lambda: self._fif(d))
        menu.addAction("File manager here").triggered.connect(lambda: self.main._spawn(["xdg-open", d]))
        menu.addAction("Terminal here").triggered.connect(lambda: self._term(d))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _term(self, d):
        for t in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
            if shutil.which(t):
                self.main._spawn([t], cwd=d)
                return

    def _fif(self, d):
        self.main.show_find(2)
        self.main.find_dlg.dir_combo.setCurrentText(d)

    def _remove(self, it):
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(it))
        self.main.S["workspace_roots"] = self.roots()

    def _remove_all(self):
        self.tree.clear()
        self.main.S["workspace_roots"] = []

    def save(self):
        self.main.S["workspace_roots"] = self.roots()
