"""Style Configurator (resource 2200): themes, per-language styles, global styles."""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontDatabase
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QListWidget,
                             QGroupBox, QPushButton, QCheckBox, QColorDialog, QLineEdit, QPlainTextEdit,
                             QMessageBox)

from .. import paths, styles as stl

OVERRIDE_KEYS = [("fg", "Enable global foreground colour"), ("bg", "Enable global background colour"),
                 ("font", "Enable global font"), ("size", "Enable global font size"),
                 ("bold", "Enable global bold font style"), ("italic", "Enable global italic font style"),
                 ("underline", "Enable global underline font style")]


class ColorButton(QPushButton):
    def __init__(self, title):
        super().__init__()
        self.title = title
        self.color = None
        self.setFixedSize(48, 22)
        self.clicked.connect(self.pick)
        self.on_change = None

    def set_color(self, c):
        self.color = c
        self.setStyleSheet("background:%s; border:1px solid #808080;" % (c.name() if c else "transparent"))
        self.setEnabled(c is not None)

    def pick(self):
        c = QColorDialog.getColor(self.color or QColor("white"), self, self.title)
        if c.isValid():
            self.set_color(c)
            if self.on_change:
                self.on_change(c)


class StyleConfigurator(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Style Configurator")
        self.resize(820, 520)
        self.orig_theme = main.S["theme"]
        self.orig_override = dict(main.styles.override)
        self.styles = main.styles
        self.cur_style = None
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Select theme :"))
        self.theme = QComboBox()
        self.themes = paths.list_themes()
        cur_idx = 0
        for i, (name, path) in enumerate(self.themes):
            self.theme.addItem(name, path)
            if main.S["theme"] and os.path.basename(path) == main.S["theme"]:
                cur_idx = i
        self.theme.setCurrentIndex(cur_idx)
        self.theme.currentIndexChanged.connect(self.change_theme)
        top.addWidget(self.theme, 1)
        lay.addLayout(top)
        mid = QHBoxLayout()
        lay.addLayout(mid, 1)
        c1 = QVBoxLayout()
        c1.addWidget(QLabel("Language :"))
        self.langs = QListWidget()
        c1.addWidget(self.langs)
        mid.addLayout(c1, 1)
        c2 = QVBoxLayout()
        c2.addWidget(QLabel("Style :"))
        self.style_list = QListWidget()
        c2.addWidget(self.style_list)
        mid.addLayout(c2, 1)
        c3 = QVBoxLayout()
        mid.addLayout(c3, 2)
        cs = QGroupBox("Colour Style")
        g = QGridLayout(cs)
        self.fg = ColorButton("Foreground colour")
        self.bg = ColorButton("Background colour")
        g.addWidget(QLabel("Foreground colour"), 0, 0)
        g.addWidget(self.fg, 0, 1)
        g.addWidget(QLabel("Background colour"), 1, 0)
        g.addWidget(self.bg, 1, 1)
        c3.addWidget(cs)
        fs = QGroupBox("Font Style")
        g2 = QGridLayout(fs)
        self.font = QComboBox()
        self.font.addItem("")
        self.font.addItems(QFontDatabase.families())
        self.size = QComboBox()
        self.size.addItems([""] + [str(s) for s in (5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28)])
        self.bold = QCheckBox("Bold")
        self.italic = QCheckBox("Italic")
        self.under = QCheckBox("Underline")
        g2.addWidget(QLabel("Font name :"), 0, 0)
        g2.addWidget(self.font, 0, 1, 1, 3)
        g2.addWidget(QLabel("Font size :"), 1, 0)
        g2.addWidget(self.size, 1, 1)
        g2.addWidget(self.bold, 2, 0)
        g2.addWidget(self.italic, 2, 1)
        g2.addWidget(self.under, 2, 2)
        c3.addWidget(fs)
        self.ovr_box = QGroupBox("Global override")
        ol = QVBoxLayout(self.ovr_box)
        self.ovr = {}
        for k, t in OVERRIDE_KEYS:
            cb = QCheckBox(t)
            cb.setChecked(bool(self.styles.override.get(k)))
            cb.toggled.connect(self.override_changed)
            ol.addWidget(cb)
            self.ovr[k] = cb
        c3.addWidget(self.ovr_box)
        er = QHBoxLayout()
        self.def_ext = QLabel()
        self.user_ext = QLineEdit()
        er.addWidget(QLabel("Default ext. :"))
        er.addWidget(self.def_ext)
        er.addWidget(QLabel("User ext. :"))
        er.addWidget(self.user_ext, 1)
        self.ext_row = er
        c3.addLayout(er)
        self.kw_box = QGroupBox("Keywords")
        kl = QVBoxLayout(self.kw_box)
        self.def_kw = QPlainTextEdit()
        self.def_kw.setReadOnly(True)
        self.user_kw = QPlainTextEdit()
        kl.addWidget(QLabel("Default keywords"))
        kl.addWidget(self.def_kw)
        kl.addWidget(QLabel("User-defined keywords"))
        kl.addWidget(self.user_kw)
        c3.addWidget(self.kw_box, 1)
        c3.addStretch(0)
        bb = QHBoxLayout()
        bb.addStretch(1)
        save = QPushButton("Save && Close")
        save.clicked.connect(self.save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancel)
        bb.addWidget(save)
        bb.addWidget(cancel)
        lay.addLayout(bb)
        self.langs.currentRowChanged.connect(self.lang_changed)
        self.style_list.currentRowChanged.connect(self.style_changed)
        self.fg.on_change = lambda c: self.set_attr("fg", c)
        self.bg.on_change = lambda c: self.set_attr("bg", c)
        self.font.currentTextChanged.connect(lambda t: self.set_attr("font", t))
        self.size.currentTextChanged.connect(lambda t: self.set_attr("size", int(t) if t.isdigit() else None))
        self.bold.toggled.connect(lambda v: self.set_bit(1, v))
        self.italic.toggled.connect(lambda v: self.set_bit(2, v))
        self.under.toggled.connect(lambda v: self.set_bit(4, v))
        self.user_kw.textChanged.connect(self.kw_changed)
        self.user_ext.textEdited.connect(self.ext_changed)
        self.fill_langs()

    def fill_langs(self):
        self.langs.blockSignals(True)
        self.langs.clear()
        self.langs.addItem("Global Styles")
        self.lang_names = [None]
        for n in self.styles.lexer_order:
            if n == "searchResult":
                continue
            self.langs.addItem(self.styles.lexers[n].desc)
            self.lang_names.append(n)
        self.langs.blockSignals(False)
        self.langs.setCurrentRow(0)
        self.lang_changed(0)

    def current_list(self):
        r = self.langs.currentRow()
        if r <= 0:
            return self.styles.globals, None
        ls = self.styles.lexers[self.lang_names[r]]
        return ls.styles, ls

    def lang_changed(self, r):
        lst, ls = self.current_list()
        self.style_list.blockSignals(True)
        self.style_list.clear()
        for st in lst:
            self.style_list.addItem(st.name)
        self.style_list.blockSignals(False)
        is_g = ls is None
        self.def_ext.setText(" ".join(self.main.langdb.get(ls.name).ext) if ls else "")
        self.user_ext.setText(ls.ext if ls else "")
        self.user_ext.setEnabled(not is_g)
        if self.style_list.count():
            self.style_list.setCurrentRow(0)
            self.style_changed(0)

    def style_changed(self, r):
        lst, ls = self.current_list()
        if r < 0 or r >= len(lst):
            return
        st = lst[r]
        self.cur_style = None
        self.fg.set_color(st.fg if st.elem.get("fgColor") is not None else None)
        self.bg.set_color(st.bg if st.elem.get("bgColor") is not None else None)
        has_font = st.elem.get("fontName") is not None
        for w in (self.font, self.size, self.bold, self.italic, self.under):
            w.setEnabled(has_font or st.elem.get("fontStyle") is not None)
        self.font.setCurrentText(st.font)
        self.size.setCurrentText(str(st.size) if st.size else "")
        fsv = st.fstyle or 0
        self.bold.setChecked(bool(fsv & 1))
        self.italic.setChecked(bool(fsv & 2))
        self.under.setChecked(bool(fsv & 4))
        self.ovr_box.setVisible(ls is None and st.name in ("Global override", "Default Style"))
        self.kw_box.setVisible(bool(st.kwclass))
        if st.kwclass and ls is not None:
            self.def_kw.setPlainText(self.main.langdb.get(ls.name).keywords.get(st.kwclass, ""))
            self.user_kw.blockSignals(True)
            self.user_kw.setPlainText(st.words)
            self.user_kw.blockSignals(False)
        self.cur_style = st

    def set_attr(self, attr, v):
        st = self.cur_style
        if st is None:
            return
        setattr(st, attr, v)
        self.preview()

    def set_bit(self, bit, on):
        st = self.cur_style
        if st is None:
            return
        st.fstyle = ((st.fstyle or 0) & ~bit) | (bit if on else 0)
        self.preview()

    def kw_changed(self):
        if self.cur_style is not None:
            self.cur_style.words = " ".join(self.user_kw.toPlainText().split())
            self.preview(relex=True)

    def ext_changed(self, t):
        lst, ls = self.current_list()
        if ls is not None:
            ls.ext = t
            ls.elem.set("ext", t)

    def override_changed(self):
        self.styles.override = {k: cb.isChecked() for k, cb in self.ovr.items()}
        self.preview()

    def preview(self, relex=False):
        self.main.styles = self.styles
        self.main.restyle_all()
        self.main.apply_palette()

    def change_theme(self, i):
        path = self.theme.itemData(i)
        ov = self.styles.override
        self.styles = stl.load_styleset(path)
        self.styles.override = ov
        self.fill_langs()
        self.preview()

    def save(self):
        i = self.theme.currentIndex()
        path = self.theme.itemData(i)
        default = i == 0
        if default:
            target = paths.cfg("stylers.xml")
            self.main.S["theme"] = ""
            self.main.S["dark_theme" if self.main.ui_is_dark() else "light_theme"] = ""
        else:
            target = paths.cfg("themes", os.path.basename(path))
            self.main.S["theme"] = os.path.basename(path)
            self.main.S["dark_theme" if self.main.ui_is_dark() else "light_theme"] = os.path.basename(path)
        try:
            self.styles.save(target)
            self.styles.path = target
        except OSError as ex:
            QMessageBox.warning(self, "Style Configurator", str(ex))
        self.main.S["global_override"] = self.styles.override
        self.main.styles = self.styles
        self.main.restyle_all()
        self.main.apply_palette()
        self.accept()

    def cancel(self):
        self.main.S["theme"] = self.orig_theme
        self.main.load_theme()
        self.main.styles.override = self.orig_override
        self.main.restyle_all()
        self.main.apply_palette()
        self.reject()
