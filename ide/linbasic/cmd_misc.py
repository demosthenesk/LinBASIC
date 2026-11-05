"""Encoding, Language, Settings, Tools, Macro, Run, Window and ? menus, plus the
editor and tab context menus (contextMenu.xml)."""
import hashlib
import os
import platform
import re
import shlex
import sys
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt, QUrl, QT_VERSION_STR, PYQT_VERSION_STR
from PyQt6.QtGui import QDesktopServices, QAction
from PyQt6.QtWidgets import QMenu, QMessageBox, QFileDialog, QApplication, QInputDialog
from PyQt6.Qsci import QsciScintilla as S, QSCINTILLA_VERSION_STR

from . import APP_NAME, VERSION, UPSTREAM, paths, encodings_util as enc
from .npp_tables import MENUBAR, RUNVARS

STRING_MSGS = {2170, 2001, 2003, 2282, 2367, 2368}   # REPLACESEL, ADDTEXT, INSERTTEXT, APPENDTEXT, SEARCHNEXT/PREV

CMDLINE_HELP = """Usage :

linbasic [--help] [-multiInst] [-noPlugin] [-L<langCode>] [-r] [-n<line>] [-c<column>] [-p<position>]
         [-l<Language>] [-x<LeftPos>] [-y<TopPos>] [-nosession] [-notabbar] [-ro] [-fullReadOnly]
         [-systemtray] [-loadingTime] [-alwaysOnTop] [-openSession] [-titleAdd=<string>]
         [-settingsDir=<path>] [-openFoldersAsWorkspace] [-monitor] [filePath]

--help : This help message
-multiInst : Launch another instance
-noPlugin : Launch without loading any plugin (accepted, no effect)
-l : Open file or display ghost typing with syntax highlighting of choice
-L : Apply indicated localization, langCode is browser language code (e.g. el, fr, de)
-n : Scroll to indicated line on filePath
-c : Scroll to indicated column on filePath
-p : Scroll to indicated position on filePath
-x : Move window to indicated left side position on the screen
-y : Move window to indicated top position on the screen
-nosession : Launch without previous session
-notabbar : Launch without tabbar
-ro : Make the filePath read-only
-fullReadOnly : Open all files read-only by default
-systemtray : Launch in system tray
-alwaysOnTop : Make LinBASIC always on top
-openSession : Open a session. filePath must be a session file
-r : Open files recursively. This argument will be ignored if filePath contains no wildcard character
-titleAdd : Add a dash and a space to the title bar, followed by the string (e.g. -titleAdd="Foo")
-settingsDir : Override the default settings directory (e.g. -settingsDir="/home/me/lp")
-openFoldersAsWorkspace : Open filePath of folder(s) as workspace
-monitor : Open file with file monitoring enabled
filePath : file or folder name to open (absolute or relative path name)
"""


def _english_index():
    """(top label, item label) -> command id, for contextMenu.xml lookups."""
    out = {}

    def walk(top, items):
        for it in items:
            if it[0] == "cmd":
                out.setdefault((top, it[2].replace("&", "").lower()), it[1])
            elif it[0] == "sub":
                walk(top, it[3])
    for mid, label, items in MENUBAR:
        walk(label.replace("&", "").lower(), items)
    return out


TAB_MENU = [
    ("cmd", 41003, None), ("cmd", 41005, "Close All BUT This"), ("cmd", 41009, None), ("cmd", 41018, None),
    ("cmd", 41024, None), ("cmd", 41006, None), ("cmd", 41008, None), ("cmd", 41017, None), ("cmd", 41016, None),
    ("cmd", 41014, "Reload"), ("cmd", 41010, None), ("sep",),
    ("cmd", 41019, "Open Containing Folder in File Manager"), ("cmd", 41020, "Open Containing Folder in Terminal"),
    ("cmd", 41025, "Open Containing Folder as Workspace"), ("sep",), ("cmd", 41023, None), ("sep",),
    ("cmd", 42028, "Read-Only"), ("cmd", 42033, None), ("sep",),
    ("cmd", 42029, "Full File Path to Clipboard"), ("cmd", 42030, "Filename to Clipboard"),
    ("cmd", 42031, "Current Dir. Path to Clipboard"), ("sep",),
    ("cmd", 10001, None), ("cmd", 10002, None), ("cmd", 10003, None), ("cmd", 10004, None),
    ("sub", "Apply Color to Tab", [44111, 44112, 44113, 44114, 44115, 44110]),
    ("pin",),
]


