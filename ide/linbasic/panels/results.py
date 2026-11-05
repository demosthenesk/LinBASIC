"""Search results window (F7) — Find All / Find in Files output."""
import os

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QFont, QBrush, QPalette
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QMenu, QApplication,
                             QStyledItemDelegate, QStyle)
from PyQt6.Qsci import QsciScintilla as S

ROLE = Qt.ItemDataRole.UserRole


class HitDelegate(QStyledItemDelegate):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel

    def paint(self, p, opt, idx):
        data = idx.data(ROLE)
        if not data or data[0] != "line":
            return super().paint(p, opt, idx)
        self.initStyleOption(opt, idx)
        style = opt.widget.style()
        text = opt.text
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, p, opt.widget)
        r = style.subElementRect(QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget)
        prefix = data[5]
        line_text = data[4]
        spans = data[3]
        fm = opt.fontMetrics
        x = r.left() + 2
        y = r.top()
        h = r.height()
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        hit_fg, hit_bg, num_fg = self.panel.colors()
        p.save()
        p.setPen(opt.palette.color(QPalette.ColorRole.HighlightedText) if selected else num_fg)
        p.drawText(QRect(x, y, fm.horizontalAdvance(prefix) + 2, h), Qt.AlignmentFlag.AlignVCenter, prefix)
        x += fm.horizontalAdvance(prefix)
        pos = 0
        segs = []
        for cs, ce in sorted(spans):
            if cs > pos:
                segs.append((line_text[pos:cs], False))
            segs.append((line_text[max(cs, pos):ce], True))
            pos = max(pos, ce)
        segs.append((line_text[pos:], False))
        normal = opt.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text)
        for seg, hit in segs:
            if not seg:
                continue
            seg = seg.replace("\t", "    ")
            w = fm.horizontalAdvance(seg)
            if x > r.right():
                break
            if hit and not selected:
                p.fillRect(QRect(x, y + 1, w, h - 2), hit_bg)
            p.setPen(hit_fg if hit and not selected else normal)
            p.drawText(QRect(x, y, w + 1, h), Qt.AlignmentFlag.AlignVCenter, seg)
            x += w
        p.restore()


