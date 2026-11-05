"""Edit menu commands (42001-42106, 45001-45003, 50000-50011)."""
import locale
import os
import random
import re

from PyQt6.QtCore import QDateTime, QLocale, QMimeData, QUrl, Qt, QByteArray
from PyQt6.QtGui import QDesktopServices, QGuiApplication
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.Qsci import QsciScintilla as S

BIN_MIME = "application/x-linpad-binary"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
             "source", "track", "wbr", "keygen", "command"}


def _num_key(s, comma):
    m = re.match(r"\s*([+-]?\d+(?:%s\d+)?)" % (r"," if comma else r"\."), s)
    if not m:
        return None
    v = m.group(1).replace(",", ".") if comma else m.group(1)
    try:
        return float(v)
    except ValueError:
        return None


class EditMixin:
    def edit_handlers(self):
        e = self.editor
        h = {
            42003: lambda: e().undo(), 42004: lambda: e().redo(),
            42001: lambda: e().cut(), 42002: lambda: e().copy(), 42005: lambda: e().paste(),
            42006: lambda: e().SendScintilla(S.SCI_CLEAR), 42007: lambda: e().selectAll(),
            42020: lambda: self.begin_end_select(False), 42089: lambda: self.begin_end_select(True),
            42084: lambda: self.insert_datetime("short"), 42085: lambda: self.insert_datetime("long"),
            42086: lambda: self.insert_datetime("custom"),
            42029: lambda: self.copy_path("full"), 42030: lambda: self.copy_path("name"),
            42031: lambda: self.copy_path("dir"), 42087: lambda: self.copy_all("name"),
            42088: lambda: self.copy_all("full"),
            42008: lambda: e().SendScintilla(S.SCI_TAB), 42009: lambda: e().SendScintilla(S.SCI_BACKTAB),
            42016: lambda: e().SendScintilla(S.SCI_UPPERCASE), 42017: lambda: e().SendScintilla(S.SCI_LOWERCASE),
            42067: lambda: self.transform_sel(lambda t: self.proper_case(t, False)),
            42068: lambda: self.transform_sel(lambda t: self.proper_case(t, True)),
            42069: lambda: self.transform_sel(lambda t: self.sentence_case(t, False)),
            42070: lambda: self.transform_sel(lambda t: self.sentence_case(t, True)),
            42071: lambda: self.transform_sel(lambda t: t.swapcase()),
            42072: lambda: self.transform_sel(lambda t: "".join(c.upper() if random.random() < .5 else c.lower() for c in t)),
            42010: lambda: e().SendScintilla(S.SCI_LINEDUPLICATE),
            42079: lambda: self.line_op(self.op_dedupe, whole_if_none=True),
            42077: lambda: self.line_op(self.op_dedupe_consecutive, whole_if_none=True),
            42012: self.split_lines, 42013: lambda: self.join_lines(),
            42014: lambda: e().SendScintilla(S.SCI_MOVESELECTEDLINESUP),
            42015: lambda: e().SendScintilla(S.SCI_MOVESELECTEDLINESDOWN),
            42055: lambda: self.line_op(lambda ls: [l for l in ls if l != ""], whole_if_none=True),
            42056: lambda: self.line_op(lambda ls: [l for l in ls if l.strip() != ""], whole_if_none=True),
            42057: lambda: self.insert_blank(above=True), 42058: lambda: self.insert_blank(above=False),
            42083: lambda: self.line_op(lambda ls: ls[::-1], whole_if_none=True),
            42078: lambda: self.line_op(lambda ls: random.sample(ls, len(ls)), whole_if_none=True),
            42022: lambda: self.comment_lines("toggle"), 42035: lambda: self.comment_lines("comment"),
            42036: lambda: self.comment_lines("uncomment"), 42023: self.block_comment,
            42047: self.block_uncomment,
            50000: lambda: self.ac_complete(e(), "func", manual=True),
            50001: lambda: self.ac_complete(e(), "word", manual=True),
            50002: lambda: self.ac_calltip(e(), manual=True),
            50010: lambda: self.ac_calltip_cycle(e(), -1), 50011: lambda: self.ac_calltip_cycle(e(), 1),
            50006: lambda: self.ac_path(e()),
            45001: lambda: self.convert_eol(S.SC_EOL_CRLF), 45002: lambda: self.convert_eol(S.SC_EOL_LF),
            45003: lambda: self.convert_eol(S.SC_EOL_CR),
            42024: lambda: self.line_op(lambda ls: [l.rstrip(" \t") for l in ls], whole_if_none=True, keep_sel=True),
            42042: lambda: self.line_op(lambda ls: [l.lstrip(" \t") for l in ls], whole_if_none=True, keep_sel=True),
            42043: lambda: self.line_op(lambda ls: [l.strip(" \t") for l in ls], whole_if_none=True, keep_sel=True),
            42044: lambda: self.eol_to_space(False), 42045: lambda: self.eol_to_space(True),
            42046: lambda: self.line_op(self.op_tab_to_space, whole_if_none=True, keep_sel=True),
            42054: lambda: self.line_op(lambda ls: self.op_space_to_tab(ls, False), whole_if_none=True, keep_sel=True),
            42053: lambda: self.line_op(lambda ls: self.op_space_to_tab(ls, True), whole_if_none=True, keep_sel=True),
            42038: lambda: self.paste_mime(["text/html"]),
            42039: lambda: self.paste_mime(["text/rtf", "application/rtf", "text/richtext"]),
            42048: lambda: self.copy_binary(cut=False), 42049: lambda: self.copy_binary(cut=True),
            42050: self.paste_binary,
            42073: self.sel_open_file, 42074: self.sel_open_folder, 42106: self.redact_selection,
            42075: self.search_internet, 42076: lambda: self.open_preferences("Search Engine"),
            42037: self.column_mode_help, 42034: self.column_editor,
            42051: lambda: self.toggle_panel("charpanel"), 42052: lambda: self.toggle_panel("cliphistory"),
            42028: self.toggle_readonly, 42102: lambda: self.readonly_all(True),
            42103: lambda: self.readonly_all(False), 42033: self.toggle_file_readonly,
            42098: self.multi_undo_last, 42099: self.multi_skip,
        }
        for i, cid in enumerate((42090, 42091, 42092, 42093)):
            h[cid] = lambda i=i: self.multi_select(True, i)
        for i, cid in enumerate((42094, 42095, 42096, 42097)):
            h[cid] = lambda i=i: self.multi_select(False, i)
        sorts = {42059: ("lex", False), 42060: ("lex", True), 42080: ("lexi", False), 42081: ("lexi", True),
                 42100: ("locale", False), 42101: ("locale", True), 42061: ("int", False), 42062: ("int", True),
                 42063: ("comma", False), 42064: ("comma", True), 42065: ("dot", False), 42066: ("dot", True),
                 42104: ("len", False), 42105: ("len", True)}
        for cid, (kind, desc) in sorts.items():
            h[cid] = lambda k=kind, d=desc: self.sort_lines(k, d)
        return h

    # ------------------------------------------------------------- helpers
    def eol_str(self, ed=None):
        ed = ed or self.editor()
        return {S.SC_EOL_CRLF: "\r\n", S.SC_EOL_CR: "\r", S.SC_EOL_LF: "\n"}[ed.SendScintilla(S.SCI_GETEOLMODE)]

    def target_lines(self, ed, whole_if_none):
        a, b = ed.sel_range()
        if a == b or (whole_if_none and ed.line_from_pos(a) == ed.line_from_pos(b)):
            if whole_if_none:
                return 0, ed.line_count() - 1
            l0 = ed.line_from_pos(a)
            return l0, l0
        l0, l1 = ed.line_from_pos(a), ed.line_from_pos(b)
        if l1 > l0 and b == ed.line_start(l1):
            l1 -= 1
        return l0, l1

    def line_op(self, fn, whole_if_none=False, keep_sel=False, ed=None):
        ed = ed or self.editor()
        if ed.SendScintilla(S.SCI_GETREADONLY):
            return
        l0, l1 = self.target_lines(ed, whole_if_none)
        start, end = ed.line_start(l0), ed.line_end(l1)
        text = ed.get_range(start, end)
        lines = re.split(r"\r\n|\r|\n", text)
        new = fn(lines)
        if new is None or new == lines:
            return
        out = self.eol_str(ed).join(new)
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        n = ed.replace_range(start, end, out)
        ed.SendScintilla(S.SCI_ENDUNDOACTION)
        if keep_sel or (l0, l1) != (0, ed.line_count() - 1):
            ed.set_sel(start, start + n)

    @staticmethod
    def op_dedupe(lines):
        seen = set()
        out = []
        for l in lines:
            if l not in seen:
                seen.add(l)
                out.append(l)
        return out

    @staticmethod
    def op_dedupe_consecutive(lines):
        out = []
        for l in lines:
            if not out or out[-1] != l:
                out.append(l)
        return out

    def op_tab_to_space(self, lines):
        w = self.editor().SendScintilla(S.SCI_GETTABWIDTH)
        return [l.expandtabs(w) for l in lines]

    def op_space_to_tab(self, lines, leading):
        w = self.editor().SendScintilla(S.SCI_GETTABWIDTH)
        out = []
        for l in lines:
            if leading:
                m = re.match(r"[ \t]*", l)
                ind = m.group(0).expandtabs(w)
                tabs, spaces = divmod(len(ind), w)
                out.append("\t" * tabs + " " * spaces + l[m.end():])
            else:
                res = []
                col = 0
                pending = 0
                for ch in l:
                    if ch == " ":
                        pending += 1
                        col += 1
                        if col % w == 0:
                            res.append("\t" if pending > 1 else " ")
                            pending = 0
                    elif ch == "\t":
                        res.append("\t")
                        pending = 0
                        col = (col // w + 1) * w
                    else:
                        res.append(" " * pending)
                        pending = 0
                        res.append(ch)
                        col += 1
                res.append(" " * pending)
                out.append("".join(res))
        return out

    def sort_lines(self, kind, desc):
        ed = self.editor()
        rect = ed.SendScintilla(S.SCI_SELECTIONISRECTANGLE) or ed.SendScintilla(S.SCI_GETSELECTIONS) > 1
        c0 = c1 = None
        if rect:
            ca = ed.SendScintilla(S.SCI_GETCOLUMN, ed.SendScintilla(S.SCI_GETRECTANGULARSELECTIONANCHOR))
            cc = ed.SendScintilla(S.SCI_GETCOLUMN, ed.SendScintilla(S.SCI_GETRECTANGULARSELECTIONCARET))
            c0, c1 = min(ca, cc), max(ca, cc)
            a = min(ed.SendScintilla(S.SCI_GETSELECTIONNSTART, i) for i in range(ed.SendScintilla(S.SCI_GETSELECTIONS)))
            b = max(ed.SendScintilla(S.SCI_GETSELECTIONNEND, i) for i in range(ed.SendScintilla(S.SCI_GETSELECTIONS)))
            ed.set_sel(a, b)
        tabw = ed.SendScintilla(S.SCI_GETTABWIDTH)

        def keytext(l):
            if c0 is None:
                return l
            x = l.expandtabs(tabw)
            return x[c0:c1] if c1 > c0 else x[c0:]

        coll = None
        if kind == "locale":
            try:
                locale.setlocale(locale.LC_COLLATE, "")
            except locale.Error:
                pass
            coll = locale.strxfrm

        def fn(lines):
            if kind in ("int", "comma", "dot"):
                nums, rest = [], []
                for l in lines:
                    k = keytext(l)
                    if kind == "int":
                        m = re.match(r"\s*([+-]?\d+)", k)
                        v = int(m.group(1)) if m else None
                    else:
                        v = _num_key(k, kind == "comma")
                    (nums if v is not None else rest).append((v, l))
                nums.sort(key=lambda x: x[0], reverse=desc)
                return [l for _, l in nums] + [l for _, l in rest]
            if kind == "len":
                return sorted(lines, key=lambda l: len(keytext(l)), reverse=desc)
            if kind == "lexi":
                return sorted(lines, key=lambda l: keytext(l).lower(), reverse=desc)
            if kind == "locale":
                return sorted(lines, key=lambda l: coll(keytext(l)), reverse=desc)
            return sorted(lines, key=keytext, reverse=desc)
        self.line_op(fn, whole_if_none=True, ed=ed)

    def split_lines(self):
        ed = self.editor()
        cols = [int(c) for c in str(self.S["edge_columns"]).replace(",", " ").split() if c.isdigit()]
        width = ed.SendScintilla(S.SCI_TEXTWIDTH, S.STYLE_DEFAULT, b"P") * cols[0] if (cols and self.S["edge_mode"]) else 0
        l0, l1 = self.target_lines(ed, False)
        ed.SendScintilla(S.SCI_SETTARGETRANGE, ed.line_start(l0), ed.line_end(l1))
        ed.SendScintilla(S.SCI_LINESSPLIT, width)

    def join_lines(self):
        ed = self.editor()
        l0, l1 = self.target_lines(ed, False)
        if l0 == l1:
            l1 = min(l0 + 1, ed.line_count() - 1)
        ed.SendScintilla(S.SCI_SETTARGETRANGE, ed.line_start(l0), ed.line_end(l1))
        ed.SendScintilla(S.SCI_LINESJOIN)

    def insert_blank(self, above):
        ed = self.editor()
        line = ed.line_from_pos(ed.pos())
        eol = self.eol_str(ed)
        if above:
            p = ed.line_start(line)
            ed.SendScintilla(S.SCI_INSERTTEXT, p, eol.encode())
            ed.goto_pos(p)
        else:
            p = ed.line_end(line)
            ed.SendScintilla(S.SCI_INSERTTEXT, p, eol.encode())
            ed.goto_pos(p + len(eol))

    def eol_to_space(self, trim):
        ed = self.editor()
        a, b = ed.sel_range()
        if a == b:
            a, b = 0, ed.length()
        t = ed.get_range(a, b)
        if trim:
            t = " ".join(l.strip(" \t") for l in re.split(r"\r\n|\r|\n", t))
        else:
            t = re.sub(r"\r\n|\r|\n", " ", t)
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        ed.replace_range(a, b, t)
        ed.SendScintilla(S.SCI_ENDUNDOACTION)

    def transform_sel(self, fn):
        ed = self.editor()
        n = ed.SendScintilla(S.SCI_GETSELECTIONS)
        sels = []
        for i in range(n):
            sels.append((ed.SendScintilla(S.SCI_GETSELECTIONNSTART, i), ed.SendScintilla(S.SCI_GETSELECTIONNEND, i)))
        if all(a == b for a, b in sels):
            return
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        for a, b in sorted(sels, reverse=True):
            if a != b:
                t = ed.get_range(a, b)
                nt = fn(t)
                if nt != t:
                    ed.replace_range(a, b, nt)
        ed.SendScintilla(S.SCI_ENDUNDOACTION)
        if n == 1:
            ed.set_sel(sels[0][0], sels[0][1])

    @staticmethod
    def proper_case(t, blend):
        def f(m):
            w = m.group(0)
            return w[0].upper() + (w[1:] if blend else w[1:].lower())
        return re.sub(r"\w+", f, t)

    @staticmethod
    def sentence_case(t, blend):
        out = []
        cap = True
        for ch in t:
            if ch.isalpha():
                out.append(ch.upper() if cap else (ch if blend else ch.lower()))
                cap = False
            else:
                out.append(ch)
                if ch in ".!?":
                    cap = True
        return "".join(out)

    def convert_eol(self, mode):
        ed = self.editor()
        if ed.SendScintilla(S.SCI_GETREADONLY):
            # Scintilla's ConvertLineEnds never terminates on a read-only document
            return
        ed.SendScintilla(S.SCI_CONVERTEOLS, mode)
        ed.SendScintilla(S.SCI_SETEOLMODE, mode)
        b = self.buf()
        if b:
            b.eol = mode
        self.update_status()

    # ----------------------------------------------------------- selection
    def begin_end_select(self, column):
        ed = self.editor()
        anchor = getattr(self, "_bes_anchor", None)
        if anchor is None or anchor[0] is not ed:
            self._bes_anchor = (ed, ed.pos(), column)
            self.actions[42089 if column else 42020].setCheckable(True)
            self.actions[42089 if column else 42020].setChecked(True)
            return
        _, p, col = anchor
        self._bes_anchor = None
        for cid in (42020, 42089):
            self.actions[cid].setChecked(False)
        if col:
            ed.SendScintilla(S.SCI_SETSELECTIONMODE, S.SC_SEL_RECTANGLE)
            ed.SendScintilla(S.SCI_SETRECTANGULARSELECTIONANCHOR, p)
            ed.SendScintilla(S.SCI_SETRECTANGULARSELECTIONCARET, ed.pos())
        else:
            ed.set_sel(p, ed.pos())

    def insert_datetime(self, kind):
        now = QDateTime.currentDateTime()
        loc = QLocale()
        if kind == "custom":
            fmt = self.S["date_format"].replace("tt", "AP").replace("t", "A")
            s = now.toString(fmt)
        else:
            ft = QLocale.FormatType.ShortFormat if kind == "short" else QLocale.FormatType.LongFormat
            d = loc.toString(now.date(), ft)
            t = loc.toString(now.time(), QLocale.FormatType.ShortFormat)
            s = (d + " " + t) if self.S["date_reverse"] else (t + " " + d)
        self.editor().replaceSelectedText(s)

    def copy_path(self, what):
        b = self.buf()
        if b is None:
            return
        if what == "full":
            s = b.full_name()
        elif what == "name":
            s = b.name()
        else:
            s = os.path.dirname(b.path) if b.path else ""
        QApplication.clipboard().setText(s)

    def copy_all(self, what):
        out = []
        for v in self.views:
            for b in v.buffers:
                s = b.name() if what == "name" else b.full_name()
                if s not in out:
                    out.append(s)
        QApplication.clipboard().setText("\n".join(out))

    # ------------------------------------------------------------- comments
    def comment_lines(self, mode):
        ed = self.editor()
        b = self.buf()
        if b is None or ed.SendScintilla(S.SCI_GETREADONLY):
            return
        lg = self.langdb.get(b.lang)
        sym = lg.comment_line
        cs, ce = lg.comment_start, lg.comment_end
        if not sym and not (cs and ce):
            return
        a, bpos = ed.sel_range()
        l0, l1 = ed.line_from_pos(a), ed.line_from_pos(bpos)
        if l1 > l0 and bpos == ed.line_start(l1):
            l1 -= 1
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        for line in range(l1, l0 - 1, -1):
            start, end = ed.line_start(line), ed.line_end(line)
            text = ed.get_range(start, end)
            stripped = text.lstrip(" \t")
            indent = len(text[: len(text) - len(stripped)].encode("utf-8"))
            if not stripped and mode != "uncomment":
                continue
            if sym:
                is_c = stripped.startswith(sym)
                if mode == "uncomment" or (mode == "toggle" and is_c):
                    if is_c:
                        n = len(sym.encode())
                        if stripped[len(sym):len(sym) + 1] == " ":
                            n += 1
                        ed.replace_range(start + indent, start + indent + n, "")
                else:
                    ed.SendScintilla(S.SCI_INSERTTEXT, start + indent, (sym + " ").encode())
            else:
                body = stripped.rstrip()
                is_c = body.startswith(cs) and body.endswith(ce)
                if mode == "uncomment" or (mode == "toggle" and is_c):
                    if is_c:
                        inner = body[len(cs):len(body) - len(ce)]
                        if inner.startswith(" "):
                            inner = inner[1:]
                        if inner.endswith(" "):
                            inner = inner[:-1]
                        ed.replace_range(start + indent, start + indent + len(body.encode()), inner)
                else:
                    ed.replace_range(start + indent, start + indent + len(body.encode()), cs + " " + body + " " + ce)
        ed.SendScintilla(S.SCI_ENDUNDOACTION)

    def block_comment(self):
        ed = self.editor()
        b = self.buf()
        lg = self.langdb.get(b.lang)
        cs, ce = lg.comment_start, lg.comment_end
        if not (cs and ce):
            self.comment_lines("comment")
            return
        a, bb = ed.sel_range()
        if a == bb:
            line = ed.line_from_pos(a)
            a, bb = ed.line_start(line), ed.line_end(line)
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        ed.SendScintilla(S.SCI_INSERTTEXT, bb, (" " + ce).encode())
        ed.SendScintilla(S.SCI_INSERTTEXT, a, (cs + " ").encode())
        ed.SendScintilla(S.SCI_ENDUNDOACTION)
        ed.set_sel(a, bb + len((cs + " " + " " + ce).encode()))

    def block_uncomment(self):
        ed = self.editor()
        lg = self.langdb.get(self.buf().lang)
        cs, ce = lg.comment_start, lg.comment_end
        if not (cs and ce):
            self.comment_lines("uncomment")
            return
        text = ed.all_text()
        raw = text.encode("utf-8")
        p = ed.pos()
        cpos = len(raw[:p].decode("utf-8", "replace"))
        s = text.rfind(cs, 0, cpos + len(cs))
        if s < 0:
            return
        e_ = text.find(ce, max(s + len(cs), cpos - len(ce)))
        if e_ < 0:
            return
        inner = text[s + len(cs):e_]
        if inner.startswith(" "):
            inner = inner[1:]
        if inner.endswith(" "):
            inner = inner[:-1]
        bs = len(text[:s].encode())
        be = len(text[:e_ + len(ce)].encode())
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        ed.replace_range(bs, be, inner)
        ed.SendScintilla(S.SCI_ENDUNDOACTION)

    # ---------------------------------------------------------- paste special
    def paste_mime(self, types):
        md = QApplication.clipboard().mimeData()
        for t in types:
            if md.hasFormat(t):
                data = bytes(md.data(t))
                try:
                    s = data.decode("utf-8")
                except UnicodeDecodeError:
                    s = data.decode("latin-1")
                self.editor().replaceSelectedText(s)
                return
        QMessageBox.information(self, "Paste Special", "The clipboard doesn't contain this format.")

    def copy_binary(self, cut):
        ed = self.editor()
        a, b = ed.sel_range()
        if a == b:
            return
        data = ed.get_bytes(a, b)
        md = QMimeData()
        md.setData(BIN_MIME, QByteArray(data))
        md.setText(data.replace(b"\0", b"").decode("utf-8", "replace"))
        QApplication.clipboard().setMimeData(md)
        if cut:
            ed.SendScintilla(S.SCI_CLEAR)

    def paste_binary(self):
        md = QApplication.clipboard().mimeData()
        ed = self.editor()
        if md.hasFormat(BIN_MIME):
            data = bytes(md.data(BIN_MIME))
        elif md.hasText():
            data = md.text().encode("utf-8")
        else:
            return
        ed.SendScintilla(S.SCI_BEGINUNDOACTION)
        ed.SendScintilla(S.SCI_CLEAR)
        ed.SendScintilla(S.SCI_ADDTEXT, len(data), data)
        ed.SendScintilla(S.SCI_ENDUNDOACTION)

    # ----------------------------------------------------------- on selection
    def current_word(self, ed=None):
        ed = ed or self.editor()
        t = ed.sel_text()
        if not t:
            a, b = ed.word_at()
            t = ed.get_range(a, b)
        return t

    def sel_open_file(self):
        t = self.current_word().strip().strip('"\'')
        if not t:
            return
        b = self.buf()
        p = os.path.expanduser(t)
        if not os.path.isabs(p) and b and b.path:
            p = os.path.join(os.path.dirname(b.path), p)
        if os.path.exists(p):
            self.open_file(p)
        else:
            QMessageBox.information(self, "Open File", 'The file "%s" doesn\'t exist.' % p)

    def sel_open_folder(self):
        t = self.current_word().strip().strip('"\'')
        p = os.path.expanduser(t)
        b = self.buf()
        if not os.path.isabs(p) and b and b.path:
            p = os.path.join(os.path.dirname(b.path), p)
        d = p if os.path.isdir(p) else os.path.dirname(p)
        if os.path.isdir(d):
            self._spawn(["xdg-open", d])

    def redact_selection(self):
        dot = bool(QGuiApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        ch = "●" if dot else "█"
        self.transform_sel(lambda t: "".join(c if c in "\r\n" else ch for c in t))

    def search_internet(self):
        from urllib.parse import quote
        w = self.current_word()
        if not w:
            return
        url = self.S["search_engine"] or "https://duckduckgo.com/?q=$(CURRENT_WORD)"
        if "$(CURRENT_WORD)" not in url:
            url += "$(CURRENT_WORD)"
        QDesktopServices.openUrl(QUrl(url.replace("$(CURRENT_WORD)", quote(w))))

    # ----------------------------------------------------------- multi-select
    def multi_select(self, all_, variant):
        ed = self.editor()
        flags = {0: S.SCFIND_WHOLEWORD, 1: S.SCFIND_MATCHCASE, 2: S.SCFIND_WHOLEWORD,
                 3: S.SCFIND_MATCHCASE | S.SCFIND_WHOLEWORD}[variant]
        if variant == 0:
            flags = S.SCFIND_WHOLEWORD
        if ed.SendScintilla(S.SCI_GETSELECTIONEMPTY):
            a, b = ed.word_at()
            if a == b:
                return
            ed.set_sel(a, b)
            if not all_:
                return
        ed.SendScintilla(S.SCI_SETSEARCHFLAGS, flags)
        ed.SendScintilla(S.SCI_TARGETWHOLEDOCUMENT)
        if all_:
            ed.SendScintilla(S.SCI_MULTIPLESELECTADDEACH)
        else:
            ed.SendScintilla(S.SCI_MULTIPLESELECTADDNEXT)
            ed.SendScintilla(S.SCI_SCROLLCARET)

    def multi_undo_last(self):
        ed = self.editor()
        n = ed.SendScintilla(S.SCI_GETSELECTIONS)
        if n > 1:
            ed.SendScintilla(S.SCI_DROPSELECTIONN, ed.SendScintilla(S.SCI_GETMAINSELECTION))
            ed.SendScintilla(S.SCI_SCROLLCARET)

    def multi_skip(self):
        ed = self.editor()
        n = ed.SendScintilla(S.SCI_GETSELECTIONS)
        main = ed.SendScintilla(S.SCI_GETMAINSELECTION)
        ed.SendScintilla(S.SCI_TARGETWHOLEDOCUMENT)
        ed.SendScintilla(S.SCI_MULTIPLESELECTADDNEXT)
        if ed.SendScintilla(S.SCI_GETSELECTIONS) > n and n > 1:
            ed.SendScintilla(S.SCI_DROPSELECTIONN, main)
        elif n == 1 and ed.SendScintilla(S.SCI_GETSELECTIONS) > 1:
            ed.SendScintilla(S.SCI_DROPSELECTIONN, 0)
        ed.SendScintilla(S.SCI_SCROLLCARET)

    def column_mode_help(self):
        QMessageBox.information(
            self, "Column Mode Tip",
            "There are 3 ways to switch to column-select mode:\n\n"
            "1. (Keyboard and Mouse)  Hold Alt while left-click dragging\n\n"
            "2. (Keyboard only)  Hold Alt+Shift while using arrow keys\n\n"
            "3. (Keyboard or Mouse)\n"
            "      Put caret at desired start of column block position, then\n"
            "       execute \"Begin/End Select in Column Mode\" command;\n"
            "      Move caret to desired end of column block position, then\n"
            "       execute \"Begin/End Select in Column Mode\" command again")

    # ------------------------------------------------------------- read-only
    def set_buf_readonly(self, b):
        with self.doc_editor(b) as e:
            e.SendScintilla(S.SCI_SETREADONLY, b.readonly())
        self.refresh_buffer_ui(b)

    def toggle_readonly(self):
        b = self.buf()
        if b:
            b.user_readonly = not b.user_readonly
            self.set_buf_readonly(b)

    def readonly_all(self, on):
        for b in self.all_buffers:
            b.user_readonly = on
            self.set_buf_readonly(b)

    def toggle_file_readonly(self):
        b = self.buf()
        if b is None or not b.path:
            return
        try:
            mode = os.stat(b.path).st_mode
            if os.access(b.path, os.W_OK):
                os.chmod(b.path, mode & ~0o222)
            else:
                os.chmod(b.path, mode | 0o200)
        except OSError as ex:
            QMessageBox.warning(self, "Read-Only", str(ex))
            return
        b.file_readonly = not os.access(b.path, os.W_OK)
        self.set_buf_readonly(b)

    # --------------------------------------------------- typing assistance
    def on_char_added(self, ed, ch):
        if ed.view_index < 0 or ed.buffer is None:
            return
        if self.recording:
            pass
        c = chr(ch) if 0 <= ch < 0x110000 else ""
        eolm = ed.SendScintilla(S.SCI_GETEOLMODE)
        if (c == "\n" and eolm != S.SC_EOL_CR) or (c == "\r" and eolm == S.SC_EOL_CR):
            self.auto_indent(ed)
        self.auto_insert(ed, c)
        if not (ed.buffer.large and not self.S["large_ac"]):
            self.ac_on_char(ed, c)

    def auto_indent(self, ed):
        mode = self.S["auto_indent"]
        if mode == "none":
            return
        line = ed.line_from_pos(ed.pos())
        if line == 0:
            return
        prev = ed.get_range(ed.line_start(line - 1), ed.line_end(line - 1))
        indent = prev[: len(prev) - len(prev.lstrip(" \t"))]
        width = ed.SendScintilla(S.SCI_GETTABWIDTH)
        unit = "\t" if ed.SendScintilla(S.SCI_GETUSETABS) else " " * width
        cur_text = ed.get_range(ed.line_start(line), ed.line_end(line))
        extra = ""
        closing = False
        if mode == "advanced":
            stripped = prev.rstrip()
            lang = ed.buffer.lang
            if lang in ("python", "gdscript", "nim", "yaml") and stripped.endswith(":"):
                extra = unit
            elif stripped.endswith("{") or stripped.endswith("[") or (stripped.endswith("(") and lang not in ("normal",)):
                extra = unit
                closing = cur_text.lstrip().startswith(("}", "]", ")"))
        new_ind = indent + extra
        cur_ind_len = len(cur_text) - len(cur_text.lstrip(" \t"))
        p0 = ed.line_start(line)
        ed.replace_range(p0, p0 + len(cur_text[:cur_ind_len].encode()), new_ind)
        caret = p0 + len(new_ind.encode())
        if closing:
            eol = self.eol_str(ed)
            ed.SendScintilla(S.SCI_INSERTTEXT, caret, (eol + indent).encode())
        ed.goto_pos(caret)

    def auto_insert(self, ed, c):
        S_ = self.S
        pairs = {"(": (")", "ai_paren"), "[": ("]", "ai_bracket"), "{": ("}", "ai_brace"),
                 '"': ('"', "ai_dquote"), "'": ("'", "ai_squote")}
        p = ed.pos()
        nxt = ed.get_range(p, min(p + 1, ed.length()))
        if c in (")", "]", "}", '"', "'") and nxt == c and getattr(ed, "_ai_pending", None) == (p, c):
            ed.SendScintilla(S.SCI_DELETERANGE, p, 1)
            ed._ai_pending = None
            return
        if c in pairs and S_[pairs[c][1]] and ed.SendScintilla(S.SCI_GETSELECTIONS) == 1:
            close = pairs[c][0]
            if c in "\"'" and p >= 2:
                prevc = ed.get_range(p - 2, p - 1)
                if prevc.isalnum() or prevc == "\\":
                    return
            if nxt and not (nxt.isspace() or nxt in ")]};,"):
                return
            ed.SendScintilla(S.SCI_INSERTTEXT, p, close.encode())
            ed._ai_pending = (p, close)
            return
        if c == ">" and S_["ai_tag"] and ed.buffer.lang in ("html", "xml", "php", "asp", "jsp"):
            line = ed.line_from_pos(p)
            before = ed.get_range(max(ed.line_start(line), p - 2000), p)
            m = re.search(r"<([A-Za-z][\w:.-]*)(?:\s[^<>]*)?>$", before)
            if m and not before.endswith("/>"):
                tag = m.group(1)
                if ed.buffer.lang != "xml" and tag.lower() in VOID_TAGS:
                    return
                ed.SendScintilla(S.SCI_INSERTTEXT, p, ("</%s>" % tag).encode())

    def delimiter_select(self, ed, ev):
        o, c = self.S["delim_open"], self.S["delim_close"]
        if not o or not c:
            return False
        p = ed.SendScintilla(S.SCI_POSITIONFROMPOINTCLOSE, int(ev.position().x()), int(ev.position().y()))
        if p < 0:
            return False
        line = ed.line_from_pos(p)
        if self.S["delim_multiline"]:
            a0, b0 = 0, ed.length()
        else:
            a0, b0 = ed.line_start(line), ed.line_end(line)
        text = ed.get_range(a0, b0)
        rel = len(ed.get_bytes(a0, p).decode("utf-8", "replace"))
        s = text.rfind(o, 0, rel)
        e = text.find(c, rel)
        if s < 0 or e < 0:
            return False
        bs = a0 + len(text[: s + len(o)].encode())
        be = a0 + len(text[:e].encode())
        ed.set_sel(bs, be)
        return True
