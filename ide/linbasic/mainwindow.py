"""Linpad++ main window: the Notepad++ frame (two views, menus, toolbar,
status bar, docking panels) and buffer lifecycle."""
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager

from PyQt6.QtCore import Qt, QTimer, QFileSystemWatcher, QByteArray, QSize, QUrl, QEvent
from PyQt6.QtGui import (QAction, QActionGroup, QIcon, QKeySequence, QDesktopServices, QColor,
                         QPalette, QGuiApplication)
from PyQt6.QtWidgets import (QMainWindow, QSplitter, QToolBar, QStatusBar, QLabel, QMenu,
                             QFileDialog, QMessageBox, QApplication, QDockWidget, QWidget,
                             QSystemTrayIcon, QPushButton)
from PyQt6.Qsci import QsciScintilla as S

from . import APP_NAME, VERSION, paths, settings, styles as stl, encodings_util as enc, keys
from .langs import LangDB, MENU_LANG, LANG_MENU, LEXERS
from .i18n import Localization
from .editor import Buffer, Editor
from .docview import EditView
from .npp_tables import MENUBAR, LANG_COMPACT, TRAY
from .cmd_edit import EditMixin
from .cmd_search import SearchMixin
from .cmd_view import ViewMixin
from .cmd_misc import MiscMixin
from .autocomplete import AutoCompleteMixin
from .npp_tables import DEFAULT_KEYS
from . import session as sess

TOOLBAR = [41001, 41002, 41006, 41007, 41003, 41004, 41010, 0, 42001, 42002, 42005, 0,
           42003, 42004, 0, 43001, 43003, 0, 44023, 44024, 0, 44035, 44036, 0,
           44022, 44019, 44020, 0, 46250, 44080, 44070, 44084, 44085, 0, 44097, 0,
           42018, 42019, 42021, 42032, 42025]
TB_ICON = {41001: "new", 41002: "open", 41006: "save", 41007: "saveall", 41003: "close",
           41004: "closeall", 41010: "print", 42001: "cut", 42002: "copy", 42005: "paste",
           42003: "undo", 42004: "redo", 43001: "find", 43003: "replace", 44023: "zoomin",
           44024: "zoomout", 44035: "syncv", 44036: "synch", 44022: "wrap", 44019: "allchars",
           44020: "indent", 46250: "udl", 44080: "docmap", 44070: "doclist", 44084: "funclist",
           44085: "workspace", 44097: "monitor", 42018: "record", 42019: "stop", 42021: "play",
           42032: "playmulti", 42025: "savemacro"}
CHECKABLE = {44034, 44032, 44009, 44011, 44025, 44026, 44130, 44131, 44019, 44020, 44041, 44027,
             44022, 44035, 44036, 42028, 44097, 44080, 44070, 44084, 44085, 44081, 44082, 44083,
             42051, 42052, 42033}
# File-menu extras that are built at runtime in Notepad++ (recent files block)
ID_RESTORE_CLOSED, ID_OPEN_ALL_RECENT, ID_EMPTY_RECENT = 41021, 41901, 41902
ID_MD_LANG = 46181


