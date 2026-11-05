"""Preferences (resource 6000 and its 6010-7160 sub-pages)."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QStackedWidget, QWidget, QFormLayout,
                             QCheckBox, QSpinBox, QComboBox, QLineEdit, QLabel, QPushButton, QGroupBox,
                             QButtonGroup, QRadioButton, QFileDialog, QScrollArea)

from .. import i18n

ENC = [("ansi", "ANSI"), ("utf8", "UTF-8"), ("utf8bom", "UTF-8 with BOM"),
       ("utf16be", "UTF-16 Big Endian with BOM"), ("utf16le", "UTF-16 Little Endian with BOM")]


def pages(main):
    langs = [(n, main.langdb.get(n).desc) for n in sorted(main.langdb.menu_langs())]
    return [
        ("General", [
            ("combo", "localization", "Localization", [(f, n) for n, f in i18n.available()]),
            ("check", "menubar_hidden", "Hide menu bar (use Alt or F10 key to toggle)"),
            ("check", "statusbar_hidden", "Hide status bar"),
        ]),
        ("Toolbar", [
            ("check", "toolbar_hidden", "Hide toolbar"),
            ("radio", "toolbar_icons", "Icon size", [("small", "Fluent UI: small"), ("large", "Fluent UI: large")]),
        ]),
        ("Tab Bar", [
            ("check", "tabbar_hidden", "Hide tab bar"),
            ("check", "tab_lock", "Lock (no drag and drop)"),
            ("check", "tab_dblclick_close", "Double click to close document"),
            ("check", "tab_exit_on_last", "Exit on close the last tab"),
            ("check", "tab_close_button", "Show close button on each tab"),
            ("check", "tab_reduce", "Reduce"),
            ("spin", "tab_max_len", "Max. tab label length (0 = no limit)", 0, 200),
        ]),
        ("Editing 1", [
            ("radio", "caretline_mode", "Current Line Indicator", [(0, "None"), (1, "Highlight Background"), (2, "Frame")]),
            ("spin", "caretline_frame_width", "Frame width", 1, 6),
            ("spin", "caret_width", "Caret width", 0, 4),
            ("spin", "caret_blink", "Caret blink rate (ms, 0 = no blink)", 0, 2500),
            ("radio", "wrap_mode", "Line Wrap", [(0, "Default"), (1, "Aligned"), (2, "Indent")]),
            ("check", "smooth_font", "Enable smooth font"),
            ("check", "virtual_space", "Enable virtual space"),
            ("check", "scroll_beyond_last", "Enable scrolling beyond last line"),
        ]),
        ("Editing 2", [
            ("check", "multi_edit", "Enable Multi-Editing (Ctrl+Mouse click/selection)"),
            ("check", "column_to_multi", "Enable Column Selection to Multi-Editing"),
            ("radio", "npc_appearance", "Non-Printing Characters appearance", [("abbrev", "Abbreviation"), ("codepoint", "Codepoint")]),
        ]),
        ("Dark Mode", [
            ("radio", "dark_mode", "Mode", [("light", "Light mode"), ("dark", "Dark mode"), ("system", "Follow system")]),
            ("label", "Dark mode switches the editor to a dark theme (DarkModeDefault by default). A theme you pick in Settings → Style Configurator is remembered separately for light and dark mode."),
        ]),
        ("Margins/Border/Edge", [
            ("radio", "fold_style", "Fold Margin Style", [("simple", "Simple"), ("arrow", "Arrow"), ("circle", "Circle tree"),
                                                         ("box", "Box tree"), ("none", "None")]),
            ("check", "line_numbers", "Display line number"),
            ("check", "line_numbers_dynamic", "Dynamic width (else constant)"),
            ("check", "bookmark_margin", "Display bookmark"),
            ("check", "change_history", "Show change history in the margin"),
            ("radio", "edge_mode", "Vertical Edge", [(0, "No edge"), (1, "Line mode"), (2, "Background mode")]),
            ("text", "edge_columns", "Edge column(s), space separated"),
            ("spin", "padding_left", "Padding left (px)", 0, 30),
            ("spin", "padding_right", "Padding right (px)", 0, 30),
        ]),
        ("New Document", [
            ("radio", "new_eol", "Format (Line ending)", [(0, "Windows (CR LF)"), (2, "Unix (LF)"), (1, "Macintosh (CR)")]),
            ("radio", "new_encoding", "Encoding", ENC),
            ("check", "apply_utf8_to_ansi", "Apply to opened ANSI files"),
            ("combo", "new_lang", "Default language", langs),
        ]),
        ("Default Directory", [
            ("radio", "open_dir_mode", "Default Open/Save file Directory",
             [("follow", "Follow current document"), ("remember", "Remember last used directory"), ("custom", "Custom")]),
            ("dir", "open_dir_custom", "Custom directory"),
        ]),
        ("Recent Files History", [
            ("check", "recent_dont_check", "Don't check at launch time"),
            ("spin", "recent_max", "Max. number of entries", 0, 30),
            ("check", "recent_submenu", "In Submenu"),
            ("radio", "recent_display", "Display", [("name", "Only File Name"), ("full", "Full File Name Path")]),
            ("spin", "recent_maxlen", "Customize Maximum Length", 1, 259),
        ]),
        ("Language", [
            ("check", "lang_compact", "Make language menu compact"),
            ("langtabs",),
        ]),
        ("Indentation", [
            ("spin", "tab_size", "Indent size", 1, 32),
            ("radio", "use_spaces", "Indent using", [(False, "Tab character"), (True, "Space character(s)")]),
            ("check", "backspace_unindent", "Backspace key unindents instead of removing single space"),
            ("radio", "auto_indent", "Auto-indent", [("none", "None"), ("basic", "Basic"), ("advanced", "Advanced")]),
        ]),
        ("Highlighting", [
            ("label", "<b>Style All Occurrences of Token</b>"),
            ("check", "token_match_case", "Match case"), ("check", "token_whole_word", "Match whole word only"),
            ("label", "<b>Smart Highlighting</b>"),
            ("check", "smart_hl", "Enable"), ("check", "smart_hl_case", "Match case"),
            ("check", "smart_hl_word", "Match whole word only"), ("check", "smart_hl_use_find", "Use Find dialog settings"),
            ("check", "smart_hl_other_view", "Highlight another view"),
            ("label", "<b>Highlight Matching Tags</b>"),
            ("check", "tag_match", "Enable"), ("check", "tag_attr", "Highlight tag attributes"),
        ]),
        ("Print", [
            ("check", "print_linenums", "Print line number"),
            ("radio", "print_color", "Color Options", [("wysiwyg", "WYSIWYG"), ("invert", "Invert"),
                                                       ("bw", "Black on white"), ("nobg", "No background color")]),
        ]),
        ("Searching", [
            ("check", "find_fill_selected", "Fill Find Field with Selected Text"),
            ("check", "find_fill_word", "Select Word Under Caret when Nothing Selected"),
            ("spin", "find_maxchars", "Max Characters to Auto-Fill Find Field from Selection", 1, 16384),
            ("check", "find_in_sel_auto", "Auto-check \"In selection\" for multi-line selections"),
            ("spin", "find_in_sel_min", "Minimum Size for Auto-Checking \"In selection\"", 1, 1_000_000),
            ("check", "find_mono", "Use Monospaced font in Find dialog (needs restart of the dialog)"),
            ("check", "confirm_replace_all_docs", "Confirm Replace All in All Opened Documents"),
            ("check", "replace_no_move", "Replace: Don't move to the following occurrence"),
        ]),
        ("Backup", [
            ("check", "remember_session", "Remember current session for next launch"),
            ("check", "snapshot", "Enable session snapshot and periodic backup"),
            ("spin", "snapshot_interval", "Trigger backup on modification in every (seconds)", 1, 3600),
            ("radio", "backup_mode", "Backup on save", [("none", "None"), ("simple", "Simple backup"), ("verbose", "Verbose backup")]),
            ("dir", "backup_dir", "Custom Backup Directory"),
        ]),
        ("Auto-Completion", [
            ("check", "ac_enable", "Enable auto-completion on each input"),
            ("radio", "ac_mode", "", [("func", "Function completion"), ("word", "Word completion"),
                                      ("both", "Function and word completion")]),
            ("spin", "ac_from", "From Nth character", 1, 9),
            ("check", "ac_ignore_numbers", "Ignore numbers"),
            ("check", "param_hint", "Function parameters hint on input"),
            ("label", "<b>Auto-Insert</b>"),
            ("check", "ai_paren", "( )"), ("check", "ai_bracket", "[ ]"), ("check", "ai_brace", "{ }"),
            ("check", "ai_dquote", "\" \""), ("check", "ai_squote", "' '"), ("check", "ai_tag", "html/xml close tag"),
        ]),
        ("Multi-Instance & Date", [
            ("radio", "multi_instance", "Multi-instance settings", [("mono", "Default (mono-instance)"),
                                                                   ("multi", "Always in multi-instance mode")]),
            ("text", "date_format", "Customize insert Date Time: custom format"),
            ("check", "date_reverse", "Reverse default date time order (short & long formats)"),
        ]),
        ("Delimiter", [
            ("text", "extra_word_chars", "Add your character as part of word"),
            ("text", "delim_open", "Delimiter selection: open"),
            ("text", "delim_close", "Delimiter selection: close"),
            ("check", "delim_multiline", "Allow on several lines"),
        ]),
        ("Performance", [
            ("check", "large_file_restrict", "Enable Large File Restriction (no syntax highlighting)"),
            ("spin", "large_file_mb", "Define Large File Size (MB)", 1, 2046),
            ("check", "large_no_wrap", "Deactivate Word Wrap globally"),
            ("check", "large_ac", "Allow Auto-Completion"), ("check", "large_smart", "Allow Smart Highlighting"),
            ("check", "large_brace", "Allow Brace Match"), ("check", "large_links", "Allow URL Clickable Link"),
        ]),
        ("Cloud & Link", [
            ("check", "link_enable", "Clickable Link: Enable"),
            ("check", "link_underline", "Underline"),
            ("check", "link_fullbox", "Enable fullbox mode"),
            ("text", "uri_schemes", "URI customized schemes"),
        ]),
        ("Search Engine", [
            ("radio", "search_engine", "Search Engine (for command \"Search on Internet\")", [
                ("https://duckduckgo.com/?q=$(CURRENT_WORD)", "DuckDuckGo"),
                ("https://www.google.com/search?q=$(CURRENT_WORD)", "Google"),
                ("https://search.yahoo.com/search?q=$(CURRENT_WORD)", "Yahoo!"),
                ("https://stackoverflow.com/search?q=$(CURRENT_WORD)", "Stack Overflow")]),
            ("text", "search_engine", "Set your search engine here"),
        ]),
        ("MISC.", [
            ("radio", "file_autodetect", "File Status Auto-Detection", [("enabled", "Enable"), ("silent", "Update silently"),
                                                                         ("disabled", "Disable")]),
            ("check", "autodetect_scroll_end", "Scroll to the last line after update"),
            ("check", "docswitcher_mru", "Document Switcher (Ctrl+TAB): Enable MRU behaviour"),
            ("check", "minimize_to_tray", "Minimize to system tray"),
            ("check", "close_to_tray", "Close to system tray"),
            ("check", "title_filename_only", "Show only filename in title bar"),
            ("check", "autodetect_encoding", "Autodetect character encoding"),
            ("text", "ansi_codepage", "ANSI code page (empty = from locale, e.g. cp1253)"),
            ("text", "session_ext", "Session file ext."),
        ]),
    ]


class PreferencesDialog(QDialog):
    def __init__(self, main, page=None):
        super().__init__(main)
        self.main = main
        self.setWindowTitle("Preferences")
        self.resize(820, 560)
        self.getters = []
        lay = QVBoxLayout(self)
        body = QHBoxLayout()
        lay.addLayout(body, 1)
        self.list = QListWidget()
        self.list.setMaximumWidth(200)
        self.stack = QStackedWidget()
        body.addWidget(self.list)
        body.addWidget(self.stack, 1)
        for title, items in pages(main):
            self.list.addItem(title)
            w = QWidget()
            form = QVBoxLayout(w)
            for it in items:
                self._build(form, it)
            form.addStretch(1)
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setWidget(w)
            self.stack.addWidget(sa)
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)
        start = 0
        if page:
            for i in range(self.list.count()):
                if self.list.item(i).text() == page:
                    start = i
        self.list.setCurrentRow(start)
        bb = QHBoxLayout()
        bb.addStretch(1)
        ok = QPushButton("Close")
        ok.setDefault(True)
        ok.clicked.connect(self.apply_close)
        bb.addWidget(ok)
        lay.addLayout(bb)

    def _build(self, form, it):
        S_ = self.main.S
        kind = it[0]
        if kind == "label":
            l = QLabel(it[1])
            l.setWordWrap(True)
            form.addWidget(l)
        elif kind == "check":
            cb = QCheckBox(it[2])
            cb.setChecked(bool(S_[it[1]]))
            form.addWidget(cb)
            self.getters.append((it[1], cb.isChecked))
        elif kind == "spin":
            row = QHBoxLayout()
            sp = QSpinBox()
            sp.setRange(it[3], it[4])
            sp.setValue(int(S_[it[1]]))
            row.addWidget(QLabel(it[2]))
            row.addWidget(sp)
            row.addStretch(1)
            form.addLayout(row)
            self.getters.append((it[1], sp.value))
        elif kind == "text":
            row = QHBoxLayout()
            le = QLineEdit(str(S_[it[1]] or ""))
            row.addWidget(QLabel(it[2]))
            row.addWidget(le, 1)
            form.addLayout(row)
            self.getters.append((it[1], le.text))
        elif kind == "dir":
            row = QHBoxLayout()
            le = QLineEdit(str(S_[it[1]] or ""))
            b = QPushButton("...")
            b.clicked.connect(lambda: le.setText(QFileDialog.getExistingDirectory(self, it[2], le.text()) or le.text()))
            row.addWidget(QLabel(it[2]))
            row.addWidget(le, 1)
            row.addWidget(b)
            form.addLayout(row)
            self.getters.append((it[1], le.text))
        elif kind == "combo":
            row = QHBoxLayout()
            cb = QComboBox()
            for v, label in it[3]:
                cb.addItem(label, v)
            i = cb.findData(S_[it[1]])
            if i >= 0:
                cb.setCurrentIndex(i)
            row.addWidget(QLabel(it[2]))
            row.addWidget(cb, 1)
            form.addLayout(row)
            self.getters.append((it[1], cb.currentData))
        elif kind == "radio":
            box = QGroupBox(it[2])
            bl = QVBoxLayout(box)
            grp = QButtonGroup(box)
            opts = []
            for v, label in it[3]:
                rb = QRadioButton(label)
                rb.setChecked(S_[it[1]] == v)
                grp.addButton(rb)
                bl.addWidget(rb)
                opts.append((rb, v))
            form.addWidget(box)
            if it[1] == "dark_mode":
                # Notepad++ applies the dark mode choice immediately
                for rb, v in opts:
                    rb.toggled.connect(lambda on, v=v: on and self._live_dark(v))
            cur = S_[it[1]]
            self.getters.append((it[1], lambda opts=opts, cur=cur, key=it[1]: next((v for rb, v in opts if rb.isChecked()), self.main.S[key])))
        elif kind == "langtabs":
            box = QGroupBox("Tab Settings")
            bl = QVBoxLayout(box)
            row = QHBoxLayout()
            self.lt_lang = QComboBox()
            for n in sorted(self.main.langdb.menu_langs()):
                self.lt_lang.addItem(self.main.langdb.get(n).desc, n)
            self.lt_default = QCheckBox("Use default value")
            self.lt_size = QSpinBox()
            self.lt_size.setRange(1, 32)
            self.lt_spaces = QCheckBox("Replace by space")
            row.addWidget(self.lt_lang, 1)
            bl.addLayout(row)
            row2 = QHBoxLayout()
            row2.addWidget(self.lt_default)
            row2.addWidget(QLabel("Tab size:"))
            row2.addWidget(self.lt_size)
            row2.addWidget(self.lt_spaces)
            row2.addStretch(1)
            bl.addLayout(row2)
            form.addWidget(box)
            self.lt_data = dict(self.main.S["lang_tabs"])
            self.lt_lang.currentIndexChanged.connect(self._lt_load)
            for w in (self.lt_default,):
                w.toggled.connect(self._lt_store)
            self.lt_size.valueChanged.connect(self._lt_store)
            self.lt_spaces.toggled.connect(self._lt_store)
            self._lt_loading = False
            self._lt_load()
            self.getters.append(("lang_tabs", lambda: self.lt_data))

    def _live_dark(self, mode):
        self.main.S["dark_mode"] = mode
        self.main.apply_dark_mode()

    def _lt_load(self):
        self._lt_loading = True
        n = self.lt_lang.currentData()
        t = self.lt_data.get(n)
        if t:
            self.lt_default.setChecked(False)
            self.lt_size.setValue(int(t[0]))
            self.lt_spaces.setChecked(bool(t[1]))
        else:
            self.lt_default.setChecked(True)
            size, sp = self.main.tab_settings(n) if n not in self.lt_data else (4, False)
            self.lt_size.setValue(size)
            self.lt_spaces.setChecked(sp)
        self.lt_size.setEnabled(not self.lt_default.isChecked())
        self.lt_spaces.setEnabled(not self.lt_default.isChecked())
        self._lt_loading = False

    def _lt_store(self, *_):
        if self._lt_loading:
            return
        n = self.lt_lang.currentData()
        self.lt_size.setEnabled(not self.lt_default.isChecked())
        self.lt_spaces.setEnabled(not self.lt_default.isChecked())
        if self.lt_default.isChecked():
            self.lt_data.pop(n, None)
        else:
            self.lt_data[n] = [self.lt_size.value(), self.lt_spaces.isChecked()]

    def apply_close(self):
        m = self.main
        old_loc = m.S["localization"]
        old_compact = m.S["lang_compact"]
        for key, get in self.getters:
            m.S[key] = get()
        m.S.save()
        if m.S["localization"] != old_loc or m.S["lang_compact"] != old_compact:
            m.i18n.load(m.S["localization"])
            for cid, a in m.actions.items():
                default = a.property("en_label")
            m.reload_menu_texts()
        m.apply_ui_settings()
        m.restyle_all()
        m.restart_backup_timer()
        self.accept()
