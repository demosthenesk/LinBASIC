"""Shortcut dialog (resources 5000/5001) and Shortcut Mapper (resource 2600)."""
from PyQt6.QtCore import Qt, QKeyCombination
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QCheckBox, QComboBox,
                             QPushButton, QTabWidget, QTableWidget, QTableWidgetItem, QAbstractItemView,
                             QHeaderView, QMessageBox, QKeySequenceEdit)
from PyQt6.Qsci import QsciScintilla as S, QsciCommand

from .. import keys

KEY_CHOICES = ([("None", None)] + [(chr(c), getattr(Qt.Key, "Key_" + chr(c))) for c in range(ord("A"), ord("Z") + 1)]
               + [(str(i), getattr(Qt.Key, "Key_%d" % i)) for i in range(10)]
               + [("F%d" % i, getattr(Qt.Key, "Key_F%d" % i)) for i in range(1, 13)]
               + [(n, getattr(Qt.Key, k)) for n, k in (
                   ("Backspace", "Key_Backspace"), ("Tab", "Key_Tab"), ("Enter", "Key_Return"), ("Esc", "Key_Escape"),
                   ("Spacebar", "Key_Space"), ("Page up", "Key_PageUp"), ("Page down", "Key_PageDown"),
                   ("End", "Key_End"), ("Home", "Key_Home"), ("Left", "Key_Left"), ("Up", "Key_Up"),
                   ("Right", "Key_Right"), ("Down", "Key_Down"), ("INS", "Key_Insert"), ("DEL", "Key_Delete"),
                   (";", "Key_Semicolon"), ("=", "Key_Equal"), (",", "Key_Comma"), ("-", "Key_Minus"),
                   (".", "Key_Period"), ("/", "Key_Slash"), ("~", "Key_QuoteLeft"), ("[", "Key_BracketLeft"),
                   ("\\", "Key_Backslash"), ("]", "Key_BracketRight"), ("'", "Key_Apostrophe"))])


class ShortcutDialog(QDialog):
    """Name + Ctrl/Alt/Shift + key, with conflict detection."""

    def __init__(self, parent, title, name, seq, name_editable=True, main=None, exclude=None):
        super().__init__(parent)
        self.main = main or getattr(parent, "main", parent)
        self.exclude = exclude
        self.setWindowTitle(title)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("&Name :"))
        self.name = QLineEdit(name)
        self.name.setEnabled(name_editable)
        row.addWidget(self.name, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        self.ctrl = QCheckBox("&CTRL")
        self.alt = QCheckBox("&ALT")
        self.shift = QCheckBox("&SHIFT")
        self.key = QComboBox()
        for n, _ in KEY_CHOICES:
            self.key.addItem(n)
        for w in (self.ctrl, QLabel("+"), self.alt, QLabel("+"), self.shift, QLabel("+"), self.key):
            row.addWidget(w)
        lay.addLayout(row)
        self.capture = QKeySequenceEdit()
        self.capture.setMaximumSequenceLength(1)
        self.capture.keySequenceChanged.connect(self._captured)
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("or press keys:"))
        row2.addWidget(self.capture, 1)
        lay.addLayout(row2)
        self.conflict = QLabel()
        self.conflict.setStyleSheet("color:#C00000;")
        lay.addWidget(self.conflict)
        bb = QHBoxLayout()
        bb.addStretch(1)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        bb.addWidget(ok)
        bb.addWidget(cancel)
        lay.addLayout(bb)
        if seq is not None and not seq.isEmpty():
            self.set_seq(seq)
        for w in (self.ctrl, self.alt, self.shift):
            w.toggled.connect(self.check)
        self.key.currentIndexChanged.connect(self.check)

    def set_seq(self, seq):
        kc = seq[0]
        m = kc.keyboardModifiers()
        self.ctrl.setChecked(bool(m & Qt.KeyboardModifier.ControlModifier))
        self.alt.setChecked(bool(m & Qt.KeyboardModifier.AltModifier))
        self.shift.setChecked(bool(m & Qt.KeyboardModifier.ShiftModifier))
        for i, (n, k) in enumerate(KEY_CHOICES):
            if k == kc.key():
                self.key.setCurrentIndex(i)
                break

    def _captured(self, seq):
        if not seq.isEmpty():
            self.set_seq(seq)

    def seq(self):
        k = KEY_CHOICES[self.key.currentIndex()][1]
        if k is None:
            return QKeySequence()
        m = Qt.KeyboardModifier.NoModifier
        if self.ctrl.isChecked():
            m |= Qt.KeyboardModifier.ControlModifier
        if self.alt.isChecked():
            m |= Qt.KeyboardModifier.AltModifier
        if self.shift.isChecked():
            m |= Qt.KeyboardModifier.ShiftModifier
        return QKeySequence(QKeyCombination(m, k))

    def check(self):
        s = self.seq()
        self.conflict.setText("")
        if s.isEmpty() or self.main is None or not hasattr(self.main, "actions"):
            return
        for cid, a in self.main.actions.items():
            if cid == self.exclude:
                continue
            if any(x == s for x in a.shortcuts()):
                self.conflict.setText("CONFLICT FOUND! — %s" % a.text().replace("&", ""))
                return

    def result_value(self):
        return self.name.text().strip(), self.seq()