class SearchResultsPanel(QWidget):
    def __init__(self, main, name):
        super().__init__()
        self.main = main
        self.purge = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setItemDelegate(HitDelegate(self))
        f = QFont("Monospace")
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.tree.setFont(f)
        self.tree.itemActivated.connect(self.open_item)
        self.tree.itemDoubleClicked.connect(self.open_item)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context)
        lay.addWidget(self.tree)
        self.cur_search = None
        self.cur_file = None

    def colors(self):
        st = self.main.styles.lexers.get("searchResult")
        hit_fg, hit_bg, num_fg = QColor("#FF0000"), QColor("#FFFFBF"), QColor("#808080")
        if st:
            for s in st.styles:
                if s.name.upper().startswith("HIT WORD") or s.id == 4:
                    hit_fg = s.fg or hit_fg
                    hit_bg = s.bg or hit_bg
                if s.name.upper().startswith("LINE NUMBER") or s.id == 2:
                    num_fg = s.fg or num_fg
        return hit_fg, hit_bg, num_fg

    def begin_search(self, text, in_files=False):
        if self.purge:
            self.tree.clear()
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(False)
        it = QTreeWidgetItem(['Search "%s" ...' % text])
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        it.setData(0, ROLE, ("search", text))
        it.setForeground(0, QBrush(QColor("#2060C0")))
        self.tree.insertTopLevelItem(0, it)
        it.setExpanded(True)
        self.cur_search = it
        self.search_text = text

    def add_file(self, path, hits, buffer=None):
        if self.cur_search is None:
            self.begin_search("")
        n = sum(len(h[2]) for h in hits)
        fi = QTreeWidgetItem(["%s (%d hit%s)" % (path, n, "s" if n != 1 else "")])
        fi.setData(0, ROLE, ("file", path, buffer))
        fi.setForeground(0, QBrush(QColor("#008000")))
        self.cur_search.addChild(fi)
        for line, text, spans in hits:
            prefix = "Line %d: " % (line + 1)
            li = QTreeWidgetItem([prefix + text])
            li.setData(0, ROLE, ("line", path, line, spans, text, prefix, buffer))
            fi.addChild(li)
        fi.setExpanded(True)

    def end_search(self, hits, files, searched):
        if self.cur_search is None:
            return
        self.cur_search.setText(0, 'Search "%s" (%d hit%s in %d file%s of %d searched)' % (
            self.search_text, hits, "s" if hits != 1 else "", files, "s" if files != 1 else "", searched))

    def open_item(self, item, col=0):
        data = item.data(0, ROLE)
        if not data:
            return
        if data[0] == "file":
            item.setExpanded(not item.isExpanded())
            return
        if data[0] != "line":
            return
        _, path, line, spans, text, prefix, buf = data
        m = self.main
        if buf is not None and buf in m.all_buffers:
            vs = m.views_of(buf)
            v = vs[0] if vs else m.active_view
            if not vs:
                v.add(buf)
            v.activate(buf)
            m.set_active_view(v)
        else:
            if not os.path.exists(path):
                return
            m.open_file(path)
        ed = m.editor()
        ls = ed.line_start(line)
        cs, ce = spans[0]
        lt = ed.get_range(ls, ed.line_end(line))
        a = ls + len(lt[:cs].encode("utf-8"))
        b = ls + len(lt[:ce].encode("utf-8"))
        ed.goto_line(line)
        ed.set_sel(a, b)
        ed.SendScintilla(S.SCI_SCROLLCARET)
        ed.setFocus()

    def line_items(self):
        out = []

        def walk(it):
            for i in range(it.childCount()):
                c = it.child(i)
                d = c.data(0, ROLE)
                if d and d[0] == "line":
                    out.append(c)
                walk(c)
        if self.cur_search is not None:
            walk(self.cur_search)
        return out

    def navigate(self, d):
        items = self.line_items()
        if not items:
            return
        cur = self.tree.currentItem()
        try:
            i = items.index(cur)
            i = (i + d) % len(items)
        except ValueError:
            i = 0 if d > 0 else len(items) - 1
        self.tree.setCurrentItem(items[i])
        self.open_item(items[i])

    def context(self, pos):
        menu = QMenu(self)
        menu.addAction("Collapse all").triggered.connect(self.tree.collapseAll)
        menu.addAction("Expand all").triggered.connect(self.tree.expandAll)
        menu.addSeparator()
        menu.addAction("Copy").triggered.connect(self.copy_lines)
        menu.addAction("Copy Selected Pathname(s)").triggered.connect(self.copy_paths)
        menu.addAction("Select all").triggered.connect(self.tree.selectAll)
        menu.addAction("Clear all").triggered.connect(self.clear)
        menu.addSeparator()
        menu.addAction("Open all").triggered.connect(self.open_all)
        menu.addSeparator()
        a = menu.addAction("Purge for every search")
        a.setCheckable(True)
        a.setChecked(self.purge)
        a.toggled.connect(lambda v: setattr(self, "purge", v))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def clear(self):
        self.tree.clear()
        self.cur_search = None

    def copy_lines(self):
        out = []
        for it in self.tree.selectedItems() or ([self.tree.currentItem()] if self.tree.currentItem() else []):
            d = it.data(0, ROLE)
            out.append(d[4] if d and d[0] == "line" else it.text(0))
        QApplication.clipboard().setText("\n".join(out))

    def copy_paths(self):
        paths = []
        for it in self.tree.selectedItems():
            d = it.data(0, ROLE)
            if d and d[0] in ("file", "line") and d[1] not in paths:
                paths.append(d[1])
        QApplication.clipboard().setText("\n".join(paths))

    def open_all(self):
        it = self.tree.currentItem()
        while it is not None and it.parent() is not None:
            it = it.parent()
        it = it or self.cur_search
        if it is None:
            return
        for i in range(it.childCount()):
            d = it.child(i).data(0, ROLE)
            if d and d[0] == "file" and os.path.exists(d[1]):
                self.main.open_file(d[1])
