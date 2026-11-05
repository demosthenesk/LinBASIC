"""Search menu (43001-43069, bookmarks, styles of tokens) and the highlighting
that follows the caret (smart highlight, tag match, clickable links)."""
import os
import re

import regex
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (QApplication, QMessageBox, QWidget, QHBoxLayout, QLabel, QLineEdit,
                             QToolButton, QCheckBox)
from PyQt6.Qsci import QsciScintilla as S

from . import search as srch, styles as stl

URL_RX = regex.compile(r"""(?:(?:https?|ftp|file|mailto):(?://)?|www\.)[^\s<>"'`{}|\\^\[\]]+[^\s<>"'`{}|\\^\[\].,;:!?)]""", regex.I)


class FindInFilesWorker(QThread):
    file_done = pyqtSignal(str, list)      # path, [(line_no, line_text, [(cs, ce)])]
    progress = pyqtSignal(int, str)
    finished_all = pyqtSignal(int, int, int)  # hits, files with hits, files searched

    def __init__(self, files_iter, rx, replace=None, opts=None, settings=None):
        super().__init__()
        self.files_iter = files_iter
        self.rx = rx
        self.replace = replace
        self.opts = opts
        self.settings = settings
        self.cancel = False

    def run(self):
        from . import encodings_util as enc
        hits = nfiles = searched = 0
        for path in self.files_iter:
            if self.cancel:
                break
            searched += 1
            if searched % 25 == 0:
                self.progress.emit(searched, path)
            try:
                if os.path.getsize(path) > 200 * 1024 * 1024:
                    continue
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if b"\0" in data[:8000] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            e, text = enc.detect(data, self.settings)
            res = []
            lines_cache = None
            line_starts = None
            for m in srch.iter_matches(self.rx, text):
                if line_starts is None:
                    line_starts = [0] + [mm.end() for mm in re.finditer(r"\r\n|\r|\n", text)]
                import bisect
                ln = bisect.bisect_right(line_starts, m.start()) - 1
                ls = line_starts[ln]
                le = line_starts[ln + 1] if ln + 1 < len(line_starts) else len(text)
                lt = text[ls:le].rstrip("\r\n")
                if res and res[-1][0] == ln:
                    res[-1][2].append((m.start() - ls, min(m.end() - ls, len(lt))))
                else:
                    res.append([ln, lt, [(m.start() - ls, min(m.end() - ls, len(lt)))]])
            if res:
                nfiles += 1
                hits += sum(len(r[2]) for r in res)
                if self.replace is not None:
                    new = self.rx.sub(lambda m: srch.expand_replacement(m, self.replace, self.opts.mode), text)
                    if new != text:
                        try:
                            with open(path, "wb") as f:
                                f.write(enc.encode(new, e, self.settings))
                        except OSError:
                            pass
                self.file_done.emit(path, [(r[0], r[1], r[2]) for r in res])
        self.finished_all.emit(hits, nfiles, searched)


class IncrementalBar(QWidget):
    def __init__(self, main):
        super().__init__()
        self.main = main
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.clicked.connect(self.hide)
        self.edit = QLineEdit()
        self.edit.setMaximumWidth(300)
        prev = QToolButton()
        prev.setText("<")
        nxt = QToolButton()
        nxt.setText(">")
        self.case = QCheckBox("Match &case")
        self.hl = QCheckBox("&Highlight all")
        self.status = QLabel()
        for w in (close, QLabel("Find:"), self.edit, prev, nxt, self.case, self.hl, self.status):
            lay.addWidget(w)
        lay.addStretch(1)
        self.edit.textChanged.connect(lambda: self.search(0))
        self.edit.returnPressed.connect(lambda: self.search(1))
        prev.clicked.connect(lambda: self.search(-1))
        nxt.clicked.connect(lambda: self.search(1))
        self.case.toggled.connect(lambda: self.search(0))
        self.hl.toggled.connect(lambda: self.search(0))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.hide()
            self.main.editor().setFocus()
            return
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.search(-1)
            return
        super().keyPressEvent(e)

    def hideEvent(self, e):
        ed = self.main.editor()
        ed.indicator_clear(stl.IND_INC)
        super().hideEvent(e)

    def search(self, direction):
        ed = self.main.editor()
        t = self.edit.text()
        ed.indicator_clear(stl.IND_INC)
        if not t:
            self.status.setText("")
            self.edit.setStyleSheet("")
            return
        opts = srch.Opts(t, match_case=self.case.isChecked(), wrap=True, backward=direction < 0)
        a, b = ed.sel_range()
        start = a if direction == 0 else (b if direction > 0 else a)
        r, wrapped = self.main.find_in_editor(ed, opts, start=start)
        if r:
            ed.goto_pos(r[1], r[0])
            self.edit.setStyleSheet("")
            self.status.setText("Reached end of page, continued from top" if wrapped else "")
        else:
            self.edit.setStyleSheet("background:#FF6666;")
            self.status.setText("Phrase not found")
        if self.hl.isChecked():
            dt = srch.DocText(ed.get_bytes())
            rx = srch.compile_opts(opts)
            bm = srch.ByteMapper(dt.text)
            n = 0
            for m in srch.iter_matches(rx, dt.text):
                if m.end() > m.start():
                    s = bm.to_byte(m.start())
                    e = bm.to_byte(m.end())
                    ed.indicator_fill(stl.IND_INC, s, e - s)
                    n += 1
            self.status.setText((self.status.text() + "  " if self.status.text() else "") + "%d matches" % n)


