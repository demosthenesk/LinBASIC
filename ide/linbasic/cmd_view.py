"""View menu (44009-44131, 10001-10006) and docking panels."""
import os
import shutil
import sys
import time

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QDockWidget, QMessageBox, QApplication
from PyQt6.Qsci import QsciScintilla as S

PANELS = {
    # name: (title, area, module, class)
    "doclist": ("Document List", Qt.DockWidgetArea.RightDockWidgetArea, "doclist", "DocListPanel"),
    "funclist": ("Function List", Qt.DockWidgetArea.RightDockWidgetArea, "funclist", "FunctionListPanel"),
    "workspace": ("Folder as Workspace", Qt.DockWidgetArea.LeftDockWidgetArea, "workspace", "WorkspacePanel"),
    "docmap": ("Document Map", Qt.DockWidgetArea.RightDockWidgetArea, "docmap", "DocMapPanel"),
    "project1": ("Project Panel 1", Qt.DockWidgetArea.LeftDockWidgetArea, "project", "ProjectPanel"),
    "project2": ("Project Panel 2", Qt.DockWidgetArea.LeftDockWidgetArea, "project", "ProjectPanel"),
    "project3": ("Project Panel 3", Qt.DockWidgetArea.LeftDockWidgetArea, "project", "ProjectPanel"),
    "charpanel": ("ASCII Codes Insertion Panel", Qt.DockWidgetArea.RightDockWidgetArea, "charpanel", "CharPanel"),
    "cliphistory": ("Clipboard History", Qt.DockWidgetArea.RightDockWidgetArea, "cliphistory", "ClipHistoryPanel"),
    "results": ("Search results", Qt.DockWidgetArea.BottomDockWidgetArea, "results", "SearchResultsPanel"),
}


