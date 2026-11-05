"""Smaller dialogs recovered from the RT_DIALOG resources: Go To (2000),
Column Editor (2020), Find Characters in Range (2900), Windows (7000),
MD5/SHA digests (1920/1930), Run a Macro Multiple Times (8000), About (1700),
Debug Info (1750), Command Line Arguments (1755)."""
import hashlib
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap, QIcon, QFont
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QRadioButton,
                             QPushButton, QSpinBox, QGroupBox, QCheckBox, QPlainTextEdit, QDialogButtonBox,
                             QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QComboBox,
                             QApplication, QFileDialog, QButtonGroup, QTextBrowser)
from PyQt6.Qsci import QsciScintilla as S

from .. import APP_NAME, VERSION, UPSTREAM, paths


class GotoDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Go To...")
        ed = main.editor()
        self.ed = ed
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.r_line = QRadioButton("&Line")
        self.r_off = QRadioButton("&Offset")
        self.r_line.setChecked(True)
        row.addWidget(self.r_line)
        row.addWidget(self.r_off)
        row.addStretch(1)
        lay.addLayout(row)
        g = QGridLayout()
        self.cur = QLabel()
        self.target = QLineEdit()
        self.maxl = QLabel()
        g.addWidget(QLabel("You are here :"), 0, 0)
        g.addWidget(self.cur, 0, 1)
        g.addWidget(QLabel("You want to &go to :"), 1, 0)
        g.addWidget(self.target, 1, 1)
        g.addWidget(QLabel("You can't go further than :"), 2, 0)
        g.addWidget(self.maxl, 2, 1)
        lay.addLayout(g)
        bb = QHBoxLayout()
        go = QPushButton("Go")
        go.setDefault(True)
        nowhere = QPushButton("I'm going nowhere")
        go.clicked.connect(self.go)
        nowhere.clicked.connect(self.reject)
        bb.addStretch(1)
        bb.addWidget(go)
        bb.addWidget(nowhere)
        lay.addLayout(bb)
        self.r_line.toggled.connect(self.refresh)
        self.refresh()
        self.target.setFocus()

    def refresh(self):
        ed = self.ed
        if self.r_line.isChecked():
            self.cur.setText(str(ed.line_from_pos(ed.pos()) + 1))
            self.maxl.setText(str(ed.line_count()))
        else:
            self.cur.setText(str(ed.pos()))
            self.maxl.setText(str(ed.length()))

    def go(self):
        t = self.target.text().strip()
        if not t.lstrip("-").isdigit():
            return
        v = int(t)
        if self.r_line.isChecked():
            if v < 0:
                v = self.ed.line_count() + v + 1
            self.ed.goto_line(max(1, v) - 1)
        else:
            self.ed.goto_pos(max(0, min(v, self.ed.length())))
        self.accept()