class MiscMixin:
    def misc_handlers(self):
        h = {
            46001: self.style_configurator, 48011: self.open_preferences, 48009: self.shortcut_mapper,
            48005: lambda: QMessageBox.information(self, "Import plugin(s)",
                                                   "Notepad++ plugins are Windows DLLs and can't be loaded on Linux.\n"
                                                   "MIME Tools, Converter and NppExport are built into %s." % APP_NAME),
            48006: self.import_themes, 48018: lambda: self.open_file(paths.cfg("contextMenu.xml")),
            46250: self.udl_unavailable, 46300: lambda: self._spawn(["xdg-open", paths.cfg("userDefineLangs")]),
            46301: lambda: QDesktopServices.openUrl(QUrl("https://github.com/notepad-plus-plus/userDefinedLanguages")),
            46180: lambda: None,
            48501: lambda: self.hash_dialog("md5"), 48502: lambda: self.hash_files("md5"),
            48503: lambda: self.hash_selection("md5"),
            48507: lambda: self.hash_dialog("sha1"), 48508: lambda: self.hash_files("sha1"),
            48509: lambda: self.hash_selection("sha1"),
            48504: lambda: self.hash_dialog("sha256"), 48505: lambda: self.hash_files("sha256"),
            48506: lambda: self.hash_selection("sha256"),
            48510: lambda: self.hash_dialog("sha512"), 48511: lambda: self.hash_files("sha512"),
            48512: lambda: self.hash_selection("sha512"),
            42018: self.start_recording, 42019: self.stop_recording,
            50005: lambda: self.stop_recording() if self.recording else self.start_recording(),
            42021: lambda: self.last_macro and self.play_macro(self.last_macro),
            42025: self.save_macro, 42032: self.run_macro_multi,
            49000: self.run_dialog, 49001: self.validate_shortcuts,
            48014: lambda: self._spawn(["xdg-open", paths.cfg("plugins")]),
            11001: self.windows_dialog, 11020: lambda: self.switch_tab(1, mru=True),
            47010: lambda: self.text_box("Command Line Arguments", CMDLINE_HELP),
            47001: lambda: QDesktopServices.openUrl(QUrl("https://notepad-plus-plus.org/")),
            47002: lambda: QDesktopServices.openUrl(QUrl("https://github.com/notepad-plus-plus/notepad-plus-plus")),
            47003: lambda: QDesktopServices.openUrl(QUrl("https://npp-user-manual.org/")),
            47004: lambda: QDesktopServices.openUrl(QUrl("https://community.notepad-plus-plus.org/")),
            47006: lambda: QMessageBox.information(self, "Update", "%s %s is distributed as an AppImage.\n"
                                                   "Download a newer AppImage to update." % (APP_NAME, VERSION)),
            47009: lambda: QMessageBox.information(self, "Updater proxy", "%s has no auto-updater, so no proxy is needed." % APP_NAME),
            47012: self.debug_info, 47000: self.about,
        }
        for cid in enc.CONVERT:
            h[cid] = lambda c=cid: self.convert_encoding(enc.CONVERT[c])
        sorts = {11002: ("name", False), 11003: ("name", True), 11004: ("path", False), 11005: ("path", True),
                 11006: ("type", False), 11007: ("type", True), 11008: ("len", False), 11009: ("len", True),
                 11010: ("mtime", False), 11011: ("mtime", True)}
        for cid, (k, d) in sorts.items():
            h[cid] = lambda k=k, d=d: self.sort_tabs(k, d)
        return h

    # -------------------------------------------------------------- encoding
    def set_encoding(self, cid):
        b = self.buf()
        if b is None:
            return
        target = enc.UNICODE[cid][0] if cid in enc.UNICODE else enc.CHARSETS[cid][0]
        if b.untitled or not b.path:
            b.encoding = target
            self.refresh_buffer_ui(b)
            return
        if b.dirty:
            r = QMessageBox.question(self, "Lose Undo Ability Warning",
                                     "You should save the current modification.\nAll the saved modifications can not be undone.\n\nSave the current modification?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Cancel:
                return
            if r == QMessageBox.StandardButton.Yes:
                self.save_buffer(b)
        self.reload_buffer(b, target, ask=False)

    def convert_encoding(self, target):
        b = self.buf()
        if b is None or b.encoding == target:
            return
        b.encoding = target
        b.dirty = b.force_dirty = True
        self.refresh_buffer_ui(b)

    # ---------------------------------------------------------------- dialogs
    def style_configurator(self):
        from .dialogs.styleconf import StyleConfigurator
        StyleConfigurator(self).exec()

    def open_preferences(self, page=None):
        from .dialogs.prefs import PreferencesDialog
        dlg = PreferencesDialog(self, page)
        dlg.exec()

    def shortcut_mapper(self):
        from .dialogs.shortcuts import ShortcutMapper
        ShortcutMapper(self).exec()

    def column_editor(self):
        from .dialogs.misc import ColumnEditor
        ColumnEditor(self).exec()

    def windows_dialog(self):
        from .dialogs.misc import WindowsDialog
        WindowsDialog(self).exec()

    def run_dialog(self):
        from .dialogs.run import RunDialog
        RunDialog(self).exec()

    def text_box(self, title, text):
        from .dialogs.misc import TextDialog
        TextDialog(self, title, text).exec()

    def import_themes(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Import style theme(s)", os.path.expanduser("~"),
                                                "XML files (*.xml)")
        for f in files:
            try:
                ET.parse(f)
            except ET.ParseError:
                QMessageBox.warning(self, "Import", "%s is not a valid XML file." % f)
                continue
            import shutil
            shutil.copy(f, paths.cfg("themes", os.path.basename(f)))
        if files:
            QMessageBox.information(self, "Import", "Theme(s) imported. Pick them in Settings → Style Configurator.")

    def udl_unavailable(self):
        QMessageBox.information(
            self, "User Defined Language",
            "The User Defined Language engine (LexUser) is Notepad++'s own lexer and isn't part of the "
            "Scintilla build %s uses.\n\nMarkdown, which Notepad++ ships as a preinstalled UDL, is provided "
            "natively: Language → User Defined Language → Markdown." % APP_NAME)

    # ------------------------------------------------------------------ hash
    def hash_dialog(self, algo):
        from .dialogs.misc import HashDialog
        HashDialog(self, algo).exec()

    def hash_files(self, algo):
        from .dialogs.misc import HashFilesDialog
        HashFilesDialog(self, algo).exec()

    def hash_selection(self, algo):
        t = self.editor().sel_text()
        if not t:
            return
        if self.S["hash_treat_lines"]:
            out = "\n".join(hashlib.new(algo, l.encode()).hexdigest() for l in t.splitlines())
        else:
            out = hashlib.new(algo, t.encode()).hexdigest()
        QApplication.clipboard().setText(out)

    # ----------------------------------------------------------------- macro
    def start_recording(self):
        self.macro = []
        self.recording = True
        for v in self.views:
            v.editor.SendScintilla(S.SCI_STARTRECORD)
        self.update_title()
        self.sync_check_states()

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        for v in self.views:
            v.editor.SendScintilla(S.SCI_STOPRECORD)
        if self.macro:
            self.last_macro = list(self.macro)
        self.update_title()
        self.sync_check_states()

    def on_macro_record(self, ed, msg, wparam, lparam):
        if not self.recording:
            return
        s = ""
        lp = 0
        if msg in STRING_MSGS:
            try:
                import ctypes
                addr = int(lparam)
                raw = ctypes.string_at(addr, wparam) if msg in (2001, 2282) else ctypes.string_at(addr)
                s = raw.decode("utf-8", "replace")
            except Exception:
                s = ""
        else:
            try:
                lp = int(lparam) if lparam is not None else 0
            except (TypeError, ValueError):
                lp = 0
        self.macro.append((1, int(msg), int(wparam), lp, s))

    def play_macro(self, actions, times=1, until_eof=False):
        ed = self.editor()
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        try:
            n = 0
            while True:
                if until_eof:
                    before = ed.pos()
                    if before >= ed.length():
                        break
                elif n >= times:
                    break
                for t, msg, w, l, s in actions:
                    if t == 2:
                        self.run_command(w)
                        ed = self.editor()
                    elif t in (0, 1):
                        if msg in STRING_MSGS:
                            data = s.encode("utf-8")
                            if msg in (2001, 2282):
                                ed.SendScintilla(msg, len(data), data)
                            else:
                                ed.SendScintilla(msg, w, data)
                        else:
                            ed.SendScintilla(msg, w, l)
                n += 1
                if until_eof and ed.pos() == before:
                    break
        finally:
            ed.SendScintilla(S.SCI_ENDUNDOACTION)

    def save_macro(self):
        if not self.last_macro:
            return
        from .dialogs.shortcuts import ShortcutDialog
        dlg = ShortcutDialog(self, "Save macro", "", None)
        if dlg.exec():
            name, seq = dlg.result_value()
            if name:
                self.shortcut_file.macros.append({"name": name, "folder": "", "seq": seq, "actions": list(self.last_macro)})
                self.shortcut_file.save()
                self.dynamic_shortcuts()

    def run_macro_multi(self):
        from .dialogs.misc import MacroMultiDialog
        MacroMultiDialog(self).exec()

    def refresh_macro_menu(self):
        m = self.menus["macro"]
        for a in list(m.actions()):
            if a not in self.macro_static:
                m.removeAction(a)
        if self.shortcut_file.macros:
            m.addSeparator()
            folders = {}
            for mac in self.shortcut_file.macros:
                target = m
                if mac.get("folder"):
                    target = folders.get(mac["folder"]) or m.addMenu(mac["folder"])
                    folders[mac["folder"]] = target
                a = target.addAction(mac["name"])
                a.setShortcut(mac["seq"])
                a.setShortcutVisibleInContextMenu(True)
                a.triggered.connect(lambda checked=False, mm=mac: self.play_macro(mm["actions"]))
        m.addSeparator()
        m.addAction("Modify Shortcut/Delete Macro...").triggered.connect(lambda: self.shortcut_mapper_tab(1))
        self.sync_check_states()

    def shortcut_mapper_tab(self, tab):
        from .dialogs.shortcuts import ShortcutMapper
        d = ShortcutMapper(self)
        d.tabs.setCurrentIndex(tab)
        d.exec()

    # ------------------------------------------------------------------- run
    def expand_vars(self, cmd):
        ed = self.editor()
        b = self.buf()
        path = b.full_name() if b else ""
        name = os.path.basename(path)
        app_path = os.environ.get("APPIMAGE") or os.path.abspath(sys.argv[0])
        line = ed.line_from_pos(ed.pos())
        vals = {
            "FULL_CURRENT_PATH": path,
            "CURRENT_DIRECTORY": os.path.dirname(path) if b and b.path else "",
            "FILE_NAME": name,
            "NAME_PART": os.path.splitext(name)[0],
            "EXT_PART": os.path.splitext(name)[1],
            "CURRENT_WORD": self.current_word(ed),
            "NPP_DIRECTORY": os.path.dirname(app_path),
            "NPP_FULL_FILE_PATH": app_path,
            "CURRENT_LINE": str(line + 1),
            "CURRENT_COLUMN": str(ed.SendScintilla(S.SCI_GETCOLUMN, ed.pos()) + 1),
            "CURRENT_LINESTR": ed.get_range(ed.line_start(line), ed.line_end(line)),
            "SYS.HOME": os.path.expanduser("~"),
        }
        def rep(m):
            k = m.group(1)
            if k.startswith("SYS."):
                return os.environ.get(k[4:], vals.get(k, ""))
            return vals.get(k, m.group(0))
        return re.sub(r"\$\(([A-Za-z_.]+)\)", rep, cmd)

    def run_user_command(self, cmd):
        cmd = self.expand_vars(cmd).strip()
        if not cmd:
            return
        if re.match(r"^(https?|ftp|mailto):", cmd):
            QDesktopServices.openUrl(QUrl(cmd))
            return
        app = os.environ.get("APPIMAGE")
        if app and cmd.startswith(app):
            cmd = cmd.replace("-nosession -multiInst", "-multiInst -nosession")
        try:
            args = shlex.split(cmd)
        except ValueError:
            args = cmd.split()
        if not self._spawn(["/bin/sh", "-c", cmd], cwd=os.path.dirname(self.buf().path) if self.buf() and self.buf().path else None):
            QMessageBox.warning(self, "Run", "Cannot run:\n%s" % cmd)

    def refresh_run_menu(self):
        m = self.menus["run"]
        for a in list(m.actions()):
            if a not in self.run_static:
                m.removeAction(a)
        if self.shortcut_file.commands:
            m.addSeparator()
            folders = {}
            for c in self.shortcut_file.commands:
                target = m
                if c.get("folder"):
                    target = folders.get(c["folder"]) or m.addMenu(c["folder"])
                    folders[c["folder"]] = target
                a = target.addAction(c["name"])
                a.setShortcut(c["seq"])
                a.triggered.connect(lambda checked=False, cc=c: self.run_user_command(cc["cmd"]))
        m.addSeparator()
        m.addAction("Modify Shortcut/Delete Command...").triggered.connect(lambda: self.shortcut_mapper_tab(2))

    def validate_shortcuts(self):
        try:
            ET.parse(paths.cfg("shortcuts.xml"))
        except ET.ParseError as ex:
            QMessageBox.warning(self, "Validate shortcuts.xml", "shortcuts.xml is not valid XML:\n%s" % ex)
            return
        except OSError:
            QMessageBox.information(self, "Validate shortcuts.xml", "shortcuts.xml doesn't exist yet.")
            return
        seen = {}
        dups = []
        def add(seq, what):
            if seq.isEmpty():
                return
            k = seq.toString()
            if k in seen:
                dups.append("%s: %s / %s" % (k, seen[k], what))
            else:
                seen[k] = what
        for cid, a in self.actions.items():
            for s_ in a.shortcuts():
                add(s_, a.text().replace("&", ""))
        for mm in self.shortcut_file.macros:
            add(mm["seq"], "Macro " + mm["name"])
        for c in self.shortcut_file.commands:
            add(c["seq"], "Run " + c["name"])
        QMessageBox.information(self, "Validate shortcuts.xml",
                                "shortcuts.xml is valid.\n%d macros, %d run commands, %d remapped commands."
                                % (len(self.shortcut_file.macros), len(self.shortcut_file.commands),
                                   len(self.shortcut_file.internal))
                                + ("\n\nConflicting shortcuts:\n" + "\n".join(dups) if dups else "\n\nNo conflicts found."))

    # ---------------------------------------------------------------- window
    def sort_tabs(self, key, desc):
        v = self.active_view

        def k(b):
            if key == "name":
                return b.name().lower()
            if key == "path":
                return b.full_name().lower()
            if key == "type":
                return (os.path.splitext(b.name())[1].lower(), b.name().lower())
            if key == "len":
                with self.doc_editor(b) as e:
                    return e.length()
            if key == "mtime":
                try:
                    return os.path.getmtime(b.path) if b.path else 0
                except OSError:
                    return 0
        order = sorted(v.buffers, key=k, reverse=desc)
        for target, b in enumerate(order):
            v.move_tab(v.index_of(b), target)

    def refresh_window_menu(self):
        m = self.menus["Window"]
        for a in list(m.actions()):
            if a not in self.window_static:
                m.removeAction(a)
        m.addSeparator()
        n = 0
        for v in self.views:
            for b in v.buffers:
                n += 1
                if n > 20:
                    break
                a = m.addAction(("&%d: " % n if n < 10 else "") + b.name().replace("&", "&&"))
                a.setCheckable(True)
                a.setChecked(b is self.buf())
                a.triggered.connect(lambda checked=False, vv=v, bb=b: (vv.activate(bb), self.set_active_view(vv), vv.editor.setFocus()))

    # ------------------------------------------------------------------- help
    def debug_info(self):
        lines = [
            "%s v%s   (64-bit)" % (APP_NAME, VERSION),
            "Clone of: %s" % UPSTREAM,
            "Build: Python %s, Qt %s, PyQt %s, QScintilla %s" % (platform.python_version(), QT_VERSION_STR,
                                                               PYQT_VERSION_STR, QSCINTILLA_VERSION_STR),
            "Path: %s" % (os.environ.get("APPIMAGE") or os.path.abspath(sys.argv[0])),
            "Settings dir: %s" % paths.config_dir(),
            "Data dir: %s" % paths.DATA_DIR,
            "Session: %s" % ("off (-nosession)" if getattr(self.opts, "nosession", False) else "on"),
            "OS: %s" % " ".join(platform.freedesktop_os_release().get(k, "") for k in ("PRETTY_NAME",)) if hasattr(platform, "freedesktop_os_release") else platform.platform(),
            "Kernel: %s %s" % (platform.system(), platform.release()),
            "Desktop: %s / %s" % (os.environ.get("XDG_CURRENT_DESKTOP", "?"), QApplication.platformName()),
            "Locale: %s  (ANSI = %s)" % (os.environ.get("LANG", "?"), enc.system_ansi(self.S)),
            "Localization: %s" % self.i18n.name,
            "Theme: %s" % (self.S["theme"] or "stylers.xml"),
        ]
        txt = "\n".join(lines)
        from .dialogs.misc import TextDialog
        d = TextDialog(self, "Debug Info", txt, copy_button="&Copy debug info into clipboard")
        d.exec()

    def about(self):
        from .dialogs.misc import AboutDialog
        AboutDialog(self).exec()

    # ----------------------------------------------------------- context menus
    def editor_context_menu(self, ed, pos):
        self.set_active_view(self.views[ed.view_index] if ed.view_index >= 0 else self.active_view)
        menu = QMenu(self)
        idx = getattr(self, "_eng_idx", None) or _english_index()
        self._eng_idx = idx
        try:
            root = ET.parse(paths.cfg("contextMenu.xml")).getroot()
            items = root.find("ScintillaContextMenu")
            items = list(items) if items is not None else []
        except (ET.ParseError, OSError):
            items = []
        from . import plugins_builtin
        plug = {(p.lower(), n.replace("&", "").lower()): f for p, cmds in plugins_builtin.menu_spec() for n, f in cmds if n}
        folders = {}
        for it in items:
            if it.tag != "Item":
                continue
            target = menu
            fn = it.get("FolderName")
            if fn:
                if fn not in folders:
                    folders[fn] = menu.addMenu(fn)
                target = folders[fn]
            cid = it.get("id")
            if cid == "0":
                target.addSeparator()
                continue
            action = None
            if cid and cid.isdigit():
                action = self.actions.get(int(cid))
            elif it.get("MenuEntryName"):
                key = (it.get("MenuEntryName").replace("&", "").lower(), it.get("MenuItemName", "").replace("&", "").lower())
                c = idx.get(key)
                if c is None:
                    aliases = {"select all": "select all", "hide lines": "hide lines",
                               "set read-only": "read-only on current document",
                               "close all but active document": "close all but active document"}
                    c = idx.get((key[0], aliases.get(key[1], key[1])))
                if c is not None:
                    action = self.actions.get(c)
            elif it.get("PluginEntryName"):
                f = plug.get((it.get("PluginEntryName").lower(), it.get("PluginCommandItemName", "").replace("&", "").lower()))
                if f:
                    a = target.addAction(it.get("ItemNameAs") or it.get("PluginCommandItemName"))
                    a.triggered.connect(lambda checked=False, ff=f: ff(self))
                continue
            if action is None:
                continue
            if it.get("ItemNameAs"):
                a = target.addAction(it.get("ItemNameAs"))
                a.triggered.connect(action.trigger)
            else:
                target.addAction(action)
        if not items:
            for c in (42001, 42002, 42005, 42006, 42007):
                menu.addAction(self.actions[c])
        menu.exec(pos)

    def tab_context_menu(self, view, i, pos):
        b = view.buffer_at(i)
        if b is None:
            return
        view.activate(b)
        self.set_active_view(view)
        self.sync_check_states()
        menu = QMenu(self)
        for it in TAB_MENU:
            if it[0] == "sep":
                menu.addSeparator()
            elif it[0] == "cmd":
                a = self.actions[it[1]]
                if it[2]:
                    x = menu.addAction(it[2])
                    x.setCheckable(a.isCheckable())
                    x.setChecked(a.isChecked())
                    x.setEnabled(a.isEnabled())
                    x.triggered.connect(a.trigger)
                else:
                    menu.addAction(a)
            elif it[0] == "sub":
                sub = menu.addMenu(it[1])
                for c in it[2]:
                    sub.addAction(self.actions[c])
            elif it[0] == "pin":
                a = menu.addAction("Unpin Tab" if b.pinned else "Pin Tab")
                a.triggered.connect(lambda: self.toggle_pin(view, b))
        menu.exec(pos)

    def toggle_pin(self, view, b):
        b.pinned = not b.pinned
        if b.pinned:
            last_pinned = max([j for j, x in enumerate(view.buffers) if x.pinned and x is not b] + [-1])
            view.move_tab(view.index_of(b), last_pinned + 1)
        view.tabs.updateGeometry()
        view.tabs.update()
