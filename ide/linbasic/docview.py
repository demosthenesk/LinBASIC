"""One Notepad++ "view": a document tab bar above a single Scintilla widget."""
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QSize, QPoint
from PyQt6.QtGui import QPainter, QColor, QIcon, QPen, QFontMetrics
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabBar, QStyle, QStyleOptionTab, QToolButton

from . import paths
from .editor import Editor


class DocTabBar(QTabBar):
    close_requested = pyqtSignal(int)
    middle_clicked = pyqtSignal(int)
    double_clicked = pyqtSignal(int)
    context = pyqtSignal(int, QPoint)
    dropped_external = pyqtSignal(object, int)   # (buffer-id, index) dragged from the other view

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.setMovable(True)
        self.setDocumentMode(True)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideNone)
        self.setTabsClosable(False)
        self.setDrawBase(False)
        self.setAcceptDrops(True)
        self.colors = {}
        self.focus_color = QColor("#FAAA3C")
        self.unfocus_color = QColor("#FFCAB0")
        self.inactive_fg = QColor("#808080")
        self.inactive_bg = QColor("#C0C0C0")
        self.active_fg = QColor("#000000")
        self.active_bg = QColor("#FFFFFF")
        self.bar_bg = QColor("#F0F0F0")
        self.tab_colors = [QColor(c) for c in ("#F3F0CB", "#DBF3CB", "#CBDBF3", "#F3DBCB", "#F3CBEE")]
        self.icons = {k: QIcon(paths.icon("misc/%s.png" % k)) for k in
                      ("tab_saved", "tab_unsaved", "tab_readonly", "tab_monitor", "close", "pinned")}
        self.show_close = True
        self.reduce = False
        self.max_len = 0

    def tab_label(self, i):
        b = self.view.buffer_at(i)
        if b is None:
            return ""
        name = b.name()
        if self.max_len and len(name) > self.max_len:
            name = name[: self.max_len - 1] + "…"
        return name

    def tabSizeHint(self, i):
        fm = QFontMetrics(self.font())
        w = 6 + 20 + fm.horizontalAdvance(self.tab_label(i)) + 10 + (20 if self.show_close else 4)
        b = self.view.buffer_at(i)
        if b is not None and b.pinned:
            w += 16
        h = 22 if self.reduce else 26
        return QSize(max(w, 50), h)

    def minimumTabSizeHint(self, i):
        return self.tabSizeHint(i)

    def close_rect(self, i):
        r = self.tabRect(i)
        return QRect(r.right() - 18, r.center().y() - 7, 14, 14)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), self.bar_bg)
        focused = self.view.has_focus()
        cur = self.currentIndex()
        for i in range(self.count()):
            r = self.tabRect(i)
            if not r.intersects(ev.rect()):
                continue
            b = self.view.buffer_at(i)
            active = i == cur
            bg = self.active_bg if active else self.inactive_bg
            if b is not None and 0 <= b.tab_color < 5:
                bg = self.tab_colors[b.tab_color]
            rr = r.adjusted(0, 2 if not active else 0, -1, 0)
            p.fillRect(rr, bg)
            p.setPen(QPen(self.inactive_fg.darker(130) if not active else QColor(160, 160, 160), 1))
            p.drawLine(rr.topRight(), rr.bottomRight())
            if active:
                p.fillRect(QRect(rr.left(), rr.top(), rr.width(), 3),
                           self.focus_color if focused else self.unfocus_color)
            x = rr.left() + 6
            if b is not None:
                if b.monitoring:
                    ic = self.icons["tab_monitor"]
                elif b.readonly():
                    ic = self.icons["tab_readonly"]
                elif b.dirty:
                    ic = self.icons["tab_unsaved"]
                else:
                    ic = self.icons["tab_saved"]
                ic.paint(p, QRect(x, rr.center().y() - 8, 16, 16))
                x += 20
            p.setPen(self.active_fg if active else self.inactive_fg.darker(160))
            f = self.font()
            f.setBold(False)
            p.setFont(f)
            tr = QRect(x, rr.top(), rr.right() - x - (20 if self.show_close else 4), rr.height())
            p.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.tab_label(i))
            if b is not None and b.pinned:
                pr = QRect(rr.right() - (36 if self.show_close else 20), rr.center().y() - 8, 16, 16)
                self.icons["pinned"].paint(p, pr)
            if self.show_close:
                self.icons["close"].paint(p, self.close_rect(i))
        p.end()

    def mousePressEvent(self, e):
        i = self.tabAt(e.position().toPoint())
        if e.button() == Qt.MouseButton.MiddleButton and i >= 0:
            self.middle_clicked.emit(i)
            return
        if e.button() == Qt.MouseButton.LeftButton and i >= 0 and self.show_close \
                and self.close_rect(i).contains(e.position().toPoint()):
            self.close_requested.emit(i)
            return
        if e.button() == Qt.MouseButton.RightButton and i >= 0:
            self.setCurrentIndex(i)
            self.context.emit(i, e.globalPosition().toPoint())
            return
        super().mousePressEvent(e)

    def mouseDoubleClickEvent(self, e):
        i = self.tabAt(e.position().toPoint())
        self.double_clicked.emit(i)

    def wheelEvent(self, e):
        if self.count():
            d = -1 if e.angleDelta().y() > 0 else 1
            self.setCurrentIndex((self.currentIndex() + d) % self.count())