class ColumnEditor(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        cfg = main.S["column_editor"] or {}
        self.setWindowTitle("Column / Multi-Selection Editor")
        lay = QVBoxLayout(self)
        self.r_text = QRadioButton("&Text to Insert")
        self.text = QLineEdit(cfg.get("text", ""))
        self.r_num = QRadioButton("&Number to Insert")
        lay.addWidget(self.r_text)
        lay.addWidget(self.text)
        lay.addWidget(self.r_num)
        g = QGridLayout()
        self.init = QSpinBox()
        self.init.setRange(-2**31, 2**31 - 1)
        self.init.setValue(cfg.get("init", 1))
        self.inc = QSpinBox()
        self.inc.setRange(-2**31, 2**31 - 1)
        self.inc.setValue(cfg.get("inc", 1))
        self.rep = QSpinBox()
        self.rep.setRange(1, 1_000_000)
        self.rep.setValue(cfg.get("rep", 1))
        self.lead = QComboBox()
        self.lead.addItems(["None", "Zeros", "Spaces"])
        self.lead.setCurrentIndex(cfg.get("lead", 0))
        for r, (lbl, w) in enumerate((("&Initial number :", self.init), ("Increase b&y :", self.inc),
                                       ("&Repeat :", self.rep), ("&Leading :", self.lead))):
            g.addWidget(QLabel(lbl), r, 0)
            g.addWidget(w, r, 1)
        lay.addLayout(g)
        fmt = QGroupBox("Format")
        fl = QHBoxLayout(fmt)
        self.fmts = {}
        for k, t in (("dec", "&Dec"), ("hex", "&Hex"), ("oct", "&Oct"), ("bin", "&Bin")):
            rb = QRadioButton(t)
            fl.addWidget(rb)
            self.fmts[k] = rb
        self.fmts[cfg.get("fmt", "dec")].setChecked(True)
        lay.addWidget(fmt)
        (self.r_num if cfg.get("mode") == "num" else self.r_text).setChecked(True)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.apply)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self):
        fmt = next(k for k, rb in self.fmts.items() if rb.isChecked())
        self.main.S["column_editor"] = {"text": self.text.text(), "init": self.init.value(), "inc": self.inc.value(),
                                        "rep": self.rep.value(), "lead": self.lead.currentIndex(), "fmt": fmt,
                                        "mode": "num" if self.r_num.isChecked() else "text"}
        ed = self.main.editor()
        snd = ed.SendScintilla
        n = snd(S.SCI_GETSELECTIONS)
        if n > 1 or snd(S.SCI_SELECTIONISRECTANGLE):
            spots = []
            for i in range(n):
                spots.append((snd(S.SCI_GETSELECTIONNSTART, i), snd(S.SCI_GETSELECTIONNEND, i)))
            spots.sort()
        else:
            p = ed.pos()
            col = snd(S.SCI_GETCOLUMN, p)
            line0 = ed.line_from_pos(p)
            spots = []
            for ln in range(line0, ed.line_count()):
                q = snd(S.SCI_FINDCOLUMN, ln, col)
                if snd(S.SCI_GETCOLUMN, q) < col:
                    pad = col - snd(S.SCI_GETCOLUMN, q)
                    spots.append((q, q, " " * pad))
                else:
                    spots.append((q, q, ""))
        values = []
        if self.r_num.isChecked():
            v = self.init.value()
            rep = self.rep.value()
            nums = []
            for i in range(len(spots)):
                nums.append(v + (i // rep) * self.inc.value())
            conv = {"dec": lambda x: str(x), "hex": lambda x: "%X" % x if x >= 0 else "-%X" % -x,
                    "oct": lambda x: "%o" % x, "bin": lambda x: bin(x).replace("0b", "")}[fmt]
            strs = [conv(x) for x in nums]
            width = max(len(s) for s in strs) if strs else 0
            lead = self.lead.currentIndex()
            for s in strs:
                if lead == 1:
                    s = s.rjust(width, "0")
                elif lead == 2:
                    s = s.rjust(width)
                values.append(s)
        else:
            values = [self.text.text()] * len(spots)
        snd(S.SCI_BEGINUNDOACTION)
        for sp, val in sorted(zip(spots, values), key=lambda x: x[0][0], reverse=True):
            a, b = sp[0], sp[1]
            pad = sp[2] if len(sp) > 2 else ""
            ed.replace_range(a, b, pad + val)
        snd(S.SCI_ENDUNDOACTION)
        self.accept()


class CharRangeDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Find Characters in Range...")
        lay = QVBoxLayout(self)
        self.r_non = QRadioButton("&Non-ASCII characters (128–255)")
        self.r_asc = QRadioButton("&ASCII characters (0–127)")
        self.r_cus = QRadioButton("Custom &range (0–255):")
        self.r_non.setChecked(True)
        lay.addWidget(self.r_non)
        lay.addWidget(self.r_asc)
        row = QHBoxLayout()
        row.addWidget(self.r_cus)
        self.lo = QSpinBox()
        self.lo.setRange(0, 0x10FFFF)
        self.hi = QSpinBox()
        self.hi.setRange(0, 0x10FFFF)
        self.hi.setValue(255)
        row.addWidget(self.lo)
        row.addWidget(QLabel("–"))
        row.addWidget(self.hi)
        lay.addLayout(row)
        dirb = QGroupBox("Direction")
        dl = QHBoxLayout(dirb)
        self.up = QRadioButton("&Up")
        self.down = QRadioButton("&Down")
        self.down.setChecked(True)
        dl.addWidget(self.up)
        dl.addWidget(self.down)
        lay.addWidget(dirb)
        self.wrap = QCheckBox("Wra&p around")
        self.wrap.setChecked(True)
        lay.addWidget(self.wrap)
        bb = QHBoxLayout()
        f = QPushButton("&Find")
        f.setDefault(True)
        f.clicked.connect(self.find)
        c = QPushButton("&Close")
        c.clicked.connect(self.hide)
        bb.addStretch(1)
        bb.addWidget(f)
        bb.addWidget(c)
        lay.addLayout(bb)
        self.status = QLabel()
        lay.addWidget(self.status)

    def find(self):
        if self.r_non.isChecked():
            lo, hi = 128, 0x10FFFF
        elif self.r_asc.isChecked():
            lo, hi = 0, 127
        else:
            lo, hi = self.lo.value(), self.hi.value()
        from .. import search as srch
        import regex
        rx = regex.compile("[%s-%s]" % (regex.escape(chr(lo)), regex.escape(chr(hi))))
        ed = self.main.editor()
        dt = srch.DocText(ed.get_bytes())
        a, b = ed.sel_range()
        if self.down.isChecked():
            m = rx.search(dt.text, dt.b2c(b))
            if m is None and self.wrap.isChecked():
                m = rx.search(dt.text, 0)
        else:
            last = None
            for mm in rx.finditer(dt.text, 0, dt.b2c(a)):
                last = mm
            m = last
            if m is None and self.wrap.isChecked():
                for mm in rx.finditer(dt.text):
                    m = mm
        if m is None:
            self.status.setText("Can't find any character in range.")
            return
        self.status.setText("")
        s, e = dt.c2b(m.start()), dt.c2b(m.end())
        ed.goto_pos(e, s)


class WindowsDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Windows")
        self.resize(640, 380)
        lay = QHBoxLayout(self)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Path", "Type", "Size"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.doubleClicked.connect(lambda *_: self.activate())
        lay.addWidget(self.table, 1)
        col = QVBoxLayout()
        for text, fn in (("&Activate", self.activate), ("&Save", self.save), ("&Close window(s)", self.close_sel),
                         ("Sort &tabs", self.sort_tabs), ("&OK", self.accept)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        lay.addLayout(col)
        self.fill()

    def fill(self):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self.rows = []
        for v in self.main.views:
            for b in v.buffers:
                r = self.table.rowCount()
                self.table.insertRow(r)
                with self.main.doc_editor(b) as e:
                    size = e.length()
                items = [b.name() + ("*" if b.dirty else ""), os.path.dirname(b.path) if b.path else "",
                         os.path.splitext(b.name())[1].lstrip(".") or "", str(size)]
                for c, t in enumerate(items):
                    it = QTableWidgetItem(t)
                    it.setData(Qt.ItemDataRole.UserRole, (v.index, id(b)))
                    if c == 3:
                        it.setData(Qt.ItemDataRole.DisplayRole, size)
                    self.table.setItem(r, c, it)
                self.rows.append((v, b))
        self.table.setSortingEnabled(True)

    def selected(self):
        out = []
        for idx in self.table.selectionModel().selectedRows():
            vi, bid = self.table.item(idx.row(), 0).data(Qt.ItemDataRole.UserRole)
            for v, b in self.rows:
                if v.index == vi and id(b) == bid:
                    out.append((v, b))
        return out

    def activate(self):
        s = self.selected()
        if s:
            v, b = s[0]
            v.activate(b)
            self.main.set_active_view(v)
            self.accept()

    def save(self):
        for v, b in self.selected():
            self.main.save_buffer(b)
        self.fill()

    def close_sel(self):
        for v, b in self.selected():
            self.main.close_buffer(b, v)
        self.fill()

    def sort_tabs(self):
        order = []
        for r in range(self.table.rowCount()):
            vi, bid = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            order.append((vi, bid))
        for vi in (0, 1):
            v = self.main.views[vi]
            ids = [bid for x, bid in order if x == vi]
            for target, bid in enumerate(ids):
                for i, b in enumerate(v.buffers):
                    if id(b) == bid:
                        v.move_tab(i, target)
                        break


class TextDialog(QDialog):
    def __init__(self, main, title, text, copy_button=None):
        super().__init__(main)
        self.setWindowTitle(title)
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        ed = QPlainTextEdit(text)
        ed.setReadOnly(True)
        ed.setFont(QFont("Monospace"))
        lay.addWidget(ed)
        row = QHBoxLayout()
        if copy_button:
            b = QPushButton(copy_button)
            b.clicked.connect(lambda: QApplication.clipboard().setText(text))
            row.addWidget(b)
        row.addStretch(1)
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)


class AboutDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.setWindowTitle("About %s" % APP_NAME)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QIcon(paths.icon("linbasic.svg")).pixmap(72, 72))
        top.addWidget(logo)
        t = QLabel("<h2>%s v%s</h2>(64-bit)<br>A Linux re-creation of %s,<br>rebuilt with REA (Reverse Engineering Anything)." % (APP_NAME, VERSION, UPSTREAM))
        t.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(t, 1)
        lay.addLayout(top)
        tb = QTextBrowser()
        tb.setOpenExternalLinks(True)
        tb.setHtml(
            "<p><b>Home:</b> https://notepad-plus-plus.org/ (upstream)</p>"
            "<p>Notepad++ is © Don HO and its contributors. Its language definitions, style themes, "
            "auto-completion and function-list parsers and its localization files are used unmodified "
            "under the GNU General Public License.</p>"
            "<p>Editing component: Scintilla (via QScintilla) — Neil Hodgson et al.; UI toolkit: Qt / PyQt6.</p>"
            "<p><b>GNU General Public Licence</b><br>This program is free software; you can redistribute it and/or modify "
            "it under the terms of the GNU General Public License as published by the Free Software Foundation; "
            "either version 3 of the License, or at your option any later version.</p>"
            "<p>This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even "
            "the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.</p>")
        lay.addWidget(tb)
        ok = QPushButton("OK")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok, 0, Qt.AlignmentFlag.AlignRight)
        self.resize(520, 420)