class ViewMixin:
    def view_handlers(self):
        h = {
            44034: self.toggle_on_top, 44032: self.toggle_fullscreen, 44009: self.toggle_postit,
            44011: self.toggle_dfm,
            44100: lambda: self.view_in_browser(["firefox"]),
            44101: lambda: self.view_in_browser(["google-chrome", "google-chrome-stable"]),
            44102: lambda: self.view_in_browser(["chromium", "chromium-browser"]),
            44103: lambda: self.view_in_browser(["xdg-open"]),
            44025: lambda: self.toggle_symbol("show_ws"), 44026: lambda: self.toggle_symbol("show_eol"),
            44130: lambda: self.toggle_symbol("show_npc"), 44131: lambda: self.toggle_symbol("show_cc"),
            44019: self.toggle_all_chars, 44020: lambda: self.toggle_symbol("show_indent"),
            44041: lambda: self.toggle_symbol("show_wrap_symbol"), 44022: lambda: self.toggle_symbol("word_wrap"),
            44023: lambda: self.zoom(1), 44024: lambda: self.zoom(-1), 44033: lambda: self.zoom(0),
            44027: lambda: self.toggle_setting("zoom_sync"),
            10001: self.move_to_other_view, 10002: self.clone_to_other_view,
            10003: lambda: self.to_new_instance(move=True), 10004: lambda: self.to_new_instance(move=False),
            44116: lambda: self.goto_tab(0), 44117: lambda: self.goto_tab(-1),
            44095: lambda: self.switch_tab(1), 44096: lambda: self.switch_tab(-1),
            50004: lambda: self.switch_tab(1, mru=True), 50003: lambda: self.switch_tab(-1, mru=True),
            10005: lambda: self.move_tab_to(0), 10006: lambda: self.move_tab_to(-1),
            44098: lambda: self.move_tab_by(1), 44099: lambda: self.move_tab_by(-1),
            44110: lambda: self.tab_color(-1),
            44072: self.focus_other_view, 44042: lambda: self.editor().hide_selected_lines(),
            44010: lambda: self.editor().SendScintilla(S.SCI_FOLDALL, S.SC_FOLDACTION_CONTRACT),
            44029: lambda: self.editor().SendScintilla(S.SCI_FOLDALL, S.SC_FOLDACTION_EXPAND),
            44030: lambda: self.editor().fold_current(True), 44031: lambda: self.editor().fold_current(False),
            44049: self.summary,
            44081: lambda: self.toggle_panel("project1"), 44082: lambda: self.toggle_panel("project2"),
            44083: lambda: self.toggle_panel("project3"), 44085: lambda: self.toggle_panel("workspace"),
            44080: lambda: self.toggle_panel("docmap"), 44070: lambda: self.toggle_panel("doclist"),
            44084: lambda: self.toggle_panel("funclist"),
            44035: lambda: self.toggle_sync("sync_v"), 44036: lambda: self.toggle_sync("sync_h"),
            44097: self.toggle_monitoring,
        }
        for i in range(9):
            h[44086 + i] = lambda i=i: self.goto_tab(i)
        for i in range(5):
            h[44111 + i] = lambda i=i: self.tab_color(i)
        for i in range(8):
            h[44051 + i] = lambda i=i: self.editor().fold_level(i + 1, True)
            h[44061 + i] = lambda i=i: self.editor().fold_level(i + 1, False)
        return h

    # ---------------------------------------------------------------- toggles
    def toggle_setting(self, key):
        self.S[key] = not self.S[key]

    def toggle_symbol(self, key):
        self.S[key] = not self.S[key]
        for v in self.views:
            v.editor.apply_symbols(self.S)
            if v.current is not None and key == "word_wrap":
                self.apply_buffer_to_editor(v.editor, v.current)

    def toggle_all_chars(self):
        on = not (self.S["show_ws"] and self.S["show_eol"] and self.S["show_npc"] and self.S["show_cc"])
        for k in ("show_ws", "show_eol", "show_npc", "show_cc"):
            self.S[k] = on
        for v in self.views:
            v.editor.apply_symbols(self.S)

    def toggle_on_top(self):
        self.S["always_on_top"] = not self.S["always_on_top"]
        geo = self.geometry()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.S["always_on_top"])
        self.show()
        self.setGeometry(geo)

    def toggle_fullscreen(self):
        if self._fullscreen:
            self._fullscreen = False
            self.showNormal()
        else:
            self._fullscreen = True
            self.showFullScreen()

    def _chrome(self, visible):
        self.menuBar().setVisible(visible and not self.S["menubar_hidden"])
        self.toolbar.setVisible(visible and not self.S["toolbar_hidden"])
        self.statusBar().setVisible(visible and not self.S["statusbar_hidden"])
        for v in self.views:
            v.tabs.setVisible(visible and not self.S["tabbar_hidden"])

    def toggle_postit(self):
        if self.dfm:
            return
        self.post_it = not self.post_it
        geo = self.geometry()
        self._chrome(not self.post_it)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, self.post_it)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.post_it or self.S["always_on_top"])
        self.show()
        self.setGeometry(geo)

    def toggle_dfm(self):
        self.dfm = not self.dfm
        if self.dfm:
            self._pre_states = (self.isFullScreen(), self.saveState(), {k: d.isVisible() for k, d in self.docks.items()})
            for d in self.docks.values():
                d.hide()
            self._chrome(False)
            self.showFullScreen()
            QTimer.singleShot(100, self._dfm_padding)
        else:
            self._chrome(True)
            for v in self.views:
                v.editor.SendScintilla(S.SCI_SETMARGINLEFT, 0, self.S["padding_left"])
                v.editor.SendScintilla(S.SCI_SETMARGINRIGHT, 0, self.S["padding_right"])
            if self._pre_states:
                fs, st, docks = self._pre_states
                if not fs:
                    self.showNormal()
                for k, vis in docks.items():
                    self.docks[k].setVisible(vis)

    def _dfm_padding(self):
        for v in self.views:
            ed = v.editor
            w = ed.viewport().width()
            text_w = ed.SendScintilla(S.SCI_TEXTWIDTH, S.STYLE_DEFAULT, b"M" * 100)
            pad = max(0, (w - text_w) // 2)
            ed.SendScintilla(S.SCI_SETMARGINLEFT, 0, pad)
            ed.SendScintilla(S.SCI_SETMARGINRIGHT, 0, pad)

    def view_in_browser(self, cmds):
        b = self.buf()
        if b is None or not b.path:
            return
        if b.dirty:
            self.save_buffer(b)
        for c in cmds:
            if shutil.which(c):
                self._spawn([c, b.path])
                return
        QMessageBox.information(self, "View Current File in", "%s is not installed." % cmds[0])

    def zoom(self, d):
        ed = self.editor()
        if d > 0:
            ed.SendScintilla(S.SCI_ZOOMIN)
        elif d < 0:
            ed.SendScintilla(S.SCI_ZOOMOUT)
        else:
            ed.SendScintilla(S.SCI_SETZOOM, 0)

    # ------------------------------------------------------- views and tabs
    def move_to_other_view(self):
        b = self.buf()
        if b is None:
            return
        src = self.active_view
        dst = self.other_view()
        if b in dst.buffers:
            src.remove(b)
        else:
            src.save_state(b)
            st = b.view_state.get(src.index)
            src.remove(b)
            if st:
                b.view_state[dst.index] = st
            self.show_view(dst)
            dst.add(b)
        self.set_active_view(dst)
        dst.activate(b)
        dst.editor.setFocus()
        self.after_view_change(src)

    def clone_to_other_view(self):
        b = self.buf()
        if b is None:
            return
        src = self.active_view
        src.save_state(b)
        dst = self.other_view()
        st = b.view_state.get(src.index)
        if st and dst.index not in b.view_state:
            b.view_state[dst.index] = dict(st)
        self.show_view(dst)
        dst.add(b)
        self.set_active_view(dst)
        dst.editor.setFocus()

    def self_command(self):
        app = os.environ.get("APPIMAGE")
        if app:
            return [app]
        return [sys.executable, "-m", "linbasic"]

    def to_new_instance(self, move):
        b = self.buf()
        if b is None or not b.path:
            QMessageBox.information(self, APP_NAME_(), "Save the document first.")
            return
        if move and b.dirty:
            if not self.save_buffer(b):
                return
        env_cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        args = self.self_command() + ["-multiInst", "-nosession", b.path]
        try:
            import subprocess
            env = dict(os.environ)
            if not os.environ.get("APPIMAGE"):
                env["PYTHONPATH"] = env_cwd + os.pathsep + env.get("PYTHONPATH", "")
            subprocess.Popen(args, env=env, start_new_session=True)
        except OSError:
            return
        if move:
            self.close_buffer(b, force=True)

    def goto_tab(self, i):
        v = self.active_view
        if not v.buffers:
            return
        if i < 0:
            i = len(v.buffers) - 1
        if i < len(v.buffers):
            v.activate(v.buffers[i])

    def switch_tab(self, d, mru=False):
        v = self.active_view
        if not v.buffers:
            return
        if mru and self.S["docswitcher_mru"]:
            order = sorted(v.buffers, key=lambda b: -b.last_access)
            i = order.index(v.current) if v.current in order else 0
            target = order[(i + d) % len(order)] if len(order) > 1 else order[0]
            v.activate(target)
            return
        i = v.index_of(v.current)
        v.activate(v.buffers[(i + d) % len(v.buffers)])

    def move_tab_to(self, pos):
        v = self.active_view
        i = v.index_of(v.current)
        if pos < 0:
            pos = len(v.buffers) - 1
        v.move_tab(i, pos)

    def move_tab_by(self, d):
        v = self.active_view
        i = v.index_of(v.current)
        v.move_tab(i, i + d)

    def tab_color(self, n):
        b = self.buf()
        if b:
            b.tab_color = n
            self.refresh_buffer_ui(b)

    def tab_double_clicked(self, view, i):
        if i < 0:
            self.set_active_view(view)
            self.new_document(view)
        elif self.S["tab_dblclick_close"]:
            self.close_buffer(view.buffer_at(i), view)

    def focus_other_view(self):
        o = self.other_view()
        if o.isVisible() and o.buffers:
            self.set_active_view(o)
            o.editor.setFocus()

    def toggle_sync(self, key):
        self.S[key] = not self.S[key]
        if self.S[key]:
            a, b = self.views[0].editor, self.views[1].editor
            self._sync_off = (a.first_visible_doc_line() - b.first_visible_doc_line(),
                              a.SendScintilla(S.SCI_GETXOFFSET) - b.SendScintilla(S.SCI_GETXOFFSET))

    def sync_scroll(self, ed):
        if not (self.S["sync_v"] or self.S["sync_h"]) or getattr(self, "_syncing", False):
            return
        o = self.views[1 - ed.view_index]
        if not o.isVisible() or o.current is None:
            return
        off = getattr(self, "_sync_off", (0, 0))
        sign = 1 if ed.view_index == 1 else -1
        self._syncing = True
        try:
            if self.S["sync_v"]:
                target = ed.first_visible_doc_line() + sign * off[0]
                o.editor.SendScintilla(S.SCI_SETFIRSTVISIBLELINE, max(0, o.editor.SendScintilla(S.SCI_VISIBLEFROMDOCLINE, target)))
            if self.S["sync_h"]:
                o.editor.SendScintilla(S.SCI_SETXOFFSET, max(0, ed.SendScintilla(S.SCI_GETXOFFSET) + sign * off[1]))
        finally:
            self._syncing = False

    def summary(self):
        b = self.buf()
        ed = self.editor()
        if b is None:
            return
        text = ed.all_text()
        import re
        words = len(re.findall(r"\w+", text))
        chars_no_eol = len(text) - text.count("\n") - text.count("\r")
        lines = ed.line_count()
        a, bb = ed.sel_range()
        sel = ed.get_range(a, bb)
        info = []
        if b.path:
            st = os.stat(b.path)
            info.append("Full file path: %s" % b.path)
            info.append("Created: %s" % time.strftime("%c", time.localtime(getattr(st, "st_birthtime", st.st_ctime))))
            info.append("Modified: %s" % time.strftime("%c", time.localtime(st.st_mtime)))
            info.append("")
        info.append("Characters (without line endings): {:,}".format(chars_no_eol))
        info.append("Words: {:,}".format(words))
        info.append("Lines: {:,}".format(lines))
        info.append("Document length: {:,}".format(ed.length()))
        sl = (ed.line_from_pos(bb) - ed.line_from_pos(a) + 1) if bb > a else 0
        info.append("{:,} selected characters ({:,} bytes) in {:,} ranges".format(len(sel), bb - a,
                                                                                  ed.SendScintilla(S.SCI_GETSELECTIONS) if bb > a else 0))
        QMessageBox.information(self, "Summary", "\n".join(info))

    def toggle_monitoring(self):
        b = self.buf()
        if b is None or not b.path:
            return
        if not b.monitoring and b.dirty:
            if not self.save_buffer(b):
                return
        b.monitoring = not b.monitoring
        self.set_buf_readonly(b)
        if b.monitoring:
            self.watch(b.path)
            self.reload_buffer(b, b.encoding, ask=False)
            if not getattr(self, "_mon_timer", None):
                self._mon_timer = QTimer(self)
                self._mon_timer.timeout.connect(self._monitor_tick)
                self._mon_timer.start(1000)

    def _monitor_tick(self):
        for b in self.all_buffers:
            if b.monitoring and b.path and os.path.exists(b.path):
                mt = os.path.getmtime(b.path)
                if mt != b.mtime:
                    b.mtime = mt
                    self.reload_buffer(b, b.encoding, ask=False)

    # ---------------------------------------------------------------- panels
    def show_panel(self, name, show=True):
        d = self.docks.get(name)
        if d is None:
            title, area, mod, cls = PANELS[name]
            import importlib
            m = importlib.import_module(".panels." + mod, __package__)
            panel = getattr(m, cls)(self, name)
            d = QDockWidget(title, self)
            d.setObjectName("dock_" + name)
            d.setWidget(panel)
            d.visibilityChanged.connect(lambda vis, n=name: self._dock_vis(n, vis))
            self.addDockWidget(area, d)
            if name == "results":
                self.resizeDocks([d], [180], Qt.Orientation.Vertical)
            else:
                self.resizeDocks([d], [260], Qt.Orientation.Horizontal)
            self.docks[name] = d
            self.panels[name] = panel
            if show is None:
                d.hide()
        if show:
            d.show()
            d.raise_()
        elif show is False:
            d.hide()
        return self.panels[name]

    def _dock_vis(self, name, vis):
        p = self.panels.get(name)
        if p is not None and vis and hasattr(p, "on_event"):
            p.on_event("shown", None)
        if hasattr(self, "actions"):
            self.sync_check_states()

    def toggle_panel(self, name):
        d = self.docks.get(name)
        if d is not None and d.isVisible():
            d.hide()
        else:
            self.show_panel(name, True)


def APP_NAME_():
    from . import APP_NAME
    return APP_NAME
