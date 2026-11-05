"""Find / Replace / Find in Files / Find in Projects / Mark — one tabbed dialog,
like Notepad++'s IDD_FIND_REPLACE_DLG (resource 1600)."""
import os

from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeySequence, QShortcut, QFont
from PyQt6.QtWidgets import (QDialog, QTabBar, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
                             QCheckBox, QPushButton, QGroupBox, QRadioButton, QSlider, QToolButton,
                             QFileDialog, QWidget, QSizePolicy)

from .. import search as srch

TABS = ["Find", "Replace", "Find in Files", "Find in Projects", "Mark"]
TAB_KEYS = ["titleFind", "titleReplace", "titleFindInFiles", "titleFindInProjects", "titleMark"]


def _combo(history):
    c = QComboBox()
    c.setEditable(True)
    c.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    c.setMaxCount(30)
    c.addItems(history)
    c.setCurrentText("")
    c.setMinimumWidth(320)
    c.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return c


class FindDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        S_ = main.S
        tr = main.i18n.find
        self.setWindowTitle("Find")
        self.setModal(False)
        root = QVBoxLayout(self)
        self.tabbar = QTabBar()
        for i, t in enumerate(TABS):
            self.tabbar.addTab(tr.get(TAB_KEYS[i], t))
        self.tabbar.currentChanged.connect(self._tab_changed)
        root.addWidget(self.tabbar)

        body = QHBoxLayout()
        root.addLayout(body)
        left = QVBoxLayout()
        body.addLayout(left, 1)
        grid = QGridLayout()
        left.addLayout(grid)
        self.find_combo = _combo(S_["find_history"])
        self.repl_combo = _combo(S_["replace_history"])
        self.filter_combo = _combo(S_["filter_history"] or ["*.*"])
        self.dir_combo = _combo(S_["dir_history"])
        if S_["find_mono"]:
            f = QFont("Monospace")
            self.find_combo.setFont(f)
            self.repl_combo.setFont(f)
        self.lbl_find = QLabel("Fi&nd what :")
        self.lbl_find.setBuddy(self.find_combo)
        self.lbl_repl = QLabel("Rep&lace with :")
        self.lbl_repl.setBuddy(self.repl_combo)
        self.lbl_filter = QLabel("Filter&s :")
        self.lbl_filter.setBuddy(self.filter_combo)
        self.lbl_dir = QLabel("Dir&ectory :")
        self.lbl_dir.setBuddy(self.dir_combo)
        self.swap_btn = QToolButton()
        self.swap_btn.setText("⇅")
        self.swap_btn.setToolTip("Swap Find with Replace")
        self.swap_btn.clicked.connect(self.swap)
        self.browse_btn = QToolButton()
        self.browse_btn.setText("...")
        self.browse_btn.clicked.connect(self.browse_dir)
        grid.addWidget(self.lbl_find, 0, 0)
        grid.addWidget(self.find_combo, 0, 1)
        grid.addWidget(self.swap_btn, 0, 2, 2, 1)
        grid.addWidget(self.lbl_repl, 1, 0)
        grid.addWidget(self.repl_combo, 1, 1)
        grid.addWidget(self.lbl_filter, 2, 0)
        grid.addWidget(self.filter_combo, 2, 1)
        grid.addWidget(self.lbl_dir, 3, 0)
        grid.addWidget(self.dir_combo, 3, 1)
        grid.addWidget(self.browse_btn, 3, 2)
        fif = QHBoxLayout()
        self.follow_cb = QCheckBox("Follow current doc.")
        self.subfolders_cb = QCheckBox("In all su&b-folders")
        self.hidden_cb = QCheckBox("In &hidden folders")
        self.subfolders_cb.setChecked(True)
        for w in (self.follow_cb, self.subfolders_cb, self.hidden_cb):
            fif.addWidget(w)
        fif.addStretch(1)
        self.fif_row = QWidget()
        self.fif_row.setLayout(fif)
        left.addWidget(self.fif_row)
        prj = QHBoxLayout()
        self.proj_cbs = [QCheckBox("Project Panel %d" % (i + 1)) for i in range(3)]
        for w in self.proj_cbs:
            prj.addWidget(w)
        prj.addStretch(1)
        self.proj_row = QWidget()
        self.proj_row.setLayout(prj)
        left.addWidget(self.proj_row)
        mark = QHBoxLayout()
        self.bookmark_cb = QCheckBox("Book&mark line")
        self.purge_cb = QCheckBox("Purge for each search")
        mark.addWidget(self.bookmark_cb)
        mark.addWidget(self.purge_cb)
        mark.addStretch(1)
        self.mark_row = QWidget()
        self.mark_row.setLayout(mark)
        left.addWidget(self.mark_row)

        opts_row = QHBoxLayout()
        left.addLayout(opts_row)
        col1 = QVBoxLayout()
        self.insel_cb = QCheckBox("In select&ion")
        self.back_cb = QCheckBox("Backward direction")
        self.word_cb = QCheckBox("Match &whole word only")
        self.case_cb = QCheckBox("Match &case")
        self.wrap_cb = QCheckBox("Wra&p around")
        self.wrap_cb.setChecked(True)
        for w in (self.insel_cb, self.back_cb, self.word_cb, self.case_cb, self.wrap_cb):
            col1.addWidget(w)
        col1.addStretch(1)
        opts_row.addLayout(col1)
        col2 = QVBoxLayout()
        mode_box = QGroupBox("Search Mode")
        mb = QVBoxLayout(mode_box)
        self.mode_normal = QRadioButton("&Normal")
        self.mode_ext = QRadioButton("E&xtended (\\n, \\r, \\t, \\0, \\x...)")
        self.mode_rx = QRadioButton("Re&gular expression")
        self.dotnl_cb = QCheckBox("&. matches newline")
        self.mode_normal.setChecked(True)
        for w in (self.mode_normal, self.mode_ext, self.mode_rx, self.dotnl_cb):
            mb.addWidget(w)
        self.mode_rx.toggled.connect(lambda on: self.dotnl_cb.setEnabled(on))
        self.dotnl_cb.setEnabled(False)
        col2.addWidget(mode_box)
        tr_box = QGroupBox("Transparenc&y")
        tr_box.setCheckable(True)
        tb = QVBoxLayout(tr_box)
        self.tr_lose = QRadioButton("On losing focus")
        self.tr_always = QRadioButton("Always")
        self.tr_slider = QSlider(Qt.Orientation.Horizontal)
        self.tr_slider.setRange(20, 230)
        self.tr_slider.setValue(S_["find_alpha"])
        tb.addWidget(self.tr_lose)
        tb.addWidget(self.tr_always)
        tb.addWidget(self.tr_slider)
        self.tr_box = tr_box
        mode = S_["find_transparency"]
        tr_box.setChecked(mode != "none")
        (self.tr_always if mode == "always" else self.tr_lose).setChecked(True)
        for w in (tr_box, self.tr_lose, self.tr_always):
            (w.toggled).connect(lambda *_: self.apply_transparency())
        self.tr_slider.valueChanged.connect(lambda *_: self.apply_transparency())
        col2.addWidget(tr_box)
        opts_row.addLayout(col2)

        right = QVBoxLayout()
        body.addLayout(right)
        self.btns = {}

        def btn(key, text, fn):
            b = QPushButton(text)
            b.clicked.connect(fn)
            b.setAutoDefault(False)
            right.addWidget(b)
            self.btns[key] = b
            return b
        nav = QHBoxLayout()
        self.btn_prev = QPushButton("▲")
        self.btn_prev.setToolTip("Find Previous (Shift+Enter)")
        self.btn_prev.setMaximumWidth(34)
        self.btn_prev.clicked.connect(lambda: self.find_next(backward=True))
        self.btn_prev.setAutoDefault(False)
        self.btn_next = QPushButton("Find Next ▼")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(lambda: self.find_next())
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next, 1)
        right.addLayout(nav)
        btn("count", "Coun&t", lambda: self.main.do_count(self.current_opts()))
        btn("replace", "&Replace", self.replace)
        btn("replace_all", "Replace &All", lambda: self.main.do_replace_all(self.current_opts()))
        btn("replace_all_docs", "Replace All in All &Opened\nDocuments",
            lambda: self.main.do_replace_all(self.current_opts(), all_docs=True))
        btn("find_all_docs", "Find All in All &Opened\nDocuments", lambda: self.main.find_all(self.current_opts(), list(self.main.all_buffers)))
        btn("find_all_cur", "Find All in Current\nDocument", lambda: self.main.buf() and self.main.find_all(self.current_opts(), [self.main.buf()]))
        btn("fif_find", "Find All", self.find_in_files)
        btn("fif_replace", "Replace in Files", lambda: self.find_in_files(replace=True))
        btn("fip_find", "Find All", self.find_in_projects)
        btn("fip_replace", "Replace in Projects", lambda: self.find_in_projects(replace=True))
        btn("mark_all", "Mark All", lambda: self.main.do_mark(self.current_opts(), self.bookmark_cb.isChecked(),
                                                              self.purge_cb.isChecked()))
        btn("clear_marks", "Clear all marks", self.main.clear_marks)
        btn("copy_marked", "Copy Marked Text", self.main.copy_marked)
        right.addStretch(1)
        btn("close", "Close", self.hide)

        self.status = QLabel()
        self.status.setFrameShape(QLabel.Shape.StyledPanel)
        root.addWidget(self.status)
        QShortcut(QKeySequence("Shift+Return"), self, activated=lambda: self.find_next(backward=True))
        QShortcut(QKeySequence("Shift+Enter"), self, activated=lambda: self.find_next(backward=True))
        QShortcut(QKeySequence("F3"), self, activated=lambda: self.find_next())
        QShortcut(QKeySequence("Shift+F3"), self, activated=lambda: self.find_next(backward=True))
        for i, k in enumerate(("Ctrl+F", "Ctrl+H", "Ctrl+Shift+F", None, "Ctrl+M")):
            if k:
                QShortcut(QKeySequence(k), self, activated=lambda i=i: self.show_tab(i))
        self.restore_opts()
        self.follow_cb.toggled.connect(self._follow)

    # ----------------------------------------------------------------- state
    def restore_opts(self):
        o = self.main.S["find_opts"] or {}
        self.case_cb.setChecked(o.get("case", False))
        self.word_cb.setChecked(o.get("word", False))
        self.wrap_cb.setChecked(o.get("wrap", True))
        self.back_cb.setChecked(o.get("back", False))
        {"normal": self.mode_normal, "extended": self.mode_ext, "regex": self.mode_rx}.get(
            o.get("mode", "normal"), self.mode_normal).setChecked(True)
        self.dotnl_cb.setChecked(o.get("dotnl", False))
        self.subfolders_cb.setChecked(o.get("sub", True))
        self.hidden_cb.setChecked(o.get("hidden", False))
        self.follow_cb.setChecked(o.get("follow", False))
        self.bookmark_cb.setChecked(o.get("bookmark", False))
        self.purge_cb.setChecked(o.get("purge", False))

    def save_opts(self):
        self.main.S["find_opts"] = {
            "case": self.case_cb.isChecked(), "word": self.word_cb.isChecked(), "wrap": self.wrap_cb.isChecked(),
            "back": self.back_cb.isChecked(), "mode": self.mode(), "dotnl": self.dotnl_cb.isChecked(),
            "sub": self.subfolders_cb.isChecked(), "hidden": self.hidden_cb.isChecked(),
            "follow": self.follow_cb.isChecked(), "bookmark": self.bookmark_cb.isChecked(),
            "purge": self.purge_cb.isChecked()}
        tr = "none" if not self.tr_box.isChecked() else ("always" if self.tr_always.isChecked() else "lose")
        self.main.S["find_transparency"] = tr
        self.main.S["find_alpha"] = self.tr_slider.value()

    def mode(self):
        if self.mode_rx.isChecked():
            return srch.MODE_REGEX
        if self.mode_ext.isChecked():
            return srch.MODE_EXTENDED
        return srch.MODE_NORMAL

    def current_opts(self):
        self._remember()
        self.save_opts()
        tab = self.tabbar.currentIndex()
        return srch.Opts(text=self.find_combo.currentText(), replace=self.repl_combo.currentText(),
                         mode=self.mode(), match_case=self.case_cb.isChecked(), whole_word=self.word_cb.isChecked(),
                         wrap=self.wrap_cb.isChecked(), backward=self.back_cb.isChecked(),
                         in_selection=self.insel_cb.isChecked() and self.insel_cb.isEnabled() and tab in (0, 1, 4),
                         dot_nl=self.dotnl_cb.isChecked())

    def _remember(self):
        for combo, key in ((self.find_combo, "find_history"), (self.repl_combo, "replace_history"),
                           (self.filter_combo, "filter_history"), (self.dir_combo, "dir_history")):
            t = combo.currentText()
            if not t and key != "replace_history":
                continue
            hist = [h for h in self.main.S[key] if h != t]
            if t:
                hist.insert(0, t)
            self.main.S[key] = hist[:20]
            i = combo.findText(t)
            if i >= 0:
                combo.removeItem(i)
            if t:
                combo.insertItem(0, t)
                combo.setCurrentIndex(0)

    def set_find_text(self, t):
        self.find_combo.setCurrentText(t)

    def set_in_selection(self, on):
        self.insel_cb.setChecked(bool(on))

    def set_status(self, msg, kind="msg"):
        st = self.main.styles
        from PyQt6.QtGui import QColor
        col = {"err": st.gfg("Find status: Not found", QColor("#FF0000")),
               "end": st.gfg("Find status: Search end reached", QColor("#008000"))}.get(
            kind, st.gfg("Find status: Message", QColor("#0000FF")))
        self.status.setStyleSheet("color:%s;" % col.name())
        self.status.setText(msg)

    # ------------------------------------------------------------------ tabs
    def show_tab(self, i):
        self.tabbar.setCurrentIndex(i)
        self._tab_changed(i)
        self.show()
        self.raise_()
        self.activateWindow()
        self.find_combo.setFocus()
        self.find_combo.lineEdit().selectAll()
        if i == 2 and not self.dir_combo.currentText():
            b = self.main.buf()
            if b is not None and b.path:
                self.dir_combo.setCurrentText(os.path.dirname(b.path))
        self._follow()

    def _tab_changed(self, i):
        tr = self.main.i18n.find
        self.setWindowTitle(tr.get(TAB_KEYS[i], TABS[i]))
        repl = i in (1, 2, 3)
        self.lbl_repl.setVisible(repl)
        self.repl_combo.setVisible(repl)
        self.swap_btn.setVisible(repl)
        fif = i == 2
        for w in (self.lbl_filter, self.filter_combo):
            w.setVisible(i in (2, 3))
        for w in (self.lbl_dir, self.dir_combo, self.browse_btn, self.fif_row):
            w.setVisible(fif)
        self.proj_row.setVisible(i == 3)
        self.mark_row.setVisible(i == 4)
        self.insel_cb.setVisible(i in (0, 1, 4))
        self.back_cb.setVisible(i in (0, 1))
        self.wrap_cb.setVisible(i in (0, 1))
        vis = {
            0: ("count", "find_all_docs", "find_all_cur", "close"),
            1: ("replace", "replace_all", "replace_all_docs", "close"),
            2: ("fif_find", "fif_replace", "close"),
            3: ("fip_find", "fip_replace", "close"),
            4: ("mark_all", "clear_marks", "copy_marked", "close"),
        }[i]
        for k, b in self.btns.items():
            b.setVisible(k in vis)
        nav = i in (0, 1)
        self.btn_next.setVisible(nav)
        self.btn_prev.setVisible(nav)
        if i == 4:
            self.btns["mark_all"].setDefault(True)
        elif i == 2:
            self.btns["fif_find"].setDefault(True)
        elif i == 3:
            self.btns["fip_find"].setDefault(True)
        else:
            self.btn_next.setDefault(True)
        self.adjustSize()

    def _follow(self):
        if self.follow_cb.isChecked():
            b = self.main.buf()
            if b is not None and b.path:
                self.dir_combo.setCurrentText(os.path.dirname(b.path))

    # --------------------------------------------------------------- actions
    def find_next(self, backward=False):
        tab = self.tabbar.currentIndex()
        if tab == 4:
            self.btns["mark_all"].click()
            return
        if tab == 2:
            self.find_in_files()
            return
        if tab == 3:
            self.find_in_projects()
            return
        o = self.current_opts()
        if backward:
            o.backward = not o.backward
        if o.in_selection:
            o.in_selection = False
        self.main.do_find(o)
        if not self.main.S["find_stay_open"] and False:
            self.hide()

    def replace(self):
        self.main.do_replace(self.current_opts())

    def swap(self):
        a, b = self.find_combo.currentText(), self.repl_combo.currentText()
        self.find_combo.setCurrentText(b)
        self.repl_combo.setCurrentText(a)

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select a folder to search from", self.dir_combo.currentText() or os.path.expanduser("~"))
        if d:
            self.dir_combo.setCurrentText(d)

    def find_in_files(self, replace=False):
        o = self.current_opts()
        if not o.text:
            return
        self.main.find_in_files(o, os.path.expanduser(self.dir_combo.currentText()),
                                self.filter_combo.currentText() or "*.*",
                                self.subfolders_cb.isChecked(), self.hidden_cb.isChecked(), replace=replace)

    def find_in_projects(self, replace=False):
        o = self.current_opts()
        if not o.text:
            return
        files = []
        for i, cb in enumerate(self.proj_cbs):
            if cb.isChecked():
                p = self.main.panels.get("project%d" % (i + 1))
                if p is not None:
                    files += p.all_files()
        if not files:
            self.set_status("Find in Projects: no project panel is checked or the projects are empty.", "err")
            return
        import fnmatch
        inc, exc, _, _ = srch.parse_filters(self.filter_combo.currentText() or "*.*")
        files = [f for f in files if any(fnmatch.fnmatch(os.path.basename(f), p) for p in inc)
                 and not any(fnmatch.fnmatch(os.path.basename(f), p) for p in exc)]
        try:
            import regex
            rx = srch.compile_opts(o, self.main.S["extra_word_chars"])
        except Exception:
            self.set_status("Find in Projects: Invalid regular expression", "err")
            return
        from ..cmd_search import FindInFilesWorker
        rp = self.main.results_panel()
        rp.begin_search(o.text, in_files=True)
        self.main.show_panel("results", True)
        w = FindInFilesWorker(iter(files), rx, o.replace if replace else None, o, self.main.S)
        self._worker = w
        w.file_done.connect(lambda p, hits: rp.add_file(p, hits))
        w.finished_all.connect(lambda h, n, s: (rp.end_search(h, n, s),
                                                self.set_status("Find in Projects: %d hits in %d files of %d searched" % (h, n, s),
                                                                "msg" if h else "err")))
        w.start()

    # ---------------------------------------------------------- transparency
    def apply_transparency(self, active=None):
        if active is None:
            active = self.isActiveWindow()
        if not self.tr_box.isChecked():
            self.setWindowOpacity(1.0)
            return
        alpha = self.tr_slider.value() / 255.0
        if self.tr_always.isChecked() or not active:
            self.setWindowOpacity(alpha)
        else:
            self.setWindowOpacity(1.0)

    def changeEvent(self, e):
        if e.type() == QEvent.Type.ActivationChange:
            self.apply_transparency(self.isActiveWindow())
        super().changeEvent(e)

    def hideEvent(self, e):
        self.save_opts()
        super().hideEvent(e)
