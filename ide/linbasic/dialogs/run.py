"""Run... dialog (resource 1900) with the $(VARIABLE) menu (resource 1950)."""
import os

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QToolButton, QPushButton,
                             QMenu, QFileDialog)

from ..npp_tables import RUNVARS


class RunDialog(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Run...")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("The &Program to Run"))
        row = QHBoxLayout()
        self.cmd = QComboBox()
        self.cmd.setEditable(True)
        self.cmd.setMinimumWidth(380)
        hist = [c["cmd"] for c in main.shortcut_file.commands]
        if main.S["run_last"]:
            hist.insert(0, main.S["run_last"])
        seen = []
        for h in hist:
            if h not in seen:
                seen.append(h)
        self.cmd.addItems(seen)
        row.addWidget(self.cmd, 1)
        browse = QToolButton()
        browse.setText("...")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        plus = QToolButton()
        plus.setText("&+")
        menu = QMenu(self)
        for cid, label in RUNVARS:
            name, _, desc = label.partition("\t")
            var = name.replace("&", "")
            a = menu.addAction("%s\t%s" % (name, desc))
            a.triggered.connect(lambda checked=False, v=var: self.insert_var(v))
        plus.setMenu(menu)
        plus.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        row.addWidget(plus)
        lay.addLayout(row)
        bb = QHBoxLayout()
        bb.addStretch(1)
        run = QPushButton("&Run")
        run.setDefault(True)
        run.clicked.connect(self.run)
        save = QPushButton("&Save...")
        save.clicked.connect(self.save)
        cancel = QPushButton("&Cancel")
        cancel.clicked.connect(self.reject)
        for b in (run, save, cancel):
            bb.addWidget(b)
        lay.addLayout(bb)

    def insert_var(self, v):
        le = self.cmd.lineEdit()
        le.insert("$(%s)" % v)

    def browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Program", "/usr/bin")
        if f:
            self.cmd.setCurrentText('"%s"' % f if " " in f else f)

    def run(self):
        c = self.cmd.currentText().strip()
        if c:
            self.main.S["run_last"] = c
            self.main.run_user_command(c)
            self.accept()

    def save(self):
        c = self.cmd.currentText().strip()
        if not c:
            return
        from .shortcuts import ShortcutDialog
        d = ShortcutDialog(self, "Shortcut", "", None)
        if d.exec():
            name, seq = d.result_value()
            if name:
                self.main.shortcut_file.commands.append({"name": name, "folder": "", "seq": seq, "cmd": c})
                self.main.shortcut_file.save()
                self.main.dynamic_shortcuts()
