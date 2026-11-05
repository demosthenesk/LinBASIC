"""Scintilla view + document buffers.

Like Notepad++, each of the two views is ONE Scintilla widget; switching tabs
swaps the Scintilla document (SCI_SETDOCPOINTER). Lexer state, undo history,
markers and indicators live in the document; styles, wrap, whitespace display
and fold contraction live in the view, so they are re-applied/restored on
every switch (ScintillaEditView::activateBuffer)."""
import os
import time

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QPoint
from PyQt6.QtGui import QColor, QPixmap, QPainter, QBrush, QPen, QKeySequence
from PyQt6.Qsci import QsciScintilla as S

from . import styles as st

FOLD_MARKERS = {
    "simple": [S.SC_MARK_MINUS, S.SC_MARK_PLUS, S.SC_MARK_EMPTY, S.SC_MARK_EMPTY,
               S.SC_MARK_EMPTY, S.SC_MARK_EMPTY, S.SC_MARK_EMPTY],
    "arrow": [S.SC_MARK_ARROWDOWN, S.SC_MARK_ARROW, S.SC_MARK_EMPTY, S.SC_MARK_EMPTY,
              S.SC_MARK_EMPTY, S.SC_MARK_EMPTY, S.SC_MARK_EMPTY],
    "circle": [S.SC_MARK_CIRCLEMINUS, S.SC_MARK_CIRCLEPLUS, S.SC_MARK_VLINE, S.SC_MARK_LCORNERCURVE,
               S.SC_MARK_CIRCLEPLUSCONNECTED, S.SC_MARK_CIRCLEMINUSCONNECTED, S.SC_MARK_TCORNERCURVE],
    "box": [S.SC_MARK_BOXMINUS, S.SC_MARK_BOXPLUS, S.SC_MARK_VLINE, S.SC_MARK_LCORNER,
            S.SC_MARK_BOXPLUSCONNECTED, S.SC_MARK_BOXMINUSCONNECTED, S.SC_MARK_TCORNER],
}
FOLD_NUMS = [S.SC_MARKNUM_FOLDEROPEN, S.SC_MARKNUM_FOLDER, S.SC_MARKNUM_FOLDERSUB,
             S.SC_MARKNUM_FOLDERTAIL, S.SC_MARKNUM_FOLDEREND, S.SC_MARKNUM_FOLDEROPENMID,
             S.SC_MARKNUM_FOLDERMIDTAIL]

M_NUM, M_SYM, M_CH, M_FOLD = 0, 1, 2, 3

NPC_REPR = {
    " ": "NBSP", " ": "ENQSP", " ": "EMQSP", " ": "ENSP", " ": "EMSP",
    " ": "3/MSP", " ": "4/MSP", " ": "6/MSP", " ": "FSP", " ": "PSP",
    " ": "THSP", " ": "HSP", "​": "ZWSP", "‌": "ZWNJ", "‍": "ZWJ",
    "‎": "LRM", "‏": "RLM", " ": "NNBSP", " ": "MMSP", "　": "IDSP",
    "﻿": "ZWNBSP", "⁠": "WJ", "­": "SHY", "᠎": "MVS",
}
CC_REPR = {" ": "LS", " ": "PS", "\u0085": "NEL"}


def _bookmark_pixmap():
    """Blue round bookmark, like Notepad++'s default bookmark marker."""
    from PyQt6.QtGui import QRadialGradient
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QRadialGradient(5, 5, 8)
    g.setColorAt(0, QColor("#9CC8FF"))
    g.setColorAt(1, QColor("#1E64C8"))
    p.setPen(QPen(QColor("#174E9E"), 1))
    p.setBrush(QBrush(g))
    p.drawEllipse(1, 1, 12, 12)
    p.end()
    return pm


def _arrow_pixmap(down):
    pm = QPixmap(14, 14)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#20A020")))
    from PyQt6.QtGui import QPolygon
    if down:
        pts = [QPoint(2, 3), QPoint(12, 3), QPoint(7, 11)]
    else:
        pts = [QPoint(2, 11), QPoint(12, 11), QPoint(7, 3)]
    p.drawPolygon(QPolygon(pts))
    p.end()
    return pm