class EditView(QWidget):
    """Holds the ordered list of buffers shown in this view plus its editor."""
    activated = pyqtSignal(object)            # view
    current_changed = pyqtSignal(object, object)  # view, buffer

    def __init__(self, main, index):
        super().__init__()
        self.main = main
        self.index = index
        self.buffers = []
        self.current = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.tabs = DocTabBar(self)
        self.editor = Editor(main, index, self)
        lay.addWidget(self.tabs)
        lay.addWidget(self.editor, 1)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabMoved.connect(self._tab_moved)
        self.editor.focused.connect(lambda e: self.activated.emit(self))
        self._switching = False

    def has_focus(self):
        return self.main.active_view is self

    def buffer_at(self, i):
        return self.buffers[i] if 0 <= i < len(self.buffers) else None

    def index_of(self, buf):
        try:
            return self.buffers.index(buf)
        except ValueError:
            return -1

    def add(self, buf, index=None, activate=True):
        if buf in self.buffers:
            if activate:
                self.activate(buf)
            return
        if index is None:
            index = len(self.buffers)
        self._switching = True
        self.buffers.insert(index, buf)
        self.tabs.insertTab(index, buf.name())
        self._switching = False
        if activate:
            self.activate(buf)
        self.tabs.update()

    def remove(self, buf):
        i = self.index_of(buf)
        if i < 0:
            return
        was_current = buf is self.current
        self._switching = True
        self.buffers.pop(i)
        self.tabs.removeTab(i)
        self._switching = False
        buf.view_state.pop(self.index, None)
        if was_current:
            self.current = None
            if self.buffers:
                nxt = self.main.mru_pick(self, i)
                self.activate(nxt)
            else:
                self.editor.SendScintilla(self.editor.SCI_SETDOCPOINTER, 0, self.main.empty_ptr(self))
                self.editor.buffer = None
        self.tabs.update()

    def save_state(self, buf=None):
        buf = buf or self.current
        if buf is None:
            return
        e = self.editor
        snd = e.SendScintilla
        buf.view_state[self.index] = {
            "first": e.first_visible_doc_line(),
            "anchor": snd(e.SCI_GETANCHOR),
            "caret": snd(e.SCI_GETCURRENTPOS),
            "xoffset": snd(e.SCI_GETXOFFSET),
            "folds": e.folded_lines(),
            "selmode": snd(e.SCI_GETSELECTIONMODE),
        }

    def activate(self, buf):
        if buf not in self.buffers:
            return
        if self.current is not None and self.current is not buf and self.current in self.buffers:
            self.save_state()
        e = self.editor
        if self.current is not buf or e.buffer is not buf:
            e.SendScintilla(e.SCI_SETDOCPOINTER, 0, buf.ptr)
            e.buffer = buf
            self.current = buf
            self.main.apply_buffer_to_editor(e, buf)
            stt = buf.view_state.get(self.index)
            if stt:
                e.restore_folds(stt.get("folds"))
                e.SendScintilla(e.SCI_SETSELECTIONMODE, stt.get("selmode", 0))
                e.SendScintilla(e.SCI_SETSEL, stt["anchor"], stt["caret"])
                e.SendScintilla(e.SCI_SETFIRSTVISIBLELINE, e.SendScintilla(e.SCI_VISIBLEFROMDOCLINE, stt["first"]))
                e.SendScintilla(e.SCI_SETXOFFSET, stt["xoffset"])
            else:
                e.SendScintilla(e.SCI_SETSEL, 0, 0)
        i = self.index_of(buf)
        if self.tabs.currentIndex() != i:
            self._switching = True
            self.tabs.setCurrentIndex(i)
            self._switching = False
        import time as _t
        buf.last_access = _t.time()
        self.tabs.update()
        self.current_changed.emit(self, buf)

    def _tab_changed(self, i):
        if self._switching or i < 0:
            return
        buf = self.buffer_at(i)
        if buf is not None:
            self.activate(buf)
            self.activated.emit(self)

    def _tab_moved(self, frm, to):
        b = self.buffers.pop(frm)
        self.buffers.insert(to, b)
        self.tabs.update()

    def move_tab(self, frm, to):
        if 0 <= frm < len(self.buffers) and 0 <= to < len(self.buffers) and frm != to:
            self.tabs.moveTab(frm, to)

    def refresh_tab(self, buf):
        i = self.index_of(buf)
        if i >= 0:
            self.tabs.setTabText(i, buf.name())
            self.tabs.setTabToolTip(i, buf.full_name())
        self.tabs.update()