class SearchMixin:
    def search_handlers(self):
        h = {
            43001: lambda: self.show_find(0), 43003: lambda: self.show_find(1),
            43013: lambda: self.show_find(2), 43054: lambda: self.show_find(4),
            43002: lambda: self.find_again(False), 43010: lambda: self.find_again(True),
            43048: lambda: self.select_and_find(False), 43049: lambda: self.select_and_find(True),
            43014: lambda: self.find_volatile(False), 43015: lambda: self.find_volatile(True),
            43011: self.show_incremental,
            43045: lambda: self.toggle_panel("results"),
            43046: lambda: self.results_panel().navigate(1),
            43047: lambda: self.results_panel().navigate(-1),
            43004: self.goto_dialog,
            43009: self.goto_brace, 43053: self.select_between_braces,
            43067: lambda: self.goto_change(True), 43068: lambda: self.goto_change(False),
            43069: self.clear_change_history,
            43005: lambda: self.toggle_bookmark(self.editor(), None),
            43006: lambda: self.next_bookmark(True), 43007: lambda: self.next_bookmark(False),
            43008: self.clear_bookmarks, 43018: lambda: self.bookmarked_lines("cut"),
            43019: lambda: self.bookmarked_lines("copy"), 43020: lambda: self.bookmarked_lines("paste"),
            43021: lambda: self.bookmarked_lines("remove"), 43051: lambda: self.bookmarked_lines("remove_unmarked"),
            43050: lambda: self.bookmarked_lines("inverse"),
            43052: self.find_chars_in_range,
            43032: self.clear_all_styles,
        }
        for i, (all_id, one_id, clr, up, down, cp) in enumerate(zip(
                (43022, 43024, 43026, 43028, 43030), (43062, 43063, 43064, 43065, 43066),
                (43023, 43025, 43027, 43029, 43031), (43033, 43034, 43035, 43036, 43037),
                (43039, 43040, 43041, 43042, 43043), (43055, 43056, 43057, 43058, 43059))):
            ind = stl.MARK_STYLE_INDICS[i]
            h[all_id] = lambda ind=ind: self.style_token(ind, True)
            h[one_id] = lambda ind=ind: self.style_token(ind, False)
            h[clr] = lambda ind=ind: self.editor().indicator_clear(ind)
            h[up] = lambda ind=ind: self.jump_indicator([ind], False)
            h[down] = lambda ind=ind: self.jump_indicator([ind], True)
            h[cp] = lambda ind=ind: self.copy_styled([ind])
        h[43038] = lambda: self.jump_indicator([stl.IND_FOUND], False)
        h[43044] = lambda: self.jump_indicator([stl.IND_FOUND], True)
        h[43060] = lambda: self.copy_styled(stl.MARK_STYLE_INDICS)
        h[43061] = lambda: self.copy_styled([stl.IND_FOUND])
        return h

    # ------------------------------------------------------------ find core
    def find_in_editor(self, ed, opts, start=None, range_=None):
        """Return ((byte_start, byte_end), wrapped) or (None, False)."""
        try:
            rx = srch.compile_opts(opts, self.S["extra_word_chars"])
        except regex.error as ex:
            raise ValueError(str(ex))
        dt = srch.DocText(ed.get_bytes())
        if range_ is None:
            r0, r1 = 0, len(dt.text)
        else:
            r0, r1 = dt.b2c(range_[0]), dt.b2c(range_[1])
        if start is None:
            a, b = ed.sel_range()
            start = a if opts.backward else b
        cs = min(max(dt.b2c(start), r0), r1)

        def fwd(lo, hi):
            for m in srch.iter_matches(rx, dt.text, lo, hi):
                return m
            return None

        def back(lo, hi):
            last = None
            for m in srch.iter_matches(rx, dt.text, lo, hi):
                if m.start() >= hi or (m.end() > hi):
                    break
                if m.start() == m.end() == hi:
                    break
                last = m
            return last

        wrapped = False
        if not opts.backward:
            m = fwd(cs, r1)
            if m is None and opts.wrap:
                m = fwd(r0, r1)
                wrapped = m is not None
        else:
            m = back(r0, cs)
            if m is None and opts.wrap:
                m = back(r0, r1)
                wrapped = m is not None
        if m is None:
            return None, False
        return (dt.c2b(m.start()), dt.c2b(m.end())), wrapped

    def all_matches(self, ed, opts, range_=None):
        """[(byte_start, byte_end, match)] over the document or a byte range."""
        rx = srch.compile_opts(opts, self.S["extra_word_chars"])
        dt = srch.DocText(ed.get_bytes())
        lo, hi = 0, len(dt.text)
        if range_ is not None:
            lo, hi = dt.b2c(range_[0]), dt.b2c(range_[1])
        bm = srch.ByteMapper(dt.text)
        out = []
        for m in srch.iter_matches(rx, dt.text, lo, hi):
            out.append((bm.to_byte(m.start()), bm.to_byte(m.end()), m))
        return out, dt

    def set_find_status(self, msg, kind="msg"):
        if self.find_dlg is not None and self.find_dlg.isVisible():
            self.find_dlg.set_status(msg, kind)
        else:
            self.statusBar().showMessage(msg, 4000)

    def do_find(self, opts, ed=None, quiet=False):
        ed = ed or self.editor()
        if not opts.text:
            return False
        self.find_opts_last = opts
        rng = None
        if opts.in_selection:
            rng = ed.sel_range()
            opts = opts.copy(wrap=True)
        try:
            r, wrapped = self.find_in_editor(ed, opts, range_=rng)
        except ValueError as ex:
            self.set_find_status("Find: Invalid regular expression", "err")
            return False
        if r is None:
            if not quiet:
                self.set_find_status('Find: Can\'t find the text "%s"' % opts.text, "err")
            return False
        if opts.in_selection:
            return True
        ed.goto_pos(r[1] if not opts.backward else r[0], r[0] if not opts.backward else r[1])
        if opts.backward:
            ed.set_sel(r[1], r[0])
        if wrapped:
            self.set_find_status("Find: Found the 1st occurrence from the %s. The %s of the document has been reached."
                                 % ("bottom" if opts.backward else "top", "beginning" if opts.backward else "end"), "end")
        else:
            self.set_find_status("", "msg")
        return True

    def find_again(self, backward):
        opts = self.find_opts_last
        if self.find_dlg is not None:
            opts = self.find_dlg.current_opts()
        if opts is None or not opts.text:
            self.show_find(0)
            return
        self.do_find(opts.copy(backward=backward, in_selection=False))

    def select_and_find(self, backward):
        ed = self.editor()
        t = ed.sel_text()
        if not t:
            a, b = ed.word_at()
            if a == b:
                return
            ed.set_sel(a, b)
            t = ed.get_range(a, b)
        base = self.find_opts_last or srch.Opts()
        opts = base.copy(text=t, mode=srch.MODE_NORMAL, backward=backward, in_selection=False, wrap=True)
        if self.find_dlg is not None:
            self.find_dlg.set_find_text(t)
        self.do_find(opts)

    def find_volatile(self, backward):
        ed = self.editor()
        t = ed.sel_text()
        if not t:
            a, b = ed.word_at()
            t = ed.get_range(a, b)
        if t:
            self.do_find(srch.Opts(t, match_case=False, whole_word=False, wrap=True, backward=backward))

    def do_replace(self, opts):
        ed = self.editor()
        if ed.SendScintilla(S.SCI_GETREADONLY):
            self.set_find_status("Replace: Cannot replace text. The current document is read only.", "err")
            return
        a, b = ed.sel_range()
        try:
            rx = srch.compile_opts(opts, self.S["extra_word_chars"])
        except regex.error:
            self.set_find_status("Replace: Invalid regular expression", "err")
            return
        sel = ed.get_range(a, b)
        m = rx.fullmatch(sel) if sel else None
        if m is not None and not opts.in_selection:
            # rematch in context so lookarounds/\K behave
            dt = srch.DocText(ed.get_bytes())
            ca = dt.b2c(a)
            mm = rx.match(dt.text, ca)
            if mm is not None and mm.end() == dt.b2c(b):
                m = mm
            rep = srch.expand_replacement(m, opts.replace, opts.mode)
            n = ed.replace_range(a, b, rep)
            ed.set_sel(a + n, a + n)
            if self.S["replace_no_move"]:
                ed.set_sel(a, a + n)
                self.set_find_status("Replace: 1 occurrence was replaced.", "msg")
                return
            found = self.do_find(opts.copy(backward=False, in_selection=False), quiet=True)
            self.set_find_status("Replace: 1 occurrence was replaced. " +
                                 ("The next occurrence found." if found else "No more occurrences."), "msg")
            return
        if not self.do_find(opts.copy(in_selection=False), quiet=True):
            self.set_find_status("Replace: no occurrence was found.", "err")

    def replace_all_in(self, ed, opts):
        if ed.SendScintilla(S.SCI_GETREADONLY):
            return -1
        rng = ed.sel_range() if opts.in_selection else None
        try:
            matches, dt = self.all_matches(ed, opts, rng)
        except regex.error:
            return -2
        if not matches:
            return 0
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        delta = 0
        for s, e, m in reversed(matches):
            ed.replace_range(s, e, srch.expand_replacement(m, opts.replace, opts.mode))
        ed.SendScintilla(S.SCI_ENDUNDOACTION)
        return len(matches)

    def do_replace_all(self, opts, all_docs=False):
        if all_docs:
            if self.S["confirm_replace_all_docs"]:
                r = QMessageBox.question(self, "Replace All", "Are you sure you want to replace all occurrences in all open documents?")
                if r != QMessageBox.StandardButton.Yes:
                    return
            total = 0
            for b in list(self.all_buffers):
                with self.doc_editor(b) as ed:
                    n = self.replace_all_in(ed, opts.copy(in_selection=False))
                    if n > 0:
                        total += n
            self.set_find_status("Replace in Opened Files: %d occurrences replaced" % total, "msg")
            return
        n = self.replace_all_in(self.editor(), opts)
        if n == -1:
            self.set_find_status("Replace All: Cannot replace text. The current document is read only.", "err")
        elif n == -2:
            self.set_find_status("Replace All: Invalid regular expression", "err")
        else:
            where = "selected text" if opts.in_selection else "entire file"
            self.set_find_status("Replace All: %d occurrence%s replaced in %s" % (n, "s were" if n != 1 else " was", where),
                                 "msg" if n else "err")

    def do_count(self, opts):
        ed = self.editor()
        try:
            matches, _ = self.all_matches(ed, opts, ed.sel_range() if opts.in_selection else None)
        except regex.error:
            self.set_find_status("Count: Invalid regular expression", "err")
            return
        where = "selected text" if opts.in_selection else "entire file"
        self.set_find_status("Count: %d match%s in %s" % (len(matches), "es" if len(matches) != 1 else "", where),
                             "msg" if matches else "err")

    def do_mark(self, opts, bookmark=False, purge=False):
        ed = self.editor()
        if purge:
            ed.indicator_clear(stl.IND_FOUND)
            if bookmark:
                ed.SendScintilla(S.SCI_MARKERDELETEALL, stl.MARK_BOOKMARK)
        try:
            matches, _ = self.all_matches(ed, opts, ed.sel_range() if opts.in_selection else None)
        except regex.error:
            self.set_find_status("Mark: Invalid regular expression", "err")
            return
        for s, e, m in matches:
            if e > s:
                ed.indicator_fill(stl.IND_FOUND, s, e - s)
            if bookmark:
                line = ed.line_from_pos(s)
                if not ed.SendScintilla(S.SCI_MARKERGET, line) & (1 << stl.MARK_BOOKMARK):
                    ed.SendScintilla(S.SCI_MARKERADD, line, stl.MARK_BOOKMARK)
        where = "selected text" if opts.in_selection else "entire file"
        self.set_find_status("Mark: %d match%s in %s" % (len(matches), "es" if len(matches) != 1 else "", where),
                             "msg" if matches else "err")

    def clear_marks(self):
        self.editor().indicator_clear(stl.IND_FOUND)
        self.set_find_status("", "msg")

    def copy_marked(self):
        self.copy_styled([stl.IND_FOUND])

    def find_all(self, opts, buffers):
        rp = self.results_panel()
        rp.begin_search(opts.text)
        total = files = 0
        for b in buffers:
            with self.doc_editor(b) as ed:
                try:
                    matches, dt = self.all_matches(ed, opts.copy(in_selection=False))
                except regex.error:
                    self.set_find_status("Find: Invalid regular expression", "err")
                    return
                if not matches:
                    continue
                hits = []
                for s, e, m in matches:
                    line = ed.line_from_pos(s)
                    ls = ed.line_start(line)
                    lt = ed.get_range(ls, ed.line_end(line))
                    cs = len(ed.get_bytes(ls, s).decode("utf-8", "replace"))
                    ce = cs + len(ed.get_bytes(s, min(e, ed.line_end(line))).decode("utf-8", "replace"))
                    if hits and hits[-1][0] == line:
                        hits[-1][2].append((cs, ce))
                    else:
                        hits.append((line, lt, [(cs, ce)]))
                rp.add_file(b.full_name(), hits, buffer=b)
                total += len(matches)
                files += 1
        rp.end_search(total, files, len(buffers))
        self.show_panel("results", True)
        if total == 0:
            self.set_find_status("Find All: no occurrence was found.", "err")

    def find_in_files(self, opts, directory, filters, recursive, hidden, replace=False):
        if not directory or not os.path.isdir(directory):
            self.set_find_status("Find in Files: The directory doesn't exist.", "err")
            return
        try:
            rx = srch.compile_opts(opts, self.S["extra_word_chars"])
        except regex.error:
            self.set_find_status("Find in Files: Invalid regular expression", "err")
            return
        if replace:
            r = QMessageBox.question(self, "Replace in Files",
                                     'Are you sure you want to replace all occurrence(s) of :\n"%s"\nwith :\n"%s"\nin all files of "%s"?'
                                     % (opts.text, opts.replace, directory))
            if r != QMessageBox.StandardButton.Yes:
                return
            # save open buffers of affected files first, like Notepad++
        rp = self.results_panel()
        rp.begin_search(opts.text, in_files=True)
        self.show_panel("results", True)
        files = srch.walk_files(directory, filters, recursive, hidden)
        w = FindInFilesWorker(files, rx, opts.replace if replace else None, opts, self.S)
        self._fif_worker = w
        w.file_done.connect(lambda p, hits: rp.add_file(p, hits))
        w.progress.connect(lambda n, p: self.set_find_status("Searching (%d files): %s" % (n, p), "msg"))

        def done(hits, nfiles, searched):
            rp.end_search(hits, nfiles, searched)
            self.set_find_status("%s: %d occurrence%s in %d file%s of %d searched" %
                                 ("Replace in Files" if replace else "Find in Files", hits, "s" if hits != 1 else "",
                                  nfiles, "s" if nfiles != 1 else "", searched), "msg" if hits else "err")
            if replace:
                for b in self.all_buffers:
                    if b.path and b.path.startswith(os.path.abspath(directory)) and not b.dirty:
                        self.reload_buffer(b, None, ask=False)
        w.finished_all.connect(done)
        w.start()

    # ------------------------------------------------------------- dialogs
    def show_find(self, tab):
        from .dialogs.find import FindDialog
        if self.find_dlg is None:
            self.find_dlg = FindDialog(self)
        ed = self.editor()
        sel = ed.sel_text()
        if sel and "\n" not in sel and len(sel) <= self.S["find_maxchars"] and self.S["find_fill_selected"]:
            self.find_dlg.set_find_text(sel)
        elif not sel and self.S["find_fill_word"]:
            a, b = ed.word_at()
            if b > a:
                self.find_dlg.set_find_text(ed.get_range(a, b))
        a, b = ed.sel_range()
        self.find_dlg.set_in_selection(self.S["find_in_sel_auto"] and (b - a) >= self.S["find_in_sel_min"]
                                       or (sel.count("\n") > 0 and self.S["find_in_sel_auto"]))
        self.find_dlg.show_tab(tab)

    def show_incremental(self):
        self.inc_bar.show()
        t = self.editor().sel_text()
        if t and "\n" not in t:
            self.inc_bar.edit.setText(t)
        self.inc_bar.edit.setFocus()
        self.inc_bar.edit.selectAll()

    def build_incremental_bar(self):
        from PyQt6.QtWidgets import QVBoxLayout
        self.inc_bar = IncrementalBar(self)
        self.inc_bar.hide()
        old = self.takeCentralWidget()
        c = QWidget()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(old, 1)
        lay.addWidget(self.inc_bar)
        self.setCentralWidget(c)

    def goto_dialog(self):
        from .dialogs.misc import GotoDialog
        GotoDialog(self).exec()

    def find_chars_in_range(self):
        from .dialogs.misc import CharRangeDialog
        if getattr(self, "_charrange", None) is None:
            self._charrange = CharRangeDialog(self)
        self._charrange.show()
        self._charrange.raise_()

    def results_panel(self):
        return self.show_panel("results", None)

    # ---------------------------------------------------------------- braces
    def goto_brace(self):
        ed = self.editor()
        p = ed.pos()
        for q in (p, p - 1):
            if q < 0:
                continue
            m = ed.SendScintilla(S.SCI_BRACEMATCH, q, 0)
            if m >= 0:
                ed.goto_pos(m)
                return

    def select_between_braces(self):
        ed = self.editor()
        text = ed.all_text()
        dt = srch.DocText(ed.get_bytes())
        c = dt.b2c(ed.pos())
        pairs = {"(": ")", "[": "]", "{": "}"}
        depth = {k: 0 for k in pairs}
        i = c - 1
        stack = []
        while i >= 0:
            ch = text[i]
            if ch in ")]}":
                stack.append(ch)
            elif ch in pairs:
                if stack and stack[-1] == pairs[ch]:
                    stack.pop()
                elif not stack:
                    bs = dt.c2b(i)
                    m = ed.SendScintilla(S.SCI_BRACEMATCH, bs, 0)
                    if m > bs:
                        ed.set_sel(bs + 1, m)
                        return
            i -= 1

    # -------------------------------------------------------- change history
    def change_history_mark(self, ed, pos, mtype, length, added):
        line = ed.line_from_pos(pos)
        last = line + max(0, added)
        snd = ed.SendScintilla
        for ln in range(line, min(last, ed.line_count() - 1) + 1):
            mask = snd(S.SCI_MARKERGET, ln)
            if mask & (1 << stl.MARK_CH_SAVED):
                snd(S.SCI_MARKERDELETE, ln, stl.MARK_CH_SAVED)
            if not mask & (1 << stl.MARK_CH_MODIFIED):
                snd(S.SCI_MARKERADD, ln, stl.MARK_CH_MODIFIED)

    def change_history_saved(self, ed):
        snd = ed.SendScintilla
        line = snd(S.SCI_MARKERNEXT, 0, 1 << stl.MARK_CH_MODIFIED)
        while line >= 0:
            snd(S.SCI_MARKERDELETE, line, stl.MARK_CH_MODIFIED)
            snd(S.SCI_MARKERADD, line, stl.MARK_CH_SAVED)
            line = snd(S.SCI_MARKERNEXT, line + 1, 1 << stl.MARK_CH_MODIFIED)

    def goto_change(self, forward):
        ed = self.editor()
        mask = (1 << stl.MARK_CH_MODIFIED) | (1 << stl.MARK_CH_SAVED)
        line = ed.line_from_pos(ed.pos())
        snd = ed.SendScintilla
        # skip the block the caret is in
        if forward:
            ln = line
            while ln < ed.line_count() and snd(S.SCI_MARKERGET, ln) & mask:
                ln += 1
            nxt = snd(S.SCI_MARKERNEXT, ln, mask)
            if nxt < 0:
                nxt = snd(S.SCI_MARKERNEXT, 0, mask)
        else:
            ln = line
            while ln >= 0 and snd(S.SCI_MARKERGET, ln) & mask:
                ln -= 1
            nxt = snd(S.SCI_MARKERPREVIOUS, ln, mask) if ln >= 0 else -1
            if nxt < 0:
                nxt = snd(S.SCI_MARKERPREVIOUS, ed.line_count() - 1, mask)
            while nxt > 0 and snd(S.SCI_MARKERGET, nxt - 1) & mask:
                nxt -= 1
        if nxt >= 0:
            ed.goto_line(nxt)

    def clear_change_history(self):
        ed = self.editor()
        ed.SendScintilla(S.SCI_MARKERDELETEALL, stl.MARK_CH_MODIFIED)
        ed.SendScintilla(S.SCI_MARKERDELETEALL, stl.MARK_CH_SAVED)

    # ------------------------------------------------------------- bookmarks
    def toggle_bookmark(self, ed, line):
        if line is None:
            line = ed.line_from_pos(ed.pos())
        if ed.SendScintilla(S.SCI_MARKERGET, line) & (1 << stl.MARK_BOOKMARK):
            ed.SendScintilla(S.SCI_MARKERDELETE, line, stl.MARK_BOOKMARK)
        else:
            ed.SendScintilla(S.SCI_MARKERADD, line, stl.MARK_BOOKMARK)
        self.panel_event("bookmarks", ed)

    def next_bookmark(self, forward):
        ed = self.editor()
        line = ed.line_from_pos(ed.pos())
        m = 1 << stl.MARK_BOOKMARK
        if forward:
            n = ed.SendScintilla(S.SCI_MARKERNEXT, line + 1, m)
            if n < 0:
                n = ed.SendScintilla(S.SCI_MARKERNEXT, 0, m)
        else:
            n = ed.SendScintilla(S.SCI_MARKERPREVIOUS, line - 1, m) if line > 0 else -1
            if n < 0:
                n = ed.SendScintilla(S.SCI_MARKERPREVIOUS, ed.line_count() - 1, m)
        if n >= 0:
            ed.goto_line(n)

    def clear_bookmarks(self):
        self.editor().SendScintilla(S.SCI_MARKERDELETEALL, stl.MARK_BOOKMARK)

    def bookmark_lines(self, ed):
        out = []
        m = 1 << stl.MARK_BOOKMARK
        n = ed.SendScintilla(S.SCI_MARKERNEXT, 0, m)
        while n >= 0:
            out.append(n)
            n = ed.SendScintilla(S.SCI_MARKERNEXT, n + 1, m)
        return out

    def bookmarked_lines(self, op):
        ed = self.editor()
        marked = self.bookmark_lines(ed)
        snd = ed.SendScintilla
        if op == "inverse":
            ms = set(marked)
            for ln in range(ed.line_count()):
                if ln in ms:
                    snd(S.SCI_MARKERDELETE, ln, stl.MARK_BOOKMARK)
                else:
                    snd(S.SCI_MARKERADD, ln, stl.MARK_BOOKMARK)
            return
        if op in ("cut", "copy"):
            parts = []
            for ln in marked:
                s = ed.line_start(ln)
                e = ed.line_start(ln + 1) if ln + 1 < ed.line_count() else ed.length()
                parts.append(ed.get_range(s, e))
            if parts:
                txt = "".join(parts)
                if not re.search(r"(\r\n|\r|\n)$", txt):
                    txt += self.eol_str(ed)
                QApplication.clipboard().setText(txt)
            if op == "copy":
                return
        if op == "paste":
            clip = QApplication.clipboard().text()
            if not clip:
                return
            snd(S.SCI_BEGINUNDOACTION)
            for ln in reversed(marked):
                ed.replace_range(ed.line_start(ln), ed.line_end(ln), clip.rstrip("\r\n"))
            snd(S.SCI_ENDUNDOACTION)
            return
        if op in ("cut", "remove", "remove_unmarked"):
            if op == "remove_unmarked":
                ms = set(marked)
                targets = [ln for ln in range(ed.line_count()) if ln not in ms]
            else:
                targets = marked
            snd(S.SCI_BEGINUNDOACTION)
            for ln in reversed(targets):
                s = ed.line_start(ln)
                e = ed.line_start(ln + 1) if ln + 1 < ed.line_count() else ed.length()
                if ln + 1 >= ed.line_count() and ln > 0:
                    s = ed.line_end(ln - 1)
                ed.replace_range(s, e, "")
            snd(S.SCI_ENDUNDOACTION)

    # ------------------------------------------------------- style of tokens
    def style_token(self, ind, all_):
        ed = self.editor()
        a, b = ed.sel_range()
        if a == b:
            a, b = ed.word_at()
            if a == b:
                return
        if not all_:
            ed.indicator_fill(ind, a, b - a)
            return
        t = ed.get_range(a, b)
        opts = srch.Opts(t, match_case=self.S["token_match_case"], whole_word=self.S["token_whole_word"])
        matches, _ = self.all_matches(ed, opts)
        for s, e, m in matches:
            ed.indicator_fill(ind, s, e - s)

    def clear_all_styles(self):
        ed = self.editor()
        for ind in stl.MARK_STYLE_INDICS + [stl.IND_FOUND]:
            ed.indicator_clear(ind)

    def indicator_runs(self, ed, ind):
        out = []
        n = ed.length()
        p = 0
        snd = ed.SendScintilla
        while p < n:
            e = snd(S.SCI_INDICATOREND, ind, p)
            if e <= p:
                break
            if snd(S.SCI_INDICATORVALUEAT, ind, p):
                out.append((p, e))
            p = e
        return out

    def jump_indicator(self, inds, forward):
        ed = self.editor()
        runs = sorted(r for ind in inds for r in self.indicator_runs(ed, ind))
        if not runs:
            return
        a, b = ed.sel_range()
        if forward:
            nxt = next((r for r in runs if r[0] >= b and (r[0], r[1]) != (a, b)), runs[0])
        else:
            prev = [r for r in runs if r[1] <= a and (r[0], r[1]) != (a, b)]
            nxt = prev[-1] if prev else runs[-1]
        ed.goto_pos(nxt[1], nxt[0])

    def copy_styled(self, inds):
        ed = self.editor()
        runs = sorted(r for ind in inds for r in self.indicator_runs(ed, ind))
        if runs:
            QApplication.clipboard().setText(self.eol_str(ed).join(ed.get_range(a, b) for a, b in runs))

    # ------------------------------------------------ caret-driven highlights
    def update_smart_highlight(self, ed, force=False):
        if ed.view_index < 0 or ed.buffer is None:
            return
        snd = ed.SendScintilla
        v0, v1 = ed.visible_range()
        key = (id(ed), ed.sel_range(), v0, v1, ed.buffer)
        if not force and getattr(ed, "_smart_key", None) == key:
            return
        ed._smart_key = key
        targets = [ed]
        if self.S["smart_hl_other_view"]:
            ov = self.other_view(self.views[ed.view_index]).editor
            if ov.isVisible() and ov.buffer is not None:
                targets.append(ov)
        for t in targets:
            t.indicator_clear(stl.IND_SMART)
        if not self.S["smart_hl"] or (ed.buffer.large and not self.S["large_smart"]):
            return
        if snd(S.SCI_GETSELECTIONS) != 1:
            return
        a, b = ed.sel_range()
        if a == b or b - a > 2000:
            return
        word = ed.get_bytes(a, b)
        if b"\n" in word or b"\r" in word or not word.strip():
            return
        flags = 0
        if self.S["smart_hl_use_find"] and self.find_opts_last is not None:
            if self.find_opts_last.match_case:
                flags |= S.SCFIND_MATCHCASE
            if self.find_opts_last.whole_word:
                flags |= S.SCFIND_WHOLEWORD
        else:
            if self.S["smart_hl_case"]:
                flags |= S.SCFIND_MATCHCASE
            if self.S["smart_hl_word"]:
                wa, wb = ed.word_at(a)
                if (wa, wb) != (a, b):
                    return
                flags |= S.SCFIND_WHOLEWORD
        for t in targets:
            t0, t1 = t.visible_range()
            t.SendScintilla(S.SCI_SETSEARCHFLAGS, flags)
            p = t0
            guard = 0
            while p < t1 and guard < 5000:
                guard += 1
                t.SendScintilla(S.SCI_SETTARGETRANGE, p, t1)
                r = t.SendScintilla(S.SCI_SEARCHINTARGET, len(word), word)
                if r < 0:
                    break
                e = t.SendScintilla(S.SCI_GETTARGETEND)
                t.indicator_fill(stl.IND_SMART, r, e - r)
                p = e if e > r else r + 1

    def update_tag_match(self, ed):
        if ed.buffer is None:
            return
        ed.indicator_clear(stl.IND_TAGMATCH)
        ed.indicator_clear(stl.IND_TAGATTR)
        if not self.S["tag_match"] or ed.buffer.lang not in ("html", "xml", "php", "asp", "jsp"):
            return
        if ed.length() > 2_000_000:
            return
        dt = srch.DocText(ed.get_bytes())
        text = dt.text
        c = dt.b2c(ed.pos())
        lt = text.rfind("<", 0, c + 1)
        if lt < 0 or text.rfind(">", lt, c) >= 0:
            return
        gt = text.find(">", lt)
        if gt < 0:
            return
        m = re.match(r"<(/?)([A-Za-z_][\w:.-]*)", text[lt:gt + 1])
        if not m:
            return
        closing, name = m.group(1) == "/", m.group(2)
        rx = re.compile(r"<(/?)%s(?=[\s/>])[^>]*?(/?)>" % re.escape(name))
        pair = None
        if not closing:
            if text[gt - 1] == "/":
                pair = None
            else:
                depth = 0
                for mm in rx.finditer(text, gt + 1):
                    if mm.group(2):
                        continue
                    if mm.group(1):
                        if depth == 0:
                            pair = mm.start()
                            break
                        depth -= 1
                    else:
                        depth += 1
        else:
            stack = []
            for mm in rx.finditer(text, 0, lt):
                if mm.group(2):
                    continue
                if mm.group(1):
                    if stack:
                        stack.pop()
                else:
                    stack.append(mm.start())
            pair = stack[-1] if stack else None

        def mark(start):
            mm = re.match(r"</?([A-Za-z_][\w:.-]*)", text[start:])
            s = dt.c2b(start + (2 if text[start + 1] == "/" else 1))
            ed.indicator_fill(stl.IND_TAGMATCH, s, len(mm.group(1).encode()))
        mark(lt)
        if pair is not None:
            mark(pair)
        if self.S["tag_attr"]:
            open_start = pair if closing and pair is not None else lt
            open_end = text.find(">", open_start)
            for am in re.finditer(r"\s([\w:.-]+)\s*=", text[open_start:open_end]):
                s = dt.c2b(open_start + am.start(1))
                ed.indicator_fill(stl.IND_TAGATTR, s, len(am.group(1).encode()))

    def update_urls(self, ed):
        if ed.buffer is None:
            return
        v0, v1 = ed.visible_range()
        ed.indicator_clear(stl.IND_URL, v0, v1)
        if not self.S["link_enable"] or (ed.buffer.large and not self.S["large_links"]):
            return
        raw = ed.get_bytes(v0, v1)
        text = raw.decode("utf-8", "surrogateescape")
        bm = srch.ByteMapper(text)
        schemes = [s for s in self.S["uri_schemes"].split() if s]
        for m in URL_RX.finditer(text):
            s, e = bm.to_byte(m.start()), bm.to_byte(m.end())
            ed.indicator_fill(stl.IND_URL, v0 + s, e - s)
        if schemes:
            rx = regex.compile("(?:%s)[^\\s<>\"']+" % "|".join(regex.escape(x) for x in schemes))
            bm = srch.ByteMapper(text)
            for m in rx.finditer(text):
                s, e = bm.to_byte(m.start()), bm.to_byte(m.end())
                ed.indicator_fill(stl.IND_URL, v0 + s, e - s)