ALGO_NAME = {"md5": "MD5", "sha1": "SHA-1", "sha256": "SHA-256", "sha512": "SHA-512"}


class HashDialog(QDialog):
    def __init__(self, main, algo):
        super().__init__(main)
        self.main = main
        self.algo = algo
        self.setWindowTitle("Generate %s digest" % ALGO_NAME[algo])
        self.resize(560, 360)
        lay = QVBoxLayout(self)
        self.src = QPlainTextEdit()
        self.src.setPlaceholderText("Text to hash")
        self.lines = QCheckBox("Treat each line as a &separate string")
        self.lines.setChecked(main.S["hash_treat_lines"])
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QFont("Monospace"))
        lay.addWidget(self.src, 1)
        lay.addWidget(self.lines)
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        cp = QPushButton("Co&py to Clipboard")
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.out.toPlainText()))
        cl = QPushButton("&Close")
        cl.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cp)
        row.addWidget(cl)
        lay.addLayout(row)
        self.src.textChanged.connect(self.update)
        self.lines.toggled.connect(self.update)

    def update(self):
        t = self.src.toPlainText()
        self.main.S["hash_treat_lines"] = self.lines.isChecked()
        if self.lines.isChecked():
            self.out.setPlainText("\n".join(hashlib.new(self.algo, l.encode()).hexdigest() for l in t.split("\n")))
        else:
            self.out.setPlainText(hashlib.new(self.algo, t.encode()).hexdigest() if t else "")


