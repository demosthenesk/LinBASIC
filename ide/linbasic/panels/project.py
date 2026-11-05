"""Project Panels 1-3 (resource 3100), stored as Notepad++ workspace files."""
import os
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QMenu, QInputDialog,
                             QFileDialog, QMessageBox, QFileIconProvider)
from PyQt6.QtCore import QFileInfo

from .. import paths

ROLE = Qt.ItemDataRole.UserRole
WS, PROJ, FOLDER, FILE = "ws", "project", "folder", "file"


class ProjectPanel(QWidget):
    def __init__(self, main, name):
        super().__init__()
        self.main = main
        self.index = int(name[-1]) - 1
        self.icons = QFileIconProvider()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context)
        lay.addWidget(self.tree)
        self.path = main.S["projects"][self.index] or paths.cfg("project%d.xml" % (self.index + 1))
        self.load(self.path)

    def root(self):
        return self.tree.topLevelItem(0)

    def _node(self, kind, label, path=None):
        it = QTreeWidgetItem([label])
        it.setData(0, ROLE, (kind, path))
        if kind == FILE:
            it.setIcon(0, self.icons.icon(QFileInfo(path)))
            it.setToolTip(0, path)
        elif kind in (FOLDER, PROJ):
            it.setIcon(0, self.icons.icon(QFileIconProvider.IconType.Folder))
        return it

    def load(self, path):
        self.tree.clear()
        ws = self._node(WS, os.path.splitext(os.path.basename(path))[0] if os.path.exists(path) else "Workspace")
        self.tree.addTopLevelItem(ws)
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            ws.setExpanded(True)
            return

        def fill(parent, el):
            for c in el:
                if c.tag == "Folder":
                    it = self._node(FOLDER, c.get("name", ""))
                    parent.addChild(it)
                    fill(it, c)
                elif c.tag == "File":
                    p = c.get("name", "")
                    if not os.path.isabs(p):
                        p = os.path.normpath(os.path.join(os.path.dirname(path), p))
                    parent.addChild(self._node(FILE, os.path.basename(p), p))
        for pr in root.findall("Project"):
            it = self._node(PROJ, pr.get("name", "Project"))
            ws.addChild(it)
            fill(it, pr)
        self.tree.expandAll()

    def save(self, path=None):
        path = path or self.path
        root = ET.Element("NotepadPlus")

        def dump(el, it):
            for i in range(it.childCount()):
                c = it.child(i)
                kind, p = c.data(0, ROLE)
                if kind == FOLDER:
                    dump(ET.SubElement(el, "Folder", name=c.text(0)), c)
                elif kind == FILE:
                    ET.SubElement(el, "File", name=p)
        ws = self.root()
        for i in range(ws.childCount()):
            pr = ws.child(i)
            dump(ET.SubElement(root, "Project", name=pr.text(0)), pr)
        try:
            ET.indent(root, space="    ")
        except AttributeError:
            pass
        try:
            ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
            self.path = path
            self.main.S["projects"][self.index] = path
        except OSError as ex:
            QMessageBox.warning(self, "Project", str(ex))

    def all_files(self):
        out = []

        def walk(it):
            for i in range(it.childCount()):
                c = it.child(i)
                kind, p = c.data(0, ROLE)
                if kind == FILE:
                    out.append(p)
                walk(c)
        walk(self.root())
        return out

    def open_item(self, it, col=0):
        kind, p = it.data(0, ROLE)
        if kind == FILE and p:
            self.main.open_file(p)

    def context(self, pos):
        it = self.tree.itemAt(pos) or self.root()
        kind, p = it.data(0, ROLE)
        menu = QMenu(self)
        if kind == WS:
            menu.addAction("Rename Workspace").triggered.connect(lambda: self.rename(it))
            menu.addAction("Add New Project").triggered.connect(lambda: self.add_container(it, PROJ, "Project Name"))
            menu.addSeparator()
            menu.addAction("New Workspace").triggered.connect(self.new_ws)
            menu.addAction("Open Workspace...").triggered.connect(self.open_ws)
            menu.addAction("Reload Workspace").triggered.connect(lambda: self.load(self.path))
            menu.addAction("Save").triggered.connect(lambda: self.save())
            menu.addAction("Save As...").triggered.connect(self.save_as)
        elif kind in (PROJ, FOLDER):
            menu.addAction("Rename").triggered.connect(lambda: self.rename(it))
            menu.addAction("Add Folder").triggered.connect(lambda: self.add_container(it, FOLDER, "Folder Name"))
            menu.addAction("Add Files...").triggered.connect(lambda: self.add_files(it))
            menu.addAction("Add Files from Directory...").triggered.connect(lambda: self.add_dir(it))
            menu.addSeparator()
            menu.addAction("Remove").triggered.connect(lambda: self.remove(it))
        else:
            menu.addAction("Open").triggered.connect(lambda: self.open_item(it))
            menu.addAction("Remove").triggered.connect(lambda: self.remove(it))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def rename(self, it):
        t, ok = QInputDialog.getText(self, "Rename", "Name:", text=it.text(0))
        if ok and t.strip():
            it.setText(0, t.strip())
            self.save()

    def add_container(self, it, kind, label):
        t, ok = QInputDialog.getText(self, label, label + ":")
        if ok and t.strip():
            c = self._node(kind, t.strip())
            it.addChild(c)
            it.setExpanded(True)
            self.save()

    def add_files(self, it):
        files, _ = QFileDialog.getOpenFileNames(self, "Add Files", os.path.expanduser("~"))
        for f in files:
            it.addChild(self._node(FILE, os.path.basename(f), f))
        it.setExpanded(True)
        self.save()

    def add_dir(self, it):
        d = QFileDialog.getExistingDirectory(self, "Add Files from Directory", os.path.expanduser("~"))
        if not d:
            return

        def add(parent, path):
            for n in sorted(os.listdir(path), key=str.lower):
                full = os.path.join(path, n)
                if n.startswith("."):
                    continue
                if os.path.isdir(full):
                    f = self._node(FOLDER, n)
                    parent.addChild(f)
                    add(f, full)
                else:
                    parent.addChild(self._node(FILE, n, full))
        top = self._node(FOLDER, os.path.basename(d))
        it.addChild(top)
        add(top, d)
        it.setExpanded(True)
        self.save()

    def remove(self, it):
        par = it.parent()
        if par is not None:
            par.removeChild(it)
            self.save()

    def new_ws(self):
        self.tree.clear()
        self.tree.addTopLevelItem(self._node(WS, "Workspace"))
        self.path = paths.cfg("project%d.xml" % (self.index + 1))

    def open_ws(self):
        f, _ = QFileDialog.getOpenFileName(self, "Open Workspace", os.path.expanduser("~"), "All types (*)")
        if f:
            self.path = f
            self.main.S["projects"][self.index] = f
            self.load(f)

    def save_as(self):
        f, _ = QFileDialog.getSaveFileName(self, "Save Workspace As", self.path)
        if f:
            self.save(f)