class Buffer:
    _new_counter = 0

    def __init__(self, ptr, path=None, title=None):
        self.ptr = ptr
        self.path = path
        if title is None and path is None:
            Buffer._new_counter += 1
            title = "new %d" % Buffer._new_counter
        self.title = title
        self.encoding = "utf8"
        self.eol = S.SC_EOL_LF
        self.lang = "normal"
        self.lang_forced = False
        self.user_readonly = False
        self.file_readonly = False
        self.monitoring = False
        self.tab_color = -1
        self.pinned = False
        self.mtime = None
        self.dirty = False
        self.force_dirty = False
        self.view_state = {}
        self.backup_path = None
        self.missing = False
        self.pending_reload = False
        self.large = False
        self.ch_dirty_lines = set()
        self.last_access = time.time()

    @property
    def untitled(self):
        return self.path is None

    def name(self):
        return os.path.basename(self.path) if self.path else self.title

    def full_name(self):
        return self.path or self.title

    def readonly(self):
        return self.user_readonly or self.file_readonly or self.monitoring


class Editor(S):
    focused = pyqtSignal(object)
    files_dropped = pyqtSignal(list)
    context_requested = pyqtSignal(object, QPoint)

    def __init__(self, main, view_index, parent=None):
        super().__init__(parent)
        self.main = main
        self.view_index = view_index
        self.buffer = None
        self._hidden_ranges = []
        self.setUtf8(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        snd = self.SendScintilla
        snd(S.SCI_SETCODEPAGE, 65001)
        snd(S.SCI_SETMULTIPLESELECTION, True)
        snd(S.SCI_SETADDITIONALSELECTIONTYPING, True)
        snd(S.SCI_SETMULTIPASTE, S.SC_MULTIPASTE_EACH)
        snd(S.SCI_SETMOUSESELECTIONRECTANGULARSWITCH, True)
        snd(S.SCI_SETRECTANGULARSELECTIONMODIFIER, S.SCMOD_ALT)
        snd(S.SCI_SETADDITIONALCARETSBLINK, True)
        snd(S.SCI_SETSCROLLWIDTHTRACKING, True)
        snd(S.SCI_SETSCROLLWIDTH, 1)
        snd(S.SCI_SETLAYOUTCACHE, S.SC_CACHE_PAGE)
        snd(S.SCI_SETFOLDFLAGS, 16)
        snd(S.SCI_SETAUTOMATICFOLD, S.SC_AUTOMATICFOLD_SHOW | S.SC_AUTOMATICFOLD_CLICK | S.SC_AUTOMATICFOLD_CHANGE)
        snd(S.SCI_SETMOUSEDWELLTIME, 500)
        snd(S.SCI_AUTOCSETSEPARATOR, ord(" "))
        snd(S.SCI_AUTOCSETMAXHEIGHT, 10)
        snd(S.SCI_AUTOCSETCANCELATSTART, False)
        snd(S.SCI_AUTOCSETAUTOHIDE, True)
        snd(S.SCI_AUTOCSETDROPRESTOFWORD, False)
        self.setBraceMatching(S.BraceMatch.SloppyBraceMatch)
        self.setAutoIndent(False)
        # margins
        snd(S.SCI_SETMARGINS, 4)
        snd(S.SCI_SETMARGINTYPEN, M_NUM, S.SC_MARGIN_NUMBER)
        snd(S.SCI_SETMARGINTYPEN, M_SYM, S.SC_MARGIN_SYMBOL)
        snd(S.SCI_SETMARGINMASKN, M_SYM, (1 << st.MARK_BOOKMARK) | (1 << st.MARK_HIDEBEGIN) | (1 << st.MARK_HIDEEND))
        snd(S.SCI_SETMARGINSENSITIVEN, M_SYM, True)
        snd(S.SCI_SETMARGINTYPEN, M_CH, S.SC_MARGIN_SYMBOL)
        snd(S.SCI_SETMARGINMASKN, M_CH, (1 << st.MARK_CH_MODIFIED) | (1 << st.MARK_CH_SAVED))
        snd(S.SCI_SETMARGINTYPEN, M_FOLD, S.SC_MARGIN_SYMBOL)
        snd(S.SCI_SETMARGINMASKN, M_FOLD, S.SC_MASK_FOLDERS)
        snd(S.SCI_SETMARGINSENSITIVEN, M_FOLD, True)
        self.markerDefine(_bookmark_pixmap(), st.MARK_BOOKMARK)
        self.markerDefine(_arrow_pixmap(True), st.MARK_HIDEBEGIN)
        self.markerDefine(_arrow_pixmap(False), st.MARK_HIDEEND)
        snd(S.SCI_MARKERDEFINE, st.MARK_CH_MODIFIED, S.SC_MARK_FULLRECT)
        snd(S.SCI_MARKERDEFINE, st.MARK_CH_SAVED, S.SC_MARK_FULLRECT)
        self.marginClicked.connect(self._margin_clicked)
        self.SCN_UPDATEUI.connect(self._update_ui)
        self.SCN_CHARADDED.connect(self._char_added)
        self.SCN_MODIFIED.connect(self._modified)
        self.SCN_DOUBLECLICK.connect(self._double_click)
        self.SCN_ZOOM.connect(self._zoomed)
        self.SCN_MACRORECORD.connect(self._macro_record)
        self.SCN_SAVEPOINTREACHED.connect(lambda: self.main.on_savepoint(self, False))
        self.SCN_SAVEPOINTLEFT.connect(lambda: self.main.on_savepoint(self, True))
        self._lines = 1
        self._ui_timer = QTimer(self)
        self._ui_timer.setSingleShot(True)
        self._ui_timer.setInterval(60)
        self._ui_timer.timeout.connect(lambda: self.main.on_editor_idle(self))

    # ---------------------------------------------------------------- helpers
    def snd(self, *a):
        return self.SendScintilla(*a)

    def pos(self):
        return self.SendScintilla(S.SCI_GETCURRENTPOS)

    def length(self):
        return self.SendScintilla(S.SCI_GETLENGTH)

    def line_count(self):
        return self.SendScintilla(S.SCI_GETLINECOUNT)

    def line_from_pos(self, p):
        return self.SendScintilla(S.SCI_LINEFROMPOSITION, p)

    def line_start(self, line):
        return self.SendScintilla(S.SCI_POSITIONFROMLINE, line)

    def line_end(self, line):
        return self.SendScintilla(S.SCI_GETLINEENDPOSITION, line)

    def get_bytes(self, start=0, end=None):
        if end is None:
            end = self.length()
        if end <= start:
            return b""
        return bytes(self.bytes(start, end))[: end - start]

    def get_range(self, start, end):
        return self.get_bytes(start, end).decode("utf-8", errors="replace")

    def all_text(self):
        return self.get_bytes().decode("utf-8", errors="replace")

    def sel_range(self):
        return (self.SendScintilla(S.SCI_GETSELECTIONSTART), self.SendScintilla(S.SCI_GETSELECTIONEND))

    def sel_text(self):
        a, b = self.sel_range()
        return self.get_range(a, b)

    def replace_range(self, start, end, text):
        data = text.encode("utf-8") if isinstance(text, str) else text
        self.SendScintilla(S.SCI_SETTARGETSTART, start)
        self.SendScintilla(S.SCI_SETTARGETEND, end)
        self.SendScintilla(S.SCI_REPLACETARGET, len(data), data)
        return len(data)

    def set_sel(self, anchor, caret):
        self.SendScintilla(S.SCI_SETSEL, anchor, caret)

    def goto_pos(self, p, anchor=None):
        if anchor is None:
            anchor = p
        line = self.line_from_pos(p)
        self.SendScintilla(S.SCI_ENSUREVISIBLEENFORCEPOLICY, line)
        self.SendScintilla(S.SCI_SETSEL, anchor, p)
        self.SendScintilla(S.SCI_SCROLLCARET)

    def goto_line(self, line):
        line = max(0, min(line, self.line_count() - 1))
        self.SendScintilla(S.SCI_ENSUREVISIBLEENFORCEPOLICY, line)
        self.SendScintilla(S.SCI_GOTOLINE, line)
        first = self.SendScintilla(S.SCI_GETFIRSTVISIBLELINE)
        vis = self.SendScintilla(S.SCI_LINESONSCREEN)
        dl = self.SendScintilla(S.SCI_VISIBLEFROMDOCLINE, line)
        if not (first <= dl < first + vis):
            self.SendScintilla(S.SCI_SETFIRSTVISIBLELINE, max(0, dl - vis // 2))

    def word_at(self, p=None, extra=""):
        if p is None:
            p = self.pos()
        a = self.SendScintilla(S.SCI_WORDSTARTPOSITION, p, True)
        b = self.SendScintilla(S.SCI_WORDENDPOSITION, p, True)
        return a, b

    def indicator_clear(self, ind, start=0, end=None):
        if end is None:
            end = self.length()
        self.SendScintilla(S.SCI_SETINDICATORCURRENT, ind)
        self.SendScintilla(S.SCI_INDICATORCLEARRANGE, start, end - start)

    def indicator_fill(self, ind, start, length):
        self.SendScintilla(S.SCI_SETINDICATORCURRENT, ind)
        self.SendScintilla(S.SCI_INDICATORFILLRANGE, start, length)

    def first_visible_doc_line(self):
        return self.SendScintilla(S.SCI_DOCLINEFROMVISIBLE, self.SendScintilla(S.SCI_GETFIRSTVISIBLELINE))

    def visible_range(self):
        first = self.SendScintilla(S.SCI_GETFIRSTVISIBLELINE)
        n = self.SendScintilla(S.SCI_LINESONSCREEN) + 1
        l0 = self.SendScintilla(S.SCI_DOCLINEFROMVISIBLE, first)
        l1 = self.SendScintilla(S.SCI_DOCLINEFROMVISIBLE, first + n)
        return self.line_start(l0), self.line_end(min(l1, self.line_count() - 1))

    # ------------------------------------------------------------- view setup
    def setup_margins(self, settings):
        snd = self.SendScintilla
        if settings["line_numbers"]:
            self.update_linenumber_width(settings, force=True)
        else:
            snd(S.SCI_SETMARGINWIDTHN, M_NUM, 0)
        snd(S.SCI_SETMARGINWIDTHN, M_SYM, 16 if settings["bookmark_margin"] else 0)
        snd(S.SCI_SETMARGINWIDTHN, M_CH, 4 if settings["change_history"] else 0)
        style = settings["fold_style"]
        if style == "none":
            snd(S.SCI_SETMARGINWIDTHN, M_FOLD, 0)
        else:
            snd(S.SCI_SETMARGINWIDTHN, M_FOLD, 14)
            for num, kind in zip(FOLD_NUMS, FOLD_MARKERS.get(style, FOLD_MARKERS["box"])):
                snd(S.SCI_MARKERDEFINE, num, kind)
        snd(S.SCI_SETMARGINLEFT, 0, settings["padding_left"])
        snd(S.SCI_SETMARGINRIGHT, 0, settings["padding_right"])

    def update_linenumber_width(self, settings, force=False):
        if not settings["line_numbers"]:
            return
        n = self.line_count()
        if not force and len(str(n)) == len(str(self._lines)):
            self._lines = n
            return
        self._lines = n
        digits = max(len(str(n)), 3) if settings["line_numbers_dynamic"] else 6
        w = self.SendScintilla(S.SCI_TEXTWIDTH, S.STYLE_LINENUMBER, b"8" * digits) + 8
        self.SendScintilla(S.SCI_SETMARGINWIDTHN, M_NUM, w)

    def apply_view_settings(self, settings):
        snd = self.SendScintilla
        self.setup_margins(settings)
        snd(S.SCI_SETCARETWIDTH, settings["caret_width"])
        snd(S.SCI_SETCARETPERIOD, settings["caret_blink"])
        snd(S.SCI_SETWRAPINDENTMODE, {0: S.SC_WRAPINDENT_FIXED, 1: S.SC_WRAPINDENT_SAME,
                                       2: S.SC_WRAPINDENT_INDENT}[settings["wrap_mode"]])
        snd(S.SCI_SETVIRTUALSPACEOPTIONS,
            S.SCVS_RECTANGULARSELECTION | (S.SCVS_USERACCESSIBLE if settings["virtual_space"] else 0))
        snd(S.SCI_SETENDATLASTLINE, not settings["scroll_beyond_last"])
        snd(S.SCI_SETMULTIPLESELECTION, settings["multi_edit"])
        snd(S.SCI_SETFONTQUALITY, S.SC_EFF_QUALITY_LCD_OPTIMIZED if settings["smooth_font"] else S.SC_EFF_QUALITY_NON_ANTIALIASED)
        mode = settings["edge_mode"]
        cols = [int(c) for c in str(settings["edge_columns"]).replace(",", " ").split() if c.isdigit()]
        snd(S.SCI_MULTIEDGECLEARALL)
        if mode == 0 or not cols:
            snd(S.SCI_SETEDGEMODE, S.EDGE_NONE)
        elif mode == 2:
            snd(S.SCI_SETEDGEMODE, S.EDGE_BACKGROUND)
            snd(S.SCI_SETEDGECOLUMN, cols[0])
        elif len(cols) == 1:
            snd(S.SCI_SETEDGEMODE, S.EDGE_LINE)
            snd(S.SCI_SETEDGECOLUMN, cols[0])
        else:
            snd(S.SCI_SETEDGEMODE, S.EDGE_MULTILINE)
            edge = self.main.styles.gfg("Edge colour", QColor("#80FFFF"))
            for c in cols:
                snd(S.SCI_MULTIEDGEADDLINE, c, edge)
        self.apply_symbols(settings)

    def apply_symbols(self, settings):
        snd = self.SendScintilla
        snd(S.SCI_SETVIEWWS, S.SCWS_VISIBLEALWAYS if settings["show_ws"] else S.SCWS_INVISIBLE)
        snd(S.SCI_SETVIEWEOL, bool(settings["show_eol"]))
        snd(S.SCI_SETINDENTATIONGUIDES, S.SC_IV_LOOKBOTH if settings["show_indent"] else S.SC_IV_NONE)
        snd(S.SCI_SETWRAPVISUALFLAGS, S.SC_WRAPVISUALFLAG_END if settings["show_wrap_symbol"] else 0)
        snd(S.SCI_SETWRAPMODE, S.SC_WRAP_WORD if settings["word_wrap"] else S.SC_WRAP_NONE)
        for ch, rep in NPC_REPR.items():
            key = ch.encode("utf-8")
            if settings["show_npc"]:
                txt = rep if settings["npc_appearance"] == "abbrev" else "U+%04X" % ord(ch)
                snd(S.SCI_SETREPRESENTATION, key, txt.encode())
            else:
                snd(S.SCI_CLEARREPRESENTATION, key, b"")
        for ch, rep in CC_REPR.items():
            key = ch.encode("utf-8")
            if settings["show_cc"]:
                snd(S.SCI_SETREPRESENTATION, key, rep.encode())
            else:
                snd(S.SCI_CLEARREPRESENTATION, key, b"")

    # ---------------------------------------------------------------- folding
    def folded_lines(self):
        out = []
        n = self.line_count()
        snd = self.SendScintilla
        line = 0
        while line < n:
            lvl = snd(S.SCI_GETFOLDLEVEL, line)
            if lvl & S.SC_FOLDLEVELHEADERFLAG and not snd(S.SCI_GETFOLDEXPANDED, line):
                out.append(line)
            line += 1
        return out

    def restore_folds(self, lines):
        if not lines:
            return
        self.SendScintilla(S.SCI_COLOURISE, 0, -1)
        for line in lines:
            if self.SendScintilla(S.SCI_GETFOLDLEVEL, line) & S.SC_FOLDLEVELHEADERFLAG:
                self.SendScintilla(S.SCI_FOLDLINE, line, S.SC_FOLDACTION_CONTRACT)

    def fold_level(self, level, contract):
        snd = self.SendScintilla
        snd(S.SCI_COLOURISE, 0, -1)
        for line in range(self.line_count()):
            lvl = snd(S.SCI_GETFOLDLEVEL, line)
            if lvl & S.SC_FOLDLEVELHEADERFLAG and (lvl & S.SC_FOLDLEVELNUMBERMASK) - S.SC_FOLDLEVELBASE == level - 1:
                snd(S.SCI_FOLDLINE, line, S.SC_FOLDACTION_CONTRACT if contract else S.SC_FOLDACTION_EXPAND)

    def fold_current(self, contract):
        snd = self.SendScintilla
        line = self.line_from_pos(self.pos())
        lvl = snd(S.SCI_GETFOLDLEVEL, line)
        if not lvl & S.SC_FOLDLEVELHEADERFLAG:
            line = snd(S.SCI_GETFOLDPARENT, line)
        if line >= 0:
            snd(S.SCI_FOLDLINE, line, S.SC_FOLDACTION_CONTRACT if contract else S.SC_FOLDACTION_EXPAND)

    # ------------------------------------------------------------- hide lines
    def hide_selected_lines(self):
        a, b = self.sel_range()
        l0, l1 = self.line_from_pos(a), self.line_from_pos(b)
        if l1 > l0 and b == self.line_start(l1):
            l1 -= 1
        if l0 == 0:
            l0 = 1
        if l1 >= self.line_count() - 1:
            l1 = self.line_count() - 2
        if l1 < l0:
            return
        self.SendScintilla(S.SCI_HIDELINES, l0, l1)
        self.SendScintilla(S.SCI_MARKERADD, l0 - 1, st.MARK_HIDEBEGIN)
        self.SendScintilla(S.SCI_MARKERADD, l1 + 1, st.MARK_HIDEEND)

    def show_hidden_at(self, line):
        snd = self.SendScintilla
        mask = snd(S.SCI_MARKERGET, line)
        if mask & (1 << st.MARK_HIDEBEGIN):
            start = line + 1
            end = start
            n = self.line_count()
            while end < n and not snd(S.SCI_GETLINEVISIBLE, end):
                end += 1
            snd(S.SCI_SHOWLINES, start, end - 1)
            snd(S.SCI_MARKERDELETE, line, st.MARK_HIDEBEGIN)
            snd(S.SCI_MARKERDELETE, end, st.MARK_HIDEEND)
            return True
        if mask & (1 << st.MARK_HIDEEND):
            end = line - 1
            start = end
            while start > 0 and not snd(S.SCI_GETLINEVISIBLE, start):
                start -= 1
            snd(S.SCI_SHOWLINES, start + 1, end)
            snd(S.SCI_MARKERDELETE, line, st.MARK_HIDEEND)
            snd(S.SCI_MARKERDELETE, start, st.MARK_HIDEBEGIN)
            return True
        return False

    # ----------------------------------------------------------------- events
    def _margin_clicked(self, margin, line, mods):
        if margin == M_SYM:
            if self.show_hidden_at(line):
                return
            self.main.toggle_bookmark(self, line)
        elif margin in (M_NUM, M_CH):
            p0 = self.line_start(line)
            p1 = self.line_start(line + 1) if line + 1 < self.line_count() else self.length()
            self.set_sel(p0, p1)

    def _update_ui(self, *args):
        self._ui_timer.start()
        self.main.on_editor_ui(self)

    def _char_added(self, ch):
        self.main.on_char_added(self, ch)

    def _modified(self, *a):
        # SCN_MODIFIED(pos, modType, text, length, linesAdded, line, foldNow, foldPrev, token, annotLines)
        try:
            pos, mtype, length, added = a[0], a[1], a[3], a[4]
        except (IndexError, TypeError):
            return
        if mtype & (S.SC_MOD_INSERTTEXT | S.SC_MOD_DELETETEXT):
            self.main.on_text_modified(self, pos, mtype, length, added)

    def _double_click(self, pos, line, mods):
        self.main.on_double_click(self, pos, line, mods)

    def _zoomed(self):
        self.main.on_zoom(self)

    def _macro_record(self, msg, wparam, lparam):
        self.main.on_macro_record(self, msg, wparam, lparam)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focused.emit(self)

    def contextMenuEvent(self, e):
        self.context_requested.emit(self, e.globalPos())

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            if files:
                e.acceptProposedAction()
                self.files_dropped.emit(files)
                return
        super().dropEvent(e)

    def keyPressEvent(self, e):
        if self.main.on_key_press(self, e):
            return
        super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier and self.main.delimiter_select(self, e):
            return
        super().mouseDoubleClickEvent(e)
