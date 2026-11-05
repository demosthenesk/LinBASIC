"""Document Map (resource 3300): a zoomed-out Scintilla view sharing the active
document, with the visible region of the editor drawn as a frame."""
from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.Qsci import QsciScintilla as S


class Overlay(QWidget):
    def __init__(self, parent, panel):
        super().__init__(parent)
        self.panel = panel
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.rect_ = QRect()

    def paintEvent(self, e):
        if self.rect_.isNull():
            return
        p = QPainter(self)
        c = self.panel.main.styles.gfg("Document map", QColor("#FF8000"))
        fill = QColor(c)
        fill.setAlpha(40)
        p.fillRect(self.rect_, fill)
        p.setPen(QPen(c, 1))
        p.drawRect(self.rect_.adjusted(0, 0, -1, -1))
        p.end()


class MapView(S):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setUtf8(True)
        for m in range(5):
            self.SendScintilla(S.SCI_SETMARGINWIDTHN, m, 0)
        self.SendScintilla(S.SCI_SETZOOM, -10)
        self.SendScintilla(S.SCI_SETHSCROLLBAR, False)
        self.SendScintilla(S.SCI_SETVSCROLLBAR, False)
        self.SendScintilla(S.SCI_SETCARETSTYLE, 0)
        self.SendScintilla(S.SCI_SETCARETLINEVISIBLE, False)
        self.overlay = Overlay(self.viewport(), panel)
        self.dragging = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.overlay.setGeometry(self.viewport().rect())
        self.panel.sync()

    def keyPressEvent(self, e):
        e.ignore()

    def wheelEvent(self, e):
        self.panel.main.editor().wheelEvent(e)

    def mousePressEvent(self, e):
        self.dragging = True
        self.panel.click(e.position().y())

    def mouseMoveEvent(self, e):
        if self.dragging:
            self.panel.click(e.position().y())

    def mouseReleaseEvent(self, e):
        self.dragging = False

    def mouseDoubleClickEvent(self, e):
        pass

    def contextMenuEvent(self, e):
        pass


class DocMapPanel(QWidget):
    def __init__(self, main, name):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.map = MapView(self)
        lay.addWidget(self.map)
        self.cur = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.sync)
        self.attach()

    def on_event(self, kind, ed):
        if kind in ("current", "theme", "lang", "shown"):
            self.attach()
        elif kind in ("scroll", "text"):
            self.timer.start()

    def attach(self):
        b = self.main.buf()
        if b is None:
            return
        ed = self.main.editor()
        self.cur = b
        self.map.SendScintilla(S.SCI_SETDOCPOINTER, 0, b.ptr)
        self.main.styles.apply(self.map, self.main.langdb, b.lang, self.main.S)
        self.map.SendScintilla(S.SCI_SETCARETLINEVISIBLE, False)
        self.map.SendScintilla(S.SCI_SETWRAPMODE, ed.SendScintilla(S.SCI_GETWRAPMODE))
        self.map.SendScintilla(S.SCI_SETZOOM, -10)
        for m in range(5):
            self.map.SendScintilla(S.SCI_SETMARGINWIDTHN, m, 0)
        self.sync()

    def sync(self):
        if self.cur is None or self.cur is not self.main.buf():
            return
        ed = self.main.editor()
        m = self.map
        first = ed.SendScintilla(S.SCI_GETFIRSTVISIBLELINE)
        n = ed.SendScintilla(S.SCI_LINESONSCREEN)
        # map visible lines are 'display lines' of the map; follow the editor's doc lines
        doc_first = ed.SendScintilla(S.SCI_DOCLINEFROMVISIBLE, first)
        doc_last = ed.SendScintilla(S.SCI_DOCLINEFROMVISIBLE, first + n)
        mfirst_vis = m.SendScintilla(S.SCI_VISIBLEFROMDOCLINE, doc_first)
        mlast_vis = m.SendScintilla(S.SCI_VISIBLEFROMDOCLINE, doc_last)
        mlines = max(1, m.SendScintilla(S.SCI_LINESONSCREEN))
        total = m.SendScintilla(S.SCI_VISIBLEFROMDOCLINE, m.line_count() if hasattr(m, "line_count") else m.SendScintilla(S.SCI_GETLINECOUNT))
        span = mlast_vis - mfirst_vis
        if total <= mlines:
            top = 0
        else:
            ratio = first / max(1, (ed.SendScintilla(S.SCI_VISIBLEFROMDOCLINE, ed.SendScintilla(S.SCI_GETLINECOUNT)) - n))
            top = int(max(0, min(total - mlines, (total - mlines) * min(1.0, ratio))))
        m.SendScintilla(S.SCI_SETFIRSTVISIBLELINE, top)
        lh = m.SendScintilla(S.SCI_TEXTHEIGHT, 0)
        y = (mfirst_vis - top) * lh
        h = max(4, span * lh)
        m.overlay.rect_ = QRect(0, y, m.viewport().width(), h)
        m.overlay.update()

    def click(self, y):
        m = self.map
        ed = self.main.editor()
        lh = max(1, m.SendScintilla(S.SCI_TEXTHEIGHT, 0))
        vis = m.SendScintilla(S.SCI_GETFIRSTVISIBLELINE) + int(y // lh)
        doc_line = m.SendScintilla(S.SCI_DOCLINEFROMVISIBLE, vis)
        n = ed.SendScintilla(S.SCI_LINESONSCREEN)
        target = ed.SendScintilla(S.SCI_VISIBLEFROMDOCLINE, doc_line) - n // 2
        ed.SendScintilla(S.SCI_SETFIRSTVISIBLELINE, max(0, target))
        self.sync()