class MainWindow(QMainWindow, EditMixin, SearchMixin, ViewMixin, MiscMixin, AutoCompleteMixin):
    def __init__(self, opts):
        super().__init__()
        self.opts = opts
        self.S = settings.S
        paths.ensure_user_files()
        self.langdb = LangDB()
        self.i18n = Localization(self.S["localization"])
        self.styles = None
        self.load_theme()
        self.shortcut_file = keys.ShortcutsFile()
        self.all_buffers = []
        self.closed_history = []
        self.panels = {}
        self.docks = {}
        self.actions = {}
        self.find_dlg = None
        self.recording = False
        self.macro = []
        self.last_macro = None
        self.closing = False
        self.find_opts_last = None
        self.post_it = False
        self.dfm = False
        self._fullscreen = False
        self._pre_states = None
        self._smart_cache = None
        self.tray = None
        self.setWindowIcon(QIcon(paths.icon("linbasic.svg")))
        self.setAcceptDrops(True)

        # hidden loader view (Notepad++ keeps an invisible Scintilla for this)
        self.loader = Editor(self, -1)
        self.loader.hide()
        self.loader_blank = self.loader.SendScintilla(S.SCI_GETDOCPOINTER)
        self.loader.SendScintilla(S.SCI_ADDREFDOCUMENT, 0, self.loader_blank)
        self._blank = {}

        self.views = [EditView(self, 0), EditView(self, 1)]
        self.splitter = QSplitter(Qt.Orientation(self.S["split_orientation"]))
        self.splitter.setChildrenCollapsible(False)
        for v in self.views:
            self.splitter.addWidget(v)
            v.activated.connect(self.set_active_view)
            v.current_changed.connect(self.on_current_changed)
            v.tabs.close_requested.connect(lambda i, vv=v: self.close_buffer(vv.buffer_at(i), vv))
            v.tabs.middle_clicked.connect(lambda i, vv=v: self.close_buffer(vv.buffer_at(i), vv))
            v.tabs.double_clicked.connect(lambda i, vv=v: self.tab_double_clicked(vv, i))
            v.tabs.context.connect(lambda i, pos, vv=v: self.tab_context_menu(vv, i, pos))
            v.editor.files_dropped.connect(self.open_dropped)
            v.editor.context_requested.connect(self.editor_context_menu)
        self.views[1].hide()
        self.active_view = self.views[0]
        self.setCentralWidget(self.splitter)

        self.ac_init()
        self.build_actions()
        self.build_menus()
        self.build_toolbar()
        self.build_statusbar()
        self.build_incremental_bar()
        self.apply_shortcuts()
        self.apply_ui_settings()
        for v in self.views:
            v.editor.apply_view_settings(self.S)

        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.on_file_changed)
        self._check_timer = QTimer(self)
        self._check_timer.setSingleShot(True)
        self._check_timer.setInterval(200)
        self._check_timer.timeout.connect(self.check_modified_files)
        QGuiApplication.instance().applicationStateChanged.connect(self._app_state)
        self.backup_timer = QTimer(self)
        self.backup_timer.timeout.connect(self.snapshot_backup)
        self.restart_backup_timer()
        self.clip_history = []
        QApplication.clipboard().dataChanged.connect(self.on_clipboard_changed)
        self.restore_geometry()
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(lambda *_: self._system_scheme_tick())
        except AttributeError:
            pass
        self._scheme_timer = QTimer(self)
        self._scheme_timer.timeout.connect(self._system_scheme_tick)
        self._scheme_timer.start(5000)
        # LinBASIC support (compiler, run, help, SUBs)
        from . import qbide
        qbide.install(self)

    # ================================================================== theme
    def load_theme(self):
        name = self.S["theme"]
        path = None
        if name:
            for d in paths.theme_dirs()[::-1]:
                p = os.path.join(d, name)
                if os.path.exists(p):
                    path = p
                    break
        if path is None:
            path = paths.user_or_model("stylers.xml", "stylers.model.xml")
        self.styles = stl.load_styleset(path)
        self.styles.override = self.S.get("global_override", {}) or {}

    def ui_is_dark(self):
        m = self.S["dark_mode"]
        if m == "dark":
            return True
        if m == "system":
            return self.system_is_dark()
        return False

    def system_is_dark(self):
        """Desktop colour scheme: Qt's own hint, then the XDG portal / GNOME
        setting, then the GTK or KDE theme name."""
        try:
            sch = QGuiApplication.styleHints().colorScheme()
            if sch == Qt.ColorScheme.Dark:
                return True
            if sch == Qt.ColorScheme.Light:
                return False
        except AttributeError:
            pass
        env = {k: v for k, v in os.environ.items()}
        for k in ("LD_LIBRARY_PATH",):
            if os.environ.get("APPIMAGE"):
                orig = env.get(k + "_ORIG")
                if orig:
                    env[k] = orig
                else:
                    env.pop(k, None)

        def run(args):
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=1.5, env=env)
                return r.stdout.strip() if r.returncode == 0 else ""
            except Exception:   # missing tool, timeout, sandbox...
                return ""
        out = run(["gdbus", "call", "--session", "--dest", "org.freedesktop.portal.Desktop",
                   "--object-path", "/org/freedesktop/portal/desktop", "--method",
                   "org.freedesktop.portal.Settings.Read", "org.freedesktop.appearance", "color-scheme"])
        if out:
            import re as _re
            m = _re.search(r"uint32 (\d)", out)
            if m and m.group(1) in ("1", "2"):
                return m.group(1) == "1"
        out = run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"])
        if "dark" in out:
            return True
        if "light" in out:
            return False
        gtk = os.environ.get("GTK_THEME", "") or run(["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"])
        if gtk:
            return "dark" in gtk.lower()
        try:
            with open(os.path.expanduser("~/.config/kdeglobals"), encoding="utf-8", errors="ignore") as f:
                kde = f.read()
            import re as _re
            m = _re.search(r"^ColorScheme=(.*)$", kde, _re.M)
            if m:
                return "dark" in m.group(1).lower()
        except OSError:
            pass
        return False

    def apply_dark_mode(self):
        """Notepad++ switches the editor theme together with the UI mode and
        remembers one theme per mode (light: stylers.xml, dark: DarkModeDefault)."""
        dark = self.ui_is_dark()
        prev = getattr(self, "_dark_effective", None)
        self._dark_effective = dark
        if prev is not None and prev != dark:
            # remember the theme that was in use for the mode we are leaving
            self.S["dark_theme" if prev else "light_theme"] = self.S["theme"]
        target = self.S["dark_theme"] if dark else self.S["light_theme"]
        if prev is None:
            # startup: keep the theme last used unless it belongs to the other mode
            cur = self.S["theme"]
            target = cur
            if dark and cur == self.S["light_theme"] and self.S["dark_theme"] != cur:
                target = self.S["dark_theme"]
            elif not dark and cur == self.S["dark_theme"] and self.S["light_theme"] != cur:
                target = self.S["light_theme"]
        if target != self.S["theme"] or self.styles is None:
            self.S["theme"] = target
            self.load_theme()
            if self.all_buffers:
                self.restyle_all()
        self.apply_palette()
        self.panel_event("theme")

    def _system_scheme_tick(self):
        if self.S["dark_mode"] == "system" and self.system_is_dark() != getattr(self, "_dark_effective", None):
            self.apply_dark_mode()

    def apply_palette(self):
        app = QApplication.instance()
        dark = self.ui_is_dark()
        if dark:
            pal = QPalette()
            c = QColor
            pal.setColor(QPalette.ColorRole.Window, c("#202020"))
            pal.setColor(QPalette.ColorRole.WindowText, c("#E0E0E0"))
            pal.setColor(QPalette.ColorRole.Base, c("#202020"))
            pal.setColor(QPalette.ColorRole.AlternateBase, c("#2B2B2B"))
            pal.setColor(QPalette.ColorRole.Text, c("#E0E0E0"))
            pal.setColor(QPalette.ColorRole.Button, c("#383838"))
            pal.setColor(QPalette.ColorRole.ButtonText, c("#E0E0E0"))
            pal.setColor(QPalette.ColorRole.Highlight, c("#404080"))
            pal.setColor(QPalette.ColorRole.HighlightedText, c("#FFFFFF"))
            pal.setColor(QPalette.ColorRole.ToolTipBase, c("#383838"))
            pal.setColor(QPalette.ColorRole.ToolTipText, c("#E0E0E0"))
            pal.setColor(QPalette.ColorRole.PlaceholderText, c("#808080"))
            pal.setColor(QPalette.ColorRole.Link, c("#6FA8FF"))
            for role, col in ((QPalette.ColorRole.Light, "#505050"), (QPalette.ColorRole.Midlight, "#404040"),
                              (QPalette.ColorRole.Mid, "#303030"), (QPalette.ColorRole.Dark, "#181818"),
                              (QPalette.ColorRole.Shadow, "#000000")):
                pal.setColor(role, c(col))
            for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
                pal.setColor(QPalette.ColorGroup.Disabled, role, c("#707070"))
            app.setPalette(pal)
        else:
            pal = QPalette()
            c = QColor
            for role, col in ((QPalette.ColorRole.Window, "#EFEFEF"), (QPalette.ColorRole.WindowText, "#000000"),
                              (QPalette.ColorRole.Base, "#FFFFFF"), (QPalette.ColorRole.AlternateBase, "#F7F7F7"),
                              (QPalette.ColorRole.Text, "#000000"), (QPalette.ColorRole.Button, "#EFEFEF"),
                              (QPalette.ColorRole.ButtonText, "#000000"), (QPalette.ColorRole.Highlight, "#308CC6"),
                              (QPalette.ColorRole.HighlightedText, "#FFFFFF"), (QPalette.ColorRole.ToolTipBase, "#FFFFDC"),
                              (QPalette.ColorRole.ToolTipText, "#000000"), (QPalette.ColorRole.PlaceholderText, "#808080"),
                              (QPalette.ColorRole.Link, "#0000FF"), (QPalette.ColorRole.Light, "#FFFFFF"),
                              (QPalette.ColorRole.Midlight, "#CACACA"), (QPalette.ColorRole.Mid, "#B8B8B8"),
                              (QPalette.ColorRole.Dark, "#9F9F9F"), (QPalette.ColorRole.Shadow, "#767676")):
                pal.setColor(role, c(col))
            for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
                pal.setColor(QPalette.ColorGroup.Disabled, role, c("#A0A0A0"))
            app.setPalette(pal)
        for v in self.views:
            tb = v.tabs
            if dark:
                tb.bar_bg, tb.active_bg, tb.active_fg = QColor("#202020"), QColor("#3A3A3A"), QColor("#E0E0E0")
                tb.inactive_bg, tb.inactive_fg = QColor("#2A2A2A"), QColor("#C0C0C0")
                cols = ["Tab color dark mode %d" % i for i in range(1, 6)]
            else:
                tb.bar_bg, tb.active_bg, tb.active_fg = QColor("#F0F0F0"), QColor("#FFFFFF"), QColor("#000000")
                tb.inactive_bg, tb.inactive_fg = QColor("#DCDCDC"), QColor("#606060")
                cols = ["Tab color %d" % i for i in range(1, 6)]
            tb.tab_colors = [self.styles.gbg(n, QColor("#CCCCCC")) for n in cols]
            tb.focus_color = self.styles.gfg("Active tab focused indicator", QColor("#FAAA3C"))
            tb.unfocus_color = self.styles.gfg("Active tab unfocused indicator", QColor("#FFCAB0"))
            tb.update()
        self.refresh_toolbar_icons()

    # ================================================================ actions
    def tr_cmd(self, cid, default):
        return self.i18n.cmd(cid, default)

    def build_actions(self):
        self.lang_group = QActionGroup(self)
        self.enc_group = QActionGroup(self)
        self.eol_group = QActionGroup(self)

        def walk(items):
            for it in items:
                if it[0] == "cmd":
                    self._make_action(it[1], it[2])
                elif it[0] == "sub":
                    walk(it[3])
        for _, _, items in MENUBAR:
            walk(items)
        walk(LANG_COMPACT)
        self._make_action(ID_RESTORE_CLOSED, "Restore Recent Closed File")
        self._make_action(ID_OPEN_ALL_RECENT, "Open All Recent Files")
        self._make_action(ID_EMPTY_RECENT, "Empty Recent Files List")
        self._make_action(ID_MD_LANG, "Markdown (preinstalled)")
        for cid, label in ((50003, "Switch to Previous Document"), (50004, "Switch to Next Document"),
                           (50005, "Toggle Macro Recording")):
            self._make_action(cid, label)
        for cid, a in self.actions.items():
            if cid in MENU_LANG or cid == 46180:
                a.setCheckable(True)
                self.lang_group.addAction(a)
            elif 45004 <= cid <= 45008 or 45020 <= cid <= 45068:
                a.setCheckable(True)
                self.enc_group.addAction(a)
            elif cid in (45001, 45002, 45003):
                a.setCheckable(True)
                self.eol_group.addAction(a)
            elif cid in CHECKABLE:
                a.setCheckable(True)
        self.linux_labels()

    def linux_labels(self):
        # Notepad++ has no system-wide Windows equivalents for these on Linux
        self.actions[44102].setText("&Chromium")
        self.actions[44103].setText("&Default browser")
        self.actions[42033].setText(self.actions[42033].text().replace("in Windows", "(file permission)"))
        self.actions[41019].setText("File Manager")
        self.actions[41020].setText("Terminal")
        self.actions[41027].setText("PowerShell (pwsh)")
        self.actions[41016].setText("Move to &Trash")
        for cid in (42026, 42027):
            self.actions[cid].setEnabled(False)
            self.actions[cid].setToolTip("Bidirectional text needs Scintilla 4+; not available in this build")

    def _make_action(self, cid, label):
        if cid in self.actions:
            return self.actions[cid]
        a = QAction(self.tr_cmd(cid, label), self)
        a.setData(cid)
        a.setProperty("en_label", label)
        a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        a.triggered.connect(lambda checked=False, c=cid: self.run_command(c))
        self.actions[cid] = a
        self.addAction(a)
        return a

    def reload_menu_texts(self):
        for cid, a in self.actions.items():
            a.setText(self.tr_cmd(cid, a.property("en_label") or a.text()))
        self.linux_labels()
        self.build_menus()

    def on_clipboard_changed(self):
        t = QApplication.clipboard().text()
        if not t or (self.clip_history and self.clip_history[0] == t):
            return
        if t in self.clip_history:
            self.clip_history.remove(t)
        self.clip_history.insert(0, t)
        del self.clip_history[30:]
        self.panel_event("clipboard")

    def build_menus(self):
        mb = self.menuBar()
        mb.clear()
        self.menus = {}
        for mid, label, items in MENUBAR:
            title = self.i18n.menu(mid, label)
            m = mb.addMenu(title)
            self.menus[mid] = m
            if mid == "language":
                self._fill_lang_menu(m)
            else:
                self._fill_menu(m, items)
            if mid == "file":
                self._insert_recent_block(m)
            if mid == "macro":
                self.macro_static = list(m.actions())
                m.aboutToShow.connect(self.refresh_macro_menu)
            if mid == "run":
                self.run_static = list(m.actions())
                m.aboutToShow.connect(self.refresh_run_menu)
            if mid == "Plugins":
                self._fill_plugins_menu(m)
            if mid == "Window":
                self.window_static = list(m.actions())
                m.aboutToShow.connect(self.refresh_window_menu)
            if mid == "edit":
                m.aboutToShow.connect(self.update_edit_menu)
        self.menus["file"].aboutToShow.connect(self.refresh_recent_menu)
        self.menus["view"].aboutToShow.connect(self.sync_check_states)
        self.menus["encoding"].aboutToShow.connect(self.sync_check_states)
        self.menus["language"].aboutToShow.connect(self.sync_check_states)

    def _fill_menu(self, menu, items):
        for it in items:
            if it[0] == "sep":
                menu.addSeparator()
            elif it[0] == "cmd":
                menu.addAction(self.actions[it[1]])
            else:
                sub = menu.addMenu(self.i18n.sub(it[1], it[2]))
                self._fill_menu(sub, it[3])

    def _fill_lang_menu(self, m):
        m.clear()
        items = None
        for mid, label, its in MENUBAR:
            if mid == "language":
                items = its
        src = LANG_COMPACT if self.S["lang_compact"] else items
        disabled = set(self.S["disabled_langs"])
        for it in src:
            if it[0] == "sep":
                m.addSeparator()
            elif it[0] == "cmd":
                if MENU_LANG.get(it[1]) in disabled:
                    continue
                m.addAction(self.actions[it[1]])
            else:
                sub = m.addMenu(self.i18n.sub(it[1], it[2]))
                for x in it[3]:
                    if x[0] == "cmd" and MENU_LANG.get(x[1]) not in disabled:
                        sub.addAction(self.actions[x[1]])
                if it[1] == "language-userDefinedLanguage" or it[2] == "User Defined Language":
                    sub.addSeparator()
                    sub.addAction(self.actions[ID_MD_LANG])
        if not self.S["lang_compact"]:
            acts = m.actions()
            udl = self.actions[46180]
            m.insertAction(udl, self.actions[ID_MD_LANG])

    def _insert_recent_block(self, m):
        exit_act = self.actions[41011]
        self.recent_sep = QAction(self)
        self.recent_sep.setSeparator(True)
        m.insertAction(exit_act, self.actions[ID_RESTORE_CLOSED])
        m.insertAction(exit_act, self.actions[ID_OPEN_ALL_RECENT])
        m.insertAction(exit_act, self.actions[ID_EMPTY_RECENT])
        m.insertAction(exit_act, self.recent_sep)
        self.recent_actions = []
        self.recent_submenu = None

    def _fill_plugins_menu(self, m):
        from . import plugins_builtin
        first = m.actions()[0] if m.actions() else None
        for title, cmds in plugins_builtin.menu_spec():
            sub = QMenu(title, m)
            for name, fn in cmds:
                if name is None:
                    sub.addSeparator()
                else:
                    a = sub.addAction(name)
                    a.triggered.connect(lambda checked=False, f=fn: f(self))
            m.insertMenu(first, sub)
        if first is not None:
            m.insertSeparator(first)

    def build_toolbar(self):
        self.toolbar = QToolBar("Toolbar")
        self.toolbar.setObjectName("toolbar")
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        for cid in TOOLBAR:
            if cid == 0:
                self.toolbar.addSeparator()
            else:
                a = self.actions[cid]
                self.toolbar.addAction(a)
        self.refresh_toolbar_icons()

    def refresh_toolbar_icons(self):
        if not hasattr(self, "toolbar"):
            return
        large = self.S["toolbar_icons"] == "large"
        sz = 24 if large else 16
        theme = "dark" if self.ui_is_dark() else "light"
        self.toolbar.setIconSize(QSize(sz, sz))
        for cid, name in TB_ICON.items():
            ic = QIcon()
            for s in (16, 24, 32):
                ic.addFile(paths.icon("%s/%s_%d.png" % (theme, name, s)), QSize(s, s))
                dis = paths.icon("%s/%s_dis_%d.png" % (theme, name, s))
                if os.path.exists(dis):
                    ic.addFile(dis, QSize(s, s), QIcon.Mode.Disabled)
            self.actions[cid].setIcon(ic)

    def build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.sb_lang = QLabel()
        self.sb_len = QLabel()
        self.sb_pos = QLabel()
        self.sb_eol = QLabel()
        self.sb_enc = QLabel()
        self.sb_ins = QLabel("INS")
        sb.addWidget(self.sb_lang, 3)
        for w, stretch in ((self.sb_len, 2), (self.sb_pos, 3), (self.sb_eol, 1), (self.sb_enc, 1), (self.sb_ins, 0)):
            w.setFrameShape(QLabel.Shape.StyledPanel)
            w.setContentsMargins(4, 0, 4, 0)
            sb.addPermanentWidget(w, stretch)
        self.sb_pos.mouseDoubleClickEvent = lambda e: self.run_command(43004)
        self.sb_eol.mouseDoubleClickEvent = lambda e: self.menus["edit"].popup(self.cursor().pos())
        self.sb_enc.mouseDoubleClickEvent = lambda e: self.menus["encoding"].popup(self.cursor().pos())
        self.sb_lang.mouseDoubleClickEvent = lambda e: self.menus["language"].popup(self.cursor().pos())
        self.sb_ins.mouseDoubleClickEvent = lambda e: self.editor().SendScintilla(S.SCI_EDITTOGGLEOVERTYPE)

    def apply_shortcuts(self):
        taken = set()
        for cid, a in self.actions.items():
            if cid in self.shortcut_file.internal:
                seqs = self.shortcut_file.internal[cid]
            else:
                seqs = keys.default_seqs(cid)
            a.setShortcuts(seqs)
            for s_ in seqs:
                if not s_.isEmpty():
                    taken.add(s_[0].toCombined())
        # free those keys inside Scintilla so window shortcuts win
        for ed in [v.editor for v in self.views]:
            for cmd in ed.standardCommands().commands():
                if cmd.key() and cmd.key() in taken:
                    cmd.setKey(0)
                if cmd.alternateKey() and cmd.alternateKey() in taken:
                    cmd.setAlternateKey(0)
                seqs = self.shortcut_file.scintilla.get(cmd.command())
                if seqs is not None:
                    cmd.setKey(seqs[0][0].toCombined() if seqs and not seqs[0].isEmpty() else 0)
        self.dynamic_shortcuts()

    def dynamic_shortcuts(self):
        for a in getattr(self, "_dyn_actions", []):
            self.removeAction(a)
        self._dyn_actions = []
        for m in self.shortcut_file.macros:
            if not m["seq"].isEmpty():
                a = QAction(self)
                a.setShortcut(m["seq"])
                a.triggered.connect(lambda checked=False, mm=m: self.play_macro(mm["actions"]))
                self.addAction(a)
                self._dyn_actions.append(a)
        for c in self.shortcut_file.commands:
            if not c["seq"].isEmpty():
                a = QAction(self)
                a.setShortcut(c["seq"])
                a.triggered.connect(lambda checked=False, cc=c: self.run_user_command(cc["cmd"]))
                self.addAction(a)
                self._dyn_actions.append(a)

    def apply_ui_settings(self):
        self.toolbar.setVisible(not self.S["toolbar_hidden"])
        self.statusBar().setVisible(not self.S["statusbar_hidden"])
        self.menuBar().setVisible(not self.S["menubar_hidden"])
        for v in self.views:
            v.tabs.setVisible(not self.S["tabbar_hidden"])
            v.tabs.show_close = self.S["tab_close_button"]
            v.tabs.reduce = self.S["tab_reduce"]
            v.tabs.max_len = self.S["tab_max_len"]
            v.tabs.setMovable(not self.S["tab_lock"])
            v.tabs.updateGeometry()
            v.tabs.update()
        self.apply_dark_mode()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(self.S["always_on_top"]))
        if self.S["minimize_to_tray"] or self.S["close_to_tray"]:
            self.ensure_tray()

    # ================================================================ buffers
    def editor(self):
        return self.active_view.editor

    def buf(self):
        return self.active_view.current

    def other_view(self, view=None):
        view = view or self.active_view
        return self.views[1 - view.index]

    def set_active_view(self, view):
        if self.active_view is view:
            return
        self.active_view = view
        for v in self.views:
            v.tabs.update()
        if view.current is not None:
            self.on_current_changed(view, view.current)

    def empty_ptr(self, view):
        if view.index not in self._blank:
            p = self.loader.SendScintilla(S.SCI_CREATEDOCUMENT, 0, 0)
            self._blank[view.index] = p
        return self._blank[view.index]

    @contextmanager
    def doc_editor(self, buf):
        for v in self.views:
            if v.current is buf and v.editor.buffer is buf:
                yield v.editor
                return
        L = self.loader
        L.SendScintilla(S.SCI_SETDOCPOINTER, 0, buf.ptr)
        L.buffer = buf
        try:
            yield L
        finally:
            dirty = bool(L.SendScintilla(S.SCI_GETMODIFY)) or buf.force_dirty
            L.SendScintilla(S.SCI_SETDOCPOINTER, 0, self.loader_blank)
            L.buffer = None
            if dirty != buf.dirty:
                buf.dirty = dirty
                self.refresh_buffer_ui(buf)

    def create_doc(self, data=b"", eol=None, lang="normal"):
        L = self.loader
        ptr = L.SendScintilla(S.SCI_CREATEDOCUMENT, 0, 0)
        L.SendScintilla(S.SCI_SETDOCPOINTER, 0, ptr)
        L.SendScintilla(S.SCI_SETCODEPAGE, 65001)
        L.SendScintilla(S.SCI_SETUNDOCOLLECTION, False)
        if data:
            L.SendScintilla(S.SCI_APPENDTEXT, len(data), data)
        L.SendScintilla(S.SCI_SETUNDOCOLLECTION, True)
        L.SendScintilla(S.SCI_EMPTYUNDOBUFFER)
        L.SendScintilla(S.SCI_SETSAVEPOINT)
        L.SendScintilla(S.SCI_SETEOLMODE, self.S["new_eol"] if eol is None else eol)
        self._setup_lexer(L, lang)
        L.SendScintilla(S.SCI_SETDOCPOINTER, 0, self.loader_blank)
        return ptr

    def _setup_lexer(self, ed, lang):
        lg = self.langdb.get(lang)
        snd = ed.SendScintilla
        snd(S.SCI_SETLEXERLANGUAGE, 0, lg.lexer.encode())
        for k, v in self.langdb.props(lang).items():
            snd(S.SCI_SETPROPERTY, k.encode(), v.encode())
        for i in range(9):
            snd(S.SCI_SETKEYWORDS, i, b"")
        for i, words in self.langdb.keyword_lists(lang, self.styles).items():
            snd(S.SCI_SETKEYWORDS, i, words.encode("utf-8"))

    def register(self, buf):
        self.all_buffers.append(buf)
        if buf.path:
            self.watch(buf.path)

    def new_document(self, view=None, text="", lang=None):
        view = view or self.active_view
        lang = lang or self.S["new_lang"]
        ptr = self.create_doc(text.encode("utf-8"), lang=lang)
        b = Buffer(ptr)
        b.lang = lang
        b.eol = self.S["new_eol"]
        b.encoding = self.S["new_encoding"]
        self.register(b)
        self.show_view(view)
        view.add(b)
        self.set_active_view(view)
        view.editor.setFocus()
        return b

    def find_buffer(self, path):
        rp = os.path.realpath(path)
        for b in self.all_buffers:
            if b.path and os.path.realpath(b.path) == rp:
                return b
        return None

    def views_of(self, buf):
        return [v for v in self.views if buf in v.buffers]

    def is_pristine(self, buf):
        if buf is None or not buf.untitled or buf.dirty:
            return False
        with self.doc_editor(buf) as e:
            return e.length() == 0 and not e.SendScintilla(S.SCI_CANUNDO)

    def read_file(self, path, encoding=None):
        with open(path, "rb") as f:
            data = f.read()
        if encoding:
            text = enc.decode(data, encoding, self.S)
            return encoding, text, data
        if path.lower().endswith(".nfo"):
            return "cp437", data.decode("cp437", errors="replace"), data
        e, text = enc.detect(data, self.S) if self.S["autodetect_encoding"] or True else ("utf8", data.decode("utf-8", "replace"))
        if e == "ansi" and self.S["apply_utf8_to_ansi"]:
            e = "utf8"
        return e, text, data

    @staticmethod
    def detect_eol(text):
        i = text.find("\n")
        j = text.find("\r")
        if j >= 0 and (i < 0 or j < i):
            return S.SC_EOL_CRLF if text[j:j + 2] == "\r\n" else S.SC_EOL_CR
        if i >= 0:
            return S.SC_EOL_LF
        return None

    def open_file(self, path, view=None, activate=True, readonly=False, line=None, col=None,
                  pos=None, encoding=None, lang=None, quiet=False):
        path = os.path.abspath(os.path.expanduser(path))
        existing = self.find_buffer(path)
        if existing is not None:
            vs = self.views_of(existing)
            v = vs[0] if vs else (view or self.active_view)
            if not vs:
                v.add(existing)
            if activate:
                v.activate(existing)
                self.set_active_view(v)
            self._goto_after_open(v.editor, line, col, pos)
            return existing
        if os.path.isdir(path):
            self.open_folder_as_workspace(path)
            return None
        if not os.path.exists(path):
            if quiet:
                return None
            r = QMessageBox.question(self, "Create new file",
                                     '"%s" doesn\'t exist. Create it?' % path)
            if r != QMessageBox.StandardButton.Yes:
                return None
            try:
                open(path, "ab").close()
            except OSError as ex:
                QMessageBox.warning(self, APP_NAME, "Cannot create file:\n%s" % ex)
                return None
        try:
            size = os.path.getsize(path)
            e, text, raw = self.read_file(path, encoding)
        except OSError as ex:
            if not quiet:
                QMessageBox.warning(self, APP_NAME, "Cannot open file \"%s\".\n%s" % (path, ex))
            return None
        view = view or self.active_view
        cur = view.current
        replace_pristine = cur is not None and self.is_pristine(cur) and len(view.buffers) == 1
        lg = lang or self.langdb.detect(path, raw[:256]) or "normal"
        large = self.S["large_file_restrict"] and size > self.S["large_file_mb"] * 1024 * 1024
        if large:
            lg = "normal"
        eol = self.detect_eol(text[:65536])
        data = text.encode("utf-8", errors="surrogatepass")
        ptr = self.create_doc(data, eol=self.S["new_eol"] if eol is None else eol, lang=lg)
        b = Buffer(ptr, path=path)
        b.encoding = e
        b.eol = self.S["new_eol"] if eol is None else eol
        b.lang = lg
        b.large = large
        b.mtime = os.path.getmtime(path)
        b.file_readonly = not os.access(path, os.W_OK)
        b.user_readonly = readonly
        self.register(b)
        if b.readonly():
            with self.doc_editor(b) as ed:
                ed.SendScintilla(S.SCI_SETREADONLY, True)
        self.show_view(view)
        view.add(b, activate=activate)
        if activate:
            self.set_active_view(view)
        if replace_pristine:
            self.close_buffer(cur, view, force=True)
        self.add_recent(path)
        self._goto_after_open(view.editor, line, col, pos)
        if activate:
            view.editor.setFocus()
        return b

    def _goto_after_open(self, ed, line, col, pos):
        if pos is not None:
            ed.goto_pos(max(0, pos))
        elif line is not None:
            ed.goto_line(max(0, line - 1))
            if col is not None:
                p = ed.SendScintilla(S.SCI_FINDCOLUMN, max(0, line - 1), max(0, col - 1))
                ed.goto_pos(p)

    def open_dropped(self, files):
        for f in files:
            if os.path.isdir(f):
                self.open_folder_as_workspace(f)
            else:
                self.open_file(f)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.open_dropped([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def show_view(self, view):
        if not view.isVisible():
            view.show()
            if view.index == 1 and len(self.splitter.sizes()) == 2:
                tot = sum(self.splitter.sizes()) or 800
                self.splitter.setSizes([tot // 2, tot - tot // 2])

    def mru_pick(self, view, removed_index):
        if self.S["docswitcher_mru"] and view.buffers:
            return max(view.buffers, key=lambda b: b.last_access)
        return view.buffers[min(removed_index, len(view.buffers) - 1)]

    def confirm_save(self, buf, multi=False):
        """Return 'yes', 'no', 'cancel', 'yesall', 'noall'."""
        box = QMessageBox(self)
        box.setWindowTitle("Save")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText('Save file "%s" ?' % buf.full_name())
        yes = box.addButton("&Yes", QMessageBox.ButtonRole.YesRole)
        no = box.addButton("&No", QMessageBox.ButtonRole.NoRole)
        cancel = box.addButton("&Cancel", QMessageBox.ButtonRole.RejectRole)
        yall = nall = None
        if multi:
            yall = box.addButton("Yes to &all", QMessageBox.ButtonRole.YesRole)
            nall = box.addButton("N&o to all", QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(yes)
        box.exec()
        c = box.clickedButton()
        return {yes: "yes", no: "no", cancel: "cancel", yall: "yesall", nall: "noall"}.get(c, "cancel")

    def close_buffer(self, buf, view=None, force=False, ask=True):
        if buf is None:
            return True
        view = view or (self.views_of(buf) or [self.active_view])[0]
        others = [v for v in self.views_of(buf) if v is not view]
        if others:
            view.remove(buf)
            self.after_view_change(view)
            return True
        if buf.dirty and not force and ask:
            view.activate(buf)
            r = self.confirm_save(buf)
            if r == "cancel":
                return False
            if r == "yes" and not self.save_buffer(buf):
                return False
        if buf.path:
            self.unwatch(buf.path)
            self.closed_history.append(buf.path)
            self.closed_history = self.closed_history[-30:]
        if buf.backup_path and os.path.exists(buf.backup_path):
            try:
                os.remove(buf.backup_path)
            except OSError:
                pass
        view.remove(buf)
        if buf in self.all_buffers:
            self.all_buffers.remove(buf)
        self.loader.SendScintilla(S.SCI_RELEASEDOCUMENT, 0, buf.ptr)
        self.after_view_change(view)
        self.panel_event("buffers")
        return True

    def after_view_change(self, view):
        if self.closing:
            return
        if not view.buffers:
            if view.index == 1:
                view.hide()
                self.set_active_view(self.views[0])
                self.views[0].editor.setFocus()
            elif not self.views[1].buffers:
                if self.S["tab_exit_on_last"]:
                    QTimer.singleShot(0, self.close)
                else:
                    self.new_document(view)
            else:
                # move everything from the sub view back like Notepad++ does
                for b in list(self.views[1].buffers):
                    self.views[1].remove(b)
                    view.add(b, activate=False)
                self.views[1].hide()
                view.activate(view.buffers[0])
                self.set_active_view(view)
        self.update_title()
        self.update_status()

    def save_buffer(self, buf, path=None, copy_only=False):
        target = path or buf.path
        if target is None:
            return self.save_buffer_as(buf)
        with self.doc_editor(buf) as e:
            raw = e.get_bytes()
        text = raw.decode("utf-8", errors="surrogateescape")
        encoding = buf.encoding
        if not enc.can_encode(text, encoding, self.S):
            r = QMessageBox.question(
                self, "Save",
                "The document contains characters that can't be saved in %s.\n"
                "Save as UTF-8 instead?" % enc.display_name(encoding),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return False
            if r == QMessageBox.StandardButton.Yes:
                encoding = "utf8"
                if not copy_only:
                    buf.encoding = "utf8"
        try:
            data = raw if encoding == "utf8" else enc.encode(text, encoding, self.S)
        except LookupError:
            data = raw
        if self.S["backup_mode"] != "none" and os.path.exists(target) and not copy_only:
            self.backup_on_save(target)
        try:
            if buf.path:
                self.unwatch(buf.path)
            with open(target, "wb") as f:
                f.write(data)
        except OSError as ex:
            QMessageBox.warning(self, "Save failed",
                                "Please check whether if this file is opened in another program.\n\n%s" % ex)
            if buf.path:
                self.watch(buf.path)
            return False
        if copy_only:
            if buf.path:
                self.watch(buf.path)
            return True
        old_path = buf.path
        buf.path = os.path.abspath(target)
        buf.mtime = os.path.getmtime(target)
        buf.missing = False
        buf.file_readonly = not os.access(target, os.W_OK)
        self.watch(buf.path)
        with self.doc_editor(buf) as e:
            e.SendScintilla(S.SCI_SETSAVEPOINT)
            self.change_history_saved(e)
        buf.dirty = False
        buf.force_dirty = False
        if old_path != buf.path:
            if not buf.lang_forced:
                lg = self.langdb.detect(buf.path, data[:256])
                if lg and lg != buf.lang:
                    self.set_buffer_lang(buf, lg)
            self.add_recent(buf.path)
        if buf.backup_path and os.path.exists(buf.backup_path):
            try:
                os.remove(buf.backup_path)
            except OSError:
                pass
            buf.backup_path = None
        self.refresh_buffer_ui(buf)
        self.panel_event("buffers")
        return True

    def save_dialog_dir(self, buf=None):
        mode = self.S["open_dir_mode"]
        buf = buf or self.buf()
        if mode == "follow" and buf is not None and buf.path:
            return os.path.dirname(buf.path)
        if mode == "custom" and self.S["open_dir_custom"]:
            return self.S["open_dir_custom"]
        return self.S["last_dir"] or os.path.expanduser("~")

    def file_filters(self):
        flt = ["All types (*)"]
        for name in sorted(self.langdb.menu_langs()):
            lg = self.langdb.get(name)
            if lg.ext:
                flt.append("%s (%s)" % (lg.desc, " ".join("*." + e for e in lg.ext)))
        return ";;".join(flt)

    def save_buffer_as(self, buf, copy_only=False):
        start = buf.path or os.path.join(self.save_dialog_dir(buf), buf.title)
        path, _ = QFileDialog.getSaveFileName(self, "Save a Copy As" if copy_only else "Save As",
                                              start, self.file_filters())
        if not path:
            return False
        self.S["last_dir"] = os.path.dirname(path)
        other = self.find_buffer(path)
        if other is not None and other is not buf and not copy_only:
            QMessageBox.warning(self, "Save failed", "The file is already opened in %s." % APP_NAME)
            return False
        return self.save_buffer(buf, path, copy_only=copy_only)

    def backup_on_save(self, target):
        d = self.S["backup_dir"] or os.path.join(os.path.dirname(target), "nppBackup")
        try:
            os.makedirs(d, exist_ok=True)
            name = os.path.basename(target)
            if self.S["backup_mode"] == "verbose":
                name += "." + time.strftime("%Y-%m-%d_%H%M%S") + ".bak"
            else:
                name += ".bak"
            shutil.copy2(target, os.path.join(d, name))
        except OSError:
            pass

    def reload_buffer(self, buf, encoding=None, ask=True):
        if buf.path is None or not os.path.exists(buf.path):
            return
        if buf.dirty and ask:
            r = QMessageBox.question(self, "Reload",
                                     'Are you sure you want to reload the current file and lose the changes made in %s?' % APP_NAME)
            if r != QMessageBox.StandardButton.Yes:
                return
        try:
            e, text, raw = self.read_file(buf.path, encoding)
        except OSError:
            return
        data = text.encode("utf-8", errors="surrogatepass")
        with self.doc_editor(buf) as ed:
            ro = ed.SendScintilla(S.SCI_GETREADONLY)
            ed.SendScintilla(S.SCI_SETREADONLY, False)
            first = ed.first_visible_doc_line()
            caret = ed.pos()
            ed.SendScintilla(S.SCI_CLEARALL)
            if data:
                ed.SendScintilla(S.SCI_APPENDTEXT, len(data), data)
            ed.SendScintilla(S.SCI_EMPTYUNDOBUFFER)
            ed.SendScintilla(S.SCI_SETSAVEPOINT)
            ed.SendScintilla(S.SCI_MARKERDELETEALL, stl.MARK_CH_MODIFIED)
            ed.SendScintilla(S.SCI_MARKERDELETEALL, stl.MARK_CH_SAVED)
            ed.SendScintilla(S.SCI_SETREADONLY, ro)
            if buf.monitoring or (self.S["autodetect_scroll_end"] and not ask):
                ed.SendScintilla(S.SCI_DOCUMENTEND)
            elif ed is not self.loader:
                ed.SendScintilla(S.SCI_GOTOPOS, min(caret, ed.length()))
                ed.SendScintilla(S.SCI_SETFIRSTVISIBLELINE, first)
        buf.encoding = e
        buf.mtime = os.path.getmtime(buf.path)
        buf.dirty = buf.force_dirty = False
        self.refresh_buffer_ui(buf)

    # ============================================================ monitoring
    def watch(self, path):
        if path and os.path.exists(path) and path not in self.watcher.files():
            self.watcher.addPath(path)

    def unwatch(self, path):
        if path and path in self.watcher.files():
            self.watcher.removePath(path)

    def on_file_changed(self, path):
        for b in self.all_buffers:
            if b.path == path:
                b.pending_reload = True
        if path not in self.watcher.files() and os.path.exists(path):
            self.watcher.addPath(path)
        if any(b.monitoring for b in self.all_buffers if b.path == path) or self.isActiveWindow():
            self._check_timer.start()

    def _app_state(self, state):
        if state == Qt.ApplicationState.ApplicationActive:
            self._check_timer.start()

    def check_modified_files(self):
        mode = self.S["file_autodetect"]
        for b in list(self.all_buffers):
            if not b.path:
                continue
            exists = os.path.exists(b.path)
            if not exists:
                if not b.missing:
                    b.missing = True
                    if mode == "disabled":
                        continue
                    vs = self.views_of(b)
                    if vs:
                        vs[0].activate(b)
                    r = QMessageBox.question(self, "Keep non existing file",
                                             'The file "%s" doesn\'t exist anymore.\nKeep this file in editor?' % b.path)
                    if r == QMessageBox.StandardButton.No:
                        self.close_buffer(b, force=True)
                    else:
                        b.dirty = b.force_dirty = True
                        self.refresh_buffer_ui(b)
                continue
            b.missing = False
            try:
                mt = os.path.getmtime(b.path)
            except OSError:
                continue
            if b.mtime is not None and mt != b.mtime:
                b.pending_reload = False
                if b.monitoring:
                    b.mtime = mt
                    self.reload_buffer(b, b.encoding, ask=False)
                    continue
                if mode == "disabled":
                    b.mtime = mt
                    continue
                if mode == "silent" and not b.dirty:
                    b.mtime = mt
                    self.reload_buffer(b, None, ask=False)
                    continue
                b.mtime = mt
                vs = self.views_of(b)
                if vs:
                    vs[0].activate(b)
                    self.set_active_view(vs[0])
                msg = '"%s"\n\nThis file has been modified by another program.\nDo you want to reload it%s?' % (
                    b.path, " and lose the changes made in %s" % APP_NAME if b.dirty else "")
                r = QMessageBox.question(self, "Reload", msg)
                if r == QMessageBox.StandardButton.Yes:
                    self.reload_buffer(b, None, ask=False)

    # ================================================================ recent
    def add_recent(self, path):
        lst = [p for p in self.S["recent_files"] if p != path]
        lst.insert(0, path)
        self.S["recent_files"] = lst[: max(0, self.S["recent_max"])]

    def refresh_recent_menu(self):
        m = self.menus["file"]
        for a in self.recent_actions:
            m.removeAction(a)
        self.recent_actions = []
        if self.recent_submenu is not None:
            m.removeAction(self.recent_submenu.menuAction())
            self.recent_submenu = None
        lst = [p for p in self.S["recent_files"] if not self.find_buffer(p)]
        if not self.S["recent_dont_check"]:
            lst = [p for p in lst if os.path.exists(p)]
        target = m
        before = self.recent_sep
        if self.S["recent_submenu"] and lst:
            self.recent_submenu = QMenu(self.i18n.sub("file-recentFiles", "&Recent Files"), m)
            m.insertMenu(self.actions[ID_RESTORE_CLOSED], self.recent_submenu)
            target = self.recent_submenu
            before = None
        for i, p in enumerate(lst):
            label = os.path.basename(p) if self.S["recent_display"] == "name" else p
            if len(label) > self.S["recent_maxlen"]:
                label = "…" + label[-self.S["recent_maxlen"]:]
            a = QAction("&%d: %s" % (i + 1, label.replace("&", "&&")) if i < 9 else label.replace("&", "&&"), m)
            a.triggered.connect(lambda checked=False, pp=p: self.open_file(pp))
            if before is not None:
                target.insertAction(before, a)
                self.recent_actions.append(a)
            else:
                target.addAction(a)
        self.actions[ID_RESTORE_CLOSED].setEnabled(bool(self.closed_history))
        self.actions[ID_OPEN_ALL_RECENT].setEnabled(bool(lst))
        self.actions[ID_EMPTY_RECENT].setEnabled(bool(self.S["recent_files"]))

    # ============================================================ UI refresh
    def apply_buffer_to_editor(self, e, buf):
        self.styles.apply(e, self.langdb, buf.lang, self.S)
        size, spaces = self.tab_settings(buf.lang)
        e.SendScintilla(S.SCI_SETTABWIDTH, size)
        e.SendScintilla(S.SCI_SETINDENT, 0)
        e.SendScintilla(S.SCI_SETUSETABS, not spaces)
        e.SendScintilla(S.SCI_SETBACKSPACEUNINDENTS, self.S["backspace_unindent"])
        e.SendScintilla(S.SCI_SETTABINDENTS, True)
        wc = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" + (self.S["extra_word_chars"] or "")
        e.SendScintilla(S.SCI_SETWORDCHARS, 0, wc.encode("utf-8"))
        e.update_linenumber_width(self.S, force=True)
        if buf.large and self.S["large_no_wrap"]:
            e.SendScintilla(S.SCI_SETWRAPMODE, S.SC_WRAP_NONE)
        else:
            e.SendScintilla(S.SCI_SETWRAPMODE, S.SC_WRAP_WORD if self.S["word_wrap"] else S.SC_WRAP_NONE)
        e.setBraceMatching(S.BraceMatch.NoBraceMatch if (buf.large and not self.S["large_brace"])
                           else S.BraceMatch.SloppyBraceMatch)

    def tab_settings(self, lang):
        t = self.S["lang_tabs"].get(lang)
        if t:
            return int(t[0]), bool(t[1])
        lg = self.langdb.get(lang)
        if lg.tab_settings:
            return lg.tab_settings
        return int(self.S["tab_size"]), bool(self.S["use_spaces"])

    def set_buffer_lang(self, buf, lang, forced=False):
        buf.lang = lang
        if forced:
            buf.lang_forced = True
        with self.doc_editor(buf) as e:
            self._setup_lexer(e, lang)
            e.SendScintilla(S.SCI_COLOURISE, 0, -1)
        for v in self.views_of(buf):
            if v.current is buf:
                self.apply_buffer_to_editor(v.editor, buf)
                v.editor.SendScintilla(S.SCI_COLOURISE, 0, -1)
        self.refresh_buffer_ui(buf)
        self.panel_event("lang")

    def restyle_all(self):
        for b in self.all_buffers:
            with self.doc_editor(b) as e:
                self._setup_lexer(e, b.lang)
        for v in self.views:
            if v.current is not None:
                self.apply_buffer_to_editor(v.editor, v.current)
                v.editor.apply_view_settings(self.S)
                v.editor.SendScintilla(S.SCI_COLOURISE, 0, -1)
        self.panel_event("theme")

    def on_current_changed(self, view, buf):
        if view is self.active_view:
            self.update_title()
            self.update_status()
            self.sync_check_states()
            self.panel_event("current")
        self.update_smart_highlight(view.editor, force=True)

    def refresh_buffer_ui(self, buf):
        for v in self.views_of(buf):
            v.refresh_tab(buf)
        if buf is self.buf():
            self.update_title()
            self.update_status()
            self.sync_check_states()

    def update_title(self):
        b = self.buf()
        if b is None:
            self.setWindowTitle(APP_NAME)
            return
        name = b.name() if self.S["title_filename_only"] else b.full_name()
        t = ("*" if b.dirty else "") + name + " - " + APP_NAME
        if getattr(self.opts, "title_add", None):
            t += " - " + self.opts.title_add
        if self.recording:
            t = "[REC] " + t
        self.setWindowTitle(t)

    def update_status(self):
        b = self.buf()
        e = self.editor()
        if b is None:
            return
        lg = self.langdb.get(b.lang)
        self.sb_lang.setText(lg.desc)
        n = e.length()
        lines = e.line_count()
        self.sb_len.setText("length : {:,}    lines : {:,}".format(n, lines))
        p = e.pos()
        line = e.line_from_pos(p)
        col = e.SendScintilla(S.SCI_GETCOLUMN, p) + 1
        nsel = e.SendScintilla(S.SCI_GETSELECTIONS)
        if nsel > 1:
            sel = "Sel : %d" % nsel if not e.SendScintilla(S.SCI_SELECTIONISRECTANGLE) else \
                "Sel : %d x %d" % (nsel, abs(e.SendScintilla(S.SCI_GETCOLUMN, e.SendScintilla(S.SCI_GETRECTANGULARSELECTIONCARET)) -
                                         e.SendScintilla(S.SCI_GETCOLUMN, e.SendScintilla(S.SCI_GETRECTANGULARSELECTIONANCHOR))))
        else:
            a, bb = e.sel_range()
            chars = e.SendScintilla(S.SCI_COUNTCHARACTERS, a, bb)
            sl = e.line_from_pos(bb) - e.line_from_pos(a) + (1 if bb > a else 0)
            sel = "Sel : {:,} | {:,}".format(chars, sl)
        self.sb_pos.setText("Ln : {:,}    Col : {:,}    Pos : {:,}    {}".format(line + 1, col, p + 1, sel))
        self.sb_eol.setText({S.SC_EOL_CRLF: "Windows (CR LF)", S.SC_EOL_LF: "Unix (LF)",
                             S.SC_EOL_CR: "Macintosh (CR)"}.get(e.SendScintilla(S.SCI_GETEOLMODE), ""))
        self.sb_enc.setText(enc.display_name(b.encoding))
        self.sb_ins.setText("OVR" if e.SendScintilla(S.SCI_GETOVERTYPE) else "INS")

    def sync_check_states(self):
        b = self.buf()
        if b is None:
            return
        e = self.editor()
        S_ = self.S
        lid = LANG_MENU.get(b.lang)
        if lid in self.actions:
            self.actions[lid].setChecked(True)
        eid = enc.menu_id(b.encoding)
        if eid in self.actions:
            self.actions[eid].setChecked(True)
        else:
            for a in self.enc_group.actions():
                a.setChecked(False)
        eol = e.SendScintilla(S.SCI_GETEOLMODE)
        for cid, m in ((45001, S.SC_EOL_CRLF), (45002, S.SC_EOL_LF), (45003, S.SC_EOL_CR)):
            self.actions[cid].setChecked(eol == m)
        checks = {
            44034: S_["always_on_top"], 44032: self._fullscreen, 44009: self.post_it, 44011: self.dfm,
            44025: S_["show_ws"], 44026: S_["show_eol"], 44130: S_["show_npc"], 44131: S_["show_cc"],
            44019: S_["show_ws"] and S_["show_eol"] and S_["show_npc"] and S_["show_cc"],
            44020: S_["show_indent"], 44041: S_["show_wrap_symbol"], 44027: S_["zoom_sync"],
            44022: S_["word_wrap"], 44035: S_["sync_v"], 44036: S_["sync_h"],
            42028: b.user_readonly, 44097: b.monitoring, 42033: b.file_readonly,
        }
        for cid, v in checks.items():
            self.actions[cid].setChecked(bool(v))
        for cid, name in ((44080, "docmap"), (44070, "doclist"), (44084, "funclist"), (44085, "workspace"),
                          (44081, "project1"), (44082, "project2"), (44083, "project3"),
                          (42051, "charpanel"), (42052, "cliphistory")):
            d = self.docks.get(name)
            self.actions[cid].setChecked(bool(d is not None and d.isVisible()))
        self.actions[42019].setEnabled(self.recording)
        self.actions[42018].setEnabled(not self.recording)
        self.actions[42021].setEnabled(bool(self.last_macro) and not self.recording)
        self.actions[42032].setEnabled(bool(self.last_macro or self.shortcut_file.macros) and not self.recording)
        self.actions[42025].setEnabled(bool(self.last_macro) and not self.recording)
        self.actions[41006].setEnabled(b.dirty or b.untitled)
        self.actions[42003].setEnabled(bool(e.SendScintilla(S.SCI_CANUNDO)))
        self.actions[42004].setEnabled(bool(e.SendScintilla(S.SCI_CANREDO)))
        self.actions[41007].setEnabled(any(x.dirty for x in self.all_buffers))
        self.actions[44097].setEnabled(b.path is not None)

    def update_edit_menu(self):
        e = self.editor()
        has_sel = not e.SendScintilla(S.SCI_GETSELECTIONEMPTY)
        for cid in (42001, 42002, 42006):
            self.actions[cid].setEnabled(has_sel or cid != 42001 or True)
        self.actions[42005].setEnabled(bool(e.SendScintilla(S.SCI_CANPASTE)))

    # ======================================================= editor callbacks
    def on_savepoint(self, ed, dirty):
        b = ed.buffer
        if b is None:
            return
        dirty = dirty or b.force_dirty
        if b.dirty != dirty:
            b.dirty = dirty
            self.refresh_buffer_ui(b)
            self.panel_event("dirty")

    def on_editor_ui(self, ed):
        if ed is self.editor():
            self.update_status()
        if ed.view_index >= 0:
            self.sync_scroll(ed)

    def on_editor_idle(self, ed):
        if ed.view_index < 0:
            return
        self.update_smart_highlight(ed)
        self.update_tag_match(ed)
        self.update_urls(ed)
        self.panel_event("scroll", ed)

    def on_text_modified(self, ed, pos, mtype, length, added):
        if ed.view_index < 0 or ed.buffer is None:
            return
        if self.S["change_history"]:
            self.change_history_mark(ed, pos, mtype, length, added)
        if added:
            ed.update_linenumber_width(self.S)
        self.panel_event("text", ed)

    def on_zoom(self, ed):
        if self.S["zoom_sync"]:
            z = ed.SendScintilla(S.SCI_GETZOOM)
            for v in self.views:
                if v.editor is not ed and v.editor.SendScintilla(S.SCI_GETZOOM) != z:
                    v.editor.SendScintilla(S.SCI_SETZOOM, z)
        ed.update_linenumber_width(self.S, force=True)

    def on_double_click(self, ed, pos, line, mods):
        if not self.S["link_enable"]:
            return
        if ed.SendScintilla(S.SCI_INDICATORVALUEAT, stl.IND_URL, pos):
            a = ed.SendScintilla(S.SCI_INDICATORSTART, stl.IND_URL, pos)
            b = ed.SendScintilla(S.SCI_INDICATOREND, stl.IND_URL, pos)
            url = ed.get_range(a, b)
            QDesktopServices.openUrl(QUrl(url))
            ed.SendScintilla(S.SCI_SETEMPTYSELECTION, pos)

    def on_key_press(self, ed, e):
        if e.key() == Qt.Key.Key_Escape:
            if self.dfm or self.post_it:
                self.run_command(44011 if self.dfm else 44009)
                return True
            if self.inc_bar.isVisible():
                self.inc_bar.hide()
                ed.setFocus()
                return True
        if e.key() == Qt.Key.Key_Insert and not e.modifiers():
            QTimer.singleShot(0, self.update_status)
        return False

    # ================================================================ events
    def changeEvent(self, ev):
        if ev.type() == QEvent.Type.WindowStateChange and self.S["minimize_to_tray"] and self.isMinimized():
            self.ensure_tray()
            QTimer.singleShot(0, self.hide)
        super().changeEvent(ev)

    def ensure_tray(self):
        if self.tray is not None or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        for it in TRAY:
            if it[0] == "sep":
                menu.addSeparator()
            elif it[0] == "cmd":
                a = menu.addAction(it[2].replace("&", ""))
                a.triggered.connect(lambda checked=False, c=it[1]: self.tray_command(c))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.tray_command(43101) if r == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()

    def tray_command(self, cid):
        if cid in (43101, 43102, 43103, 43104, 43013):
            self.showNormal()
            self.raise_()
            self.activateWindow()
        if cid == 43102:
            self.run_command(41001)
        elif cid == 43103:
            self.run_command(41001)
            self.editor().paste()
        elif cid == 43104:
            self.run_command(41002)
        elif cid == 43013:
            self.run_command(43013)
        elif cid == 43105:
            if self.tray:
                self.tray.hide()
                self.tray = None
            self.showNormal()

    def closeEvent(self, ev):
        if self.S["close_to_tray"] and not getattr(self, "_really_quit", False):
            self.ensure_tray()
            self.hide()
            ev.ignore()
            return
        if not self.shutdown():
            ev.ignore()
            return
        ev.accept()

    def shutdown(self):
        snapshot = self.S["snapshot"] and self.S["remember_session"] and not getattr(self.opts, "nosession", False)
        if snapshot:
            self.snapshot_backup(force=True)
        else:
            dirty = [b for b in self.all_buffers if b.dirty]
            mode = None
            for b in dirty:
                if mode == "noall":
                    break
                if mode != "yesall":
                    vs = self.views_of(b)
                    if vs:
                        vs[0].activate(b)
                        self.set_active_view(vs[0])
                    r = self.confirm_save(b, multi=len(dirty) > 1)
                    if r == "cancel":
                        return False
                    if r in ("yesall", "noall"):
                        mode = r
                    if r in ("no", "noall"):
                        continue
                if not self.save_buffer(b):
                    return False
        self.closing = True
        if self.S["remember_session"] and not getattr(self.opts, "nosession", False):
            sess.save_session(self, paths.cfg("session.xml"), with_backups=snapshot)
        self.save_window_state()
        self.S.save()
        self.shortcut_file.save()
        for p in self.panels.values():
            if hasattr(p, "save"):
                p.save()
        return True

    def save_window_state(self):
        self.S["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self.S["window_state"] = bytes(self.saveState().toBase64()).decode()
        self.S["splitter"] = bytes(self.splitter.saveState().toBase64()).decode()
        self.S["split_orientation"] = self.splitter.orientation().value
        self.S["panels"] = {k: d.isVisible() for k, d in self.docks.items()}

    def restore_geometry(self):
        g = self.S["geometry"]
        if g:
            self.restoreGeometry(QByteArray.fromBase64(g.encode()))
        else:
            self.resize(1100, 760)
        if self.S["splitter"]:
            self.splitter.restoreState(QByteArray.fromBase64(self.S["splitter"].encode()))

    def restore_panels(self):
        for name, vis in (self.S["panels"] or {}).items():
            if vis:
                self.show_panel(name, True)
        st = self.S["window_state"]
        if st:
            self.restoreState(QByteArray.fromBase64(st.encode()))

    # ============================================================== snapshot
    def restart_backup_timer(self):
        if self.S["snapshot"]:
            self.backup_timer.start(max(1, int(self.S["snapshot_interval"])) * 1000)
        else:
            self.backup_timer.stop()

    def snapshot_backup(self, force=False):
        if not self.S["snapshot"]:
            return
        d = paths.cfg("backup")
        os.makedirs(d, exist_ok=True)
        for b in self.all_buffers:
            if not b.dirty:
                if b.backup_path and os.path.exists(b.backup_path) and not b.untitled:
                    try:
                        os.remove(b.backup_path)
                    except OSError:
                        pass
                    b.backup_path = None
                if not (b.untitled and force):
                    continue
            if b.backup_path is None:
                stamp = time.strftime("%Y-%m-%d_%H%M%S")
                b.backup_path = os.path.join(d, "%s@%s" % (b.name(), stamp))
            with self.doc_editor(b) as e:
                data = e.get_bytes()
            try:
                with open(b.backup_path, "wb") as f:
                    f.write(data)
            except OSError:
                pass

    # ============================================================== dispatch
    def run_command(self, cid):
        if self.recording and cid not in (42018, 42019, 42021, 42025, 42032):
            self.macro.append((2, 0, cid, 0, ""))
        h = self.handlers().get(cid)
        if h is None:
            if cid in MENU_LANG:
                b = self.buf()
                if b is not None:
                    self.set_buffer_lang(b, MENU_LANG[cid], forced=True)
                return
            if cid in enc.UNICODE or cid in enc.CHARSETS:
                self.set_encoding(cid)
                return
            QMessageBox.information(self, APP_NAME, "This command is not available in %s." % APP_NAME)
            return
        h()
        if self.isVisible():
            self.sync_check_states()
            self.update_status()

    def run_command_text(self, label):
        for cid, a in self.actions.items():
            if a.text().replace("&", "").lower() == label.replace("&", "").lower():
                return cid
        return None

    def handlers(self):
        if getattr(self, "_handlers", None) is None:
            h = {}
            for mixin in (self.file_handlers, self.edit_handlers, self.search_handlers,
                          self.view_handlers, self.misc_handlers):
                h.update(mixin())
            self._handlers = h
        return self._handlers

    # ================================================================ panels
    def panel_event(self, kind, ed=None):
        for p in self.panels.values():
            fn = getattr(p, "on_event", None)
            if fn is not None:
                fn(kind, ed)

    # ============================================================ file cmds
    def file_handlers(self):
        return {
            41001: lambda: self.new_document(),
            41002: self.cmd_open,
            41019: lambda: self.open_containing("explorer"),
            41020: lambda: self.open_containing("terminal"),
            41027: lambda: self.open_containing("pwsh"),
            41025: lambda: self.open_containing("workspace"),
            41023: self.open_default_viewer,
            41022: self.cmd_open_folder_workspace,
            41014: lambda: self.buf() and self.reload_buffer(self.buf()),
            41006: lambda: self.buf() and self.save_buffer(self.buf()),
            41008: lambda: self.buf() and self.save_buffer_as(self.buf()),
            41015: lambda: self.buf() and self.save_buffer_as(self.buf(), copy_only=True),
            41007: self.save_all,
            41017: self.cmd_rename,
            41003: lambda: self.close_buffer(self.buf(), self.active_view),
            41004: lambda: self.close_many(lambda b, i, cur: True),
            41005: lambda: self.close_many(lambda b, i, cur: b is not cur),
            41026: lambda: self.close_many(lambda b, i, cur: not b.pinned),
            41009: lambda: self.close_many(lambda b, i, cur: i < self.active_view.index_of(cur), view_only=True),
            41018: lambda: self.close_many(lambda b, i, cur: i > self.active_view.index_of(cur), view_only=True),
            41024: lambda: self.close_many(lambda b, i, cur: not b.dirty),
            41016: self.cmd_trash,
            41012: self.cmd_load_session,
            41013: self.cmd_save_session,
            41010: self.cmd_print,
            1001: lambda: self.cmd_print(now=True),
            41011: self.close,
            ID_RESTORE_CLOSED: self.restore_closed,
            ID_OPEN_ALL_RECENT: lambda: [self.open_file(p, quiet=True) for p in list(self.S["recent_files"])],
            ID_EMPTY_RECENT: lambda: self.S.__setitem__("recent_files", []),
            ID_MD_LANG: lambda: self.buf() and self.set_buffer_lang(self.buf(), "markdown", forced=True),
        }

    def cmd_open(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Open", self.save_dialog_dir(), self.file_filters())
        if files:
            self.S["last_dir"] = os.path.dirname(files[0])
        for f in files:
            self.open_file(f)

    def cmd_open_folder_workspace(self):
        d = QFileDialog.getExistingDirectory(self, "Select a folder to add in Folder as Workspace panel",
                                             self.save_dialog_dir())
        if d:
            self.open_folder_as_workspace(d)

    def open_folder_as_workspace(self, d):
        p = self.show_panel("workspace", True)
        p.add_root(d)

    def open_containing(self, how):
        b = self.buf()
        if b is None or not b.path:
            return
        d = os.path.dirname(b.path)
        if how == "explorer":
            if not self._spawn(["xdg-open", d]):
                QDesktopServices.openUrl(QUrl.fromLocalFile(d))
        elif how == "terminal":
            for term in (["x-terminal-emulator"], ["gnome-terminal", "--working-directory=" + d],
                         ["konsole", "--workdir", d], ["xfce4-terminal", "--working-directory=" + d],
                         ["xterm"]):
                if shutil.which(term[0]) and self._spawn(term, cwd=d):
                    return
        elif how == "pwsh":
            if not shutil.which("pwsh"):
                QMessageBox.information(self, APP_NAME, "PowerShell (pwsh) is not installed.")
                return
            for term in (["x-terminal-emulator", "-e", "pwsh"], ["gnome-terminal", "--", "pwsh"], ["xterm", "-e", "pwsh"]):
                if shutil.which(term[0]) and self._spawn(term, cwd=d):
                    return
        elif how == "workspace":
            self.open_folder_as_workspace(d)

    def _spawn(self, args, cwd=None):
        try:
            env = dict(os.environ)
            for k in ("LD_LIBRARY_PATH", "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
                if k in env and os.environ.get("APPIMAGE"):
                    orig = env.get(k + "_ORIG")
                    if orig:
                        env[k] = orig
                    else:
                        env.pop(k, None)
            subprocess.Popen(args, cwd=cwd, env=env, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False

    def open_default_viewer(self):
        b = self.buf()
        if b and b.path:
            if not self._spawn(["xdg-open", b.path]):
                QDesktopServices.openUrl(QUrl.fromLocalFile(b.path))

    def save_all(self):
        for b in list(self.all_buffers):
            if b.dirty:
                if b.untitled:
                    vs = self.views_of(b)
                    if vs:
                        vs[0].activate(b)
                if not self.save_buffer(b):
                    break

    def cmd_rename(self):
        b = self.buf()
        if b is None:
            return
        if b.untitled:
            from PyQt6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "Rename", "New name:", text=b.title)
            if ok and name.strip():
                b.title = name.strip()
                self.refresh_buffer_ui(b)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Rename", b.path)
        if not path or path == b.path:
            return
        try:
            self.unwatch(b.path)
            os.rename(b.path, path)
        except OSError as ex:
            QMessageBox.warning(self, "Rename", str(ex))
            self.watch(b.path)
            return
        b.path = os.path.abspath(path)
        b.mtime = os.path.getmtime(b.path)
        self.watch(b.path)
        if not b.lang_forced:
            lg = self.langdb.detect(b.path)
            if lg and lg != b.lang:
                self.set_buffer_lang(b, lg)
        self.add_recent(b.path)
        self.refresh_buffer_ui(b)
        self.panel_event("buffers")

    def cmd_trash(self):
        b = self.buf()
        if b is None or not b.path:
            return
        r = QMessageBox.question(self, "Move to Trash", 'Move "%s" to the Trash?' % b.path)
        if r != QMessageBox.StandardButton.Yes:
            return
        path = b.path
        try:
            from PyQt6.QtCore import QFile
            ok = QFile.moveToTrash(path)
        except Exception:
            ok = False
        if not ok:
            ok = self._spawn(["gio", "trash", path])
        if ok:
            self.close_buffer(b, force=True)
        else:
            QMessageBox.warning(self, APP_NAME, "Could not move the file to the Trash.")

    def close_many(self, pred, view_only=False):
        cur = self.buf()
        views = [self.active_view] if view_only else self.views
        targets = []
        for v in views:
            for i, b in enumerate(list(v.buffers)):
                if pred(b, i, cur) and b not in targets:
                    targets.append((v, b))
        dirty = [b for v, b in targets if b.dirty and len(self.views_of(b)) == 1]
        mode = None
        for v, b in targets:
            if b.dirty and len(self.views_of(b)) == 1:
                if mode == "noall":
                    self.close_buffer(b, v, force=True)
                    continue
                if mode != "yesall":
                    v.activate(b)
                    r = self.confirm_save(b, multi=len(dirty) > 1)
                    if r == "cancel":
                        return
                    if r in ("yesall", "noall"):
                        mode = r
                    if r in ("no", "noall"):
                        self.close_buffer(b, v, force=True)
                        continue
                if not self.save_buffer(b):
                    return
            self.close_buffer(b, v, force=True)

    def restore_closed(self):
        while self.closed_history:
            p = self.closed_history.pop()
            if os.path.exists(p) and not self.find_buffer(p):
                self.open_file(p)
                return

    def cmd_load_session(self):
        f, _ = QFileDialog.getOpenFileName(self, "Load Session", self.save_dialog_dir(), "All types (*)")
        if f:
            sess.load_session(self, f)

    def cmd_save_session(self):
        ext = self.S["session_ext"]
        f, _ = QFileDialog.getSaveFileName(self, "Save Session", self.save_dialog_dir(),
                                           ("Session file (*.%s);;" % ext if ext else "") + "All types (*)")
        if f:
            if ext and not os.path.splitext(f)[1]:
                f += "." + ext
            sess.save_session(self, f, with_backups=False)

    def cmd_print(self, now=False):
        from PyQt6.Qsci import QsciPrinter
        from PyQt6.QtPrintSupport import QPrintDialog
        e = self.editor()
        pr = QsciPrinter()
        pr.setDocName(self.buf().name() if self.buf() else APP_NAME)
        e.SendScintilla(S.SCI_SETPRINTCOLOURMODE,
                        {"wysiwyg": 0, "invert": 1, "bw": 2, "nobg": 4}.get(self.S["print_color"], 0))
        from PyQt6.QtCore import QMarginsF
        from PyQt6.QtGui import QPageLayout
        t, l, r, b_ = self.S["print_margins"]
        pr.setPageMargins(QMarginsF(l, t, r, b_), QPageLayout.Unit.Millimeter)
        pr.setMagnification(0)
        if not now:
            dlg = QPrintDialog(pr, self)
            if e.hasSelectedText():
                dlg.setOption(QPrintDialog.PrintDialogOption.PrintSelection, True)
            if dlg.exec() != QPrintDialog.DialogCode.Accepted:
                return
        a, bb = -1, -1
        if e.hasSelectedText():
            a = e.line_from_pos(e.sel_range()[0])
            bb = e.line_from_pos(e.sel_range()[1])
        pr.printRange(e, a, bb)