SCI_CMDS = None


class ShortcutMapper(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Shortcut mapper")
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tables = []
        for name in ("Main menu", "Macros", "Run commands", "Plugin commands", "Scintilla commands"):
            t = QTableWidget(0, 3)
            t.setHorizontalHeaderLabels(["Name", "Shortcut", "Category"])
            t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            t.verticalHeader().setDefaultSectionSize(20)
            t.doubleClicked.connect(lambda *_: self.modify())
            self.tabs.addTab(t, name)
            self.tables.append(t)
        lay.addWidget(self.tabs, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Filter :"))
        self.filter = QLineEdit()
        self.filter.textChanged.connect(self.apply_filter)
        row.addWidget(self.filter, 1)
        lay.addLayout(row)
        self.info = QLabel()
        lay.addWidget(self.info)
        bb = QHBoxLayout()
        for text, fn in (("Modify", self.modify), ("Clear", self.clear), ("Delete", self.delete),
                         ("Reset to default", self.reset)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bb.addWidget(b)
        bb.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bb.addWidget(close)
        lay.addLayout(bb)
        self.fill()

    def _category(self, cid):
        from ..npp_tables import MENUBAR
        if not hasattr(self, "_cat"):
            self._cat = {}

            def walk(top, items):
                for it in items:
                    if it[0] == "cmd":
                        self._cat.setdefault(it[1], top)
                    elif it[0] == "sub":
                        walk(top, it[3])
            for mid, label, items in MENUBAR:
                walk(label.replace("&", ""), items)
        return self._cat.get(cid, "")

    def fill(self):
        m = self.main
        t = self.tables[0]
        t.setRowCount(0)
        rows = sorted(m.actions.items(), key=lambda kv: (self._category(kv[0]), kv[0]))
        for cid, a in rows:
            self._row(t, a.text().replace("&", ""), ", ".join(keys.seq_text(s) for s in a.shortcuts()),
                      self._category(cid), ("cmd", cid))
        t = self.tables[1]
        t.setRowCount(0)
        for i, mm in enumerate(m.shortcut_file.macros):
            self._row(t, mm["name"], keys.seq_text(mm["seq"]), mm.get("folder", ""), ("macro", i))
        t = self.tables[2]
        t.setRowCount(0)
        for i, c in enumerate(m.shortcut_file.commands):
            self._row(t, c["name"], keys.seq_text(c["seq"]), c.get("folder", ""), ("run", i))
        t = self.tables[3]
        t.setRowCount(0)
        from .. import plugins_builtin
        for pname, cmds in plugins_builtin.menu_spec():
            for n, f in cmds:
                if n:
                    self._row(t, n.replace("&", ""), "", pname, ("plugin", n))
        t = self.tables[4]
        t.setRowCount(0)
        ed = m.views[0].editor
        for cmd in ed.standardCommands().commands():
            ks = []
            for k in (cmd.key(), cmd.alternateKey()):
                if k:
                    ks.append(QKeySequence(k).toString())
            self._row(t, cmd.description(), ", ".join(ks), "Scintilla", ("sci", cmd.command()))
        self.apply_filter()

    def _row(self, t, name, sc, cat, data):
        r = t.rowCount()
        t.insertRow(r)
        for c, txt in enumerate((name, sc, cat)):
            it = QTableWidgetItem(txt)
            it.setData(Qt.ItemDataRole.UserRole, data)
            t.setItem(r, c, it)

    def apply_filter(self):
        f = self.filter.text().lower()
        for t in self.tables:
            for r in range(t.rowCount()):
                txt = " ".join(t.item(r, c).text().lower() for c in range(3))
                t.setRowHidden(r, bool(f) and f not in txt)

    def current(self):
        t = self.tables[self.tabs.currentIndex()]
        r = t.currentRow()
        if r < 0:
            return None, None
        return t.item(r, 0).data(Qt.ItemDataRole.UserRole), t.item(r, 0).text()

    def modify(self):
        data, name = self.current()
        if data is None:
            return
        m = self.main
        kind, key = data
        if kind == "cmd":
            a = m.actions[key]
            d = ShortcutDialog(self, "Shortcut", name, a.shortcut(), name_editable=False, main=m, exclude=key)
            if d.exec():
                _, seq = d.result_value()
                m.shortcut_file.internal[key] = [seq] if not seq.isEmpty() else []
                m.apply_shortcuts()
        elif kind in ("macro", "run"):
            lst = m.shortcut_file.macros if kind == "macro" else m.shortcut_file.commands
            item = lst[key]
            d = ShortcutDialog(self, "Shortcut", item["name"], item["seq"], main=m)
            if d.exec():
                item["name"], item["seq"] = d.result_value()
                m.dynamic_shortcuts()
        elif kind == "sci":
            ed = m.views[0].editor
            d = ShortcutDialog(self, "Shortcut", name, QKeySequence(), name_editable=False, main=m)
            if d.exec():
                _, seq = d.result_value()
                for v in m.views:
                    for cmd in v.editor.standardCommands().commands():
                        if cmd.command() == key:
                            cmd.setKey(seq[0].toCombined() if not seq.isEmpty() else 0)
                m.shortcut_file.scintilla[key] = [seq]
        else:
            QMessageBox.information(self, "Shortcut mapper", "Built-in plugin commands are reachable from the Plugins menu.")
            return
        m.shortcut_file.save()
        self.fill()

    def clear(self):
        data, name = self.current()
        if data is None:
            return
        kind, key = data
        m = self.main
        if kind == "cmd":
            m.shortcut_file.internal[key] = []
            m.apply_shortcuts()
        elif kind in ("macro", "run"):
            lst = m.shortcut_file.macros if kind == "macro" else m.shortcut_file.commands
            lst[key]["seq"] = QKeySequence()
            m.dynamic_shortcuts()
        m.shortcut_file.save()
        self.fill()

    def delete(self):
        data, name = self.current()
        if data is None:
            return
        kind, key = data
        m = self.main
        if kind in ("macro", "run"):
            lst = m.shortcut_file.macros if kind == "macro" else m.shortcut_file.commands
            if QMessageBox.question(self, "Delete", 'Delete "%s"?' % name) == QMessageBox.StandardButton.Yes:
                lst.pop(key)
                m.dynamic_shortcuts()
                m.shortcut_file.save()
                self.fill()

    def reset(self):
        data, name = self.current()
        if data and data[0] == "cmd":
            self.main.shortcut_file.internal.pop(data[1], None)
            self.main.apply_shortcuts()
            self.main.shortcut_file.save()
            self.fill()