class HashFilesDialog(QDialog):
    def __init__(self, main, algo):
        super().__init__(main)
        self.algo = algo
        self.setWindowTitle("Generate %s digest from files" % ALGO_NAME[algo])
        self.resize(640, 320)
        lay = QVBoxLayout(self)
        ch = QPushButton("Choose files to &generate %s..." % ALGO_NAME[algo])
        ch.clicked.connect(self.choose)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setFont(QFont("Monospace"))
        lay.addWidget(ch)
        lay.addWidget(self.out, 1)
        row = QHBoxLayout()
        cp = QPushButton("Co&py to Clipboard")
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.out.toPlainText()))
        cl = QPushButton("&Close")
        cl.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(cp)
        row.addWidget(cl)
        lay.addLayout(row)

    def choose(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files", os.path.expanduser("~"))
        lines = []
        for f in files:
            h = hashlib.new(self.algo)
            try:
                with open(f, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                lines.append("%s  %s" % (h.hexdigest(), f))
            except OSError as ex:
                lines.append("ERROR  %s (%s)" % (f, ex))
        self.out.setPlainText("\n".join(lines))


class MacroMultiDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Run a Macro Multiple Times")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("&Macro to run"))
        self.combo = QComboBox()
        self.macros = []
        if main.last_macro:
            self.combo.addItem("Current recorded macro")
            self.macros.append(main.last_macro)
        for m in main.shortcut_file.macros:
            self.combo.addItem(m["name"])
            self.macros.append(m["actions"])
        lay.addWidget(self.combo)
        row = QHBoxLayout()
        self.r_times = QRadioButton("R&un")
        self.r_times.setChecked(True)
        self.n = QSpinBox()
        self.n.setRange(1, 100000)
        row.addWidget(self.r_times)
        row.addWidget(self.n)
        row.addWidget(QLabel("times"))
        row.addStretch(1)
        lay.addLayout(row)
        self.r_eof = QRadioButton("Run until the &end of file")
        lay.addWidget(self.r_eof)
        bb = QHBoxLayout()
        run = QPushButton("&Run")
        run.setDefault(True)
        run.clicked.connect(self.run)
        cancel = QPushButton("&Cancel")
        cancel.clicked.connect(self.reject)
        bb.addStretch(1)
        bb.addWidget(run)
        bb.addWidget(cancel)
        lay.addLayout(bb)

    def run(self):
        if not self.macros:
            return
        acts = self.macros[self.combo.currentIndex()]
        if self.r_eof.isChecked():
            self.main.play_macro(acts, until_eof=True)
        else:
            self.main.play_macro(acts, times=self.n.value())
        self.accept()
