"""ASCII Codes Insertion Panel (resource 2700)."""
import html.entities

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView

from .. import encodings_util as enc

CTRL = ["NUL", "SOH", "STX", "ETX", "EOT", "ENQ", "ACK", "BEL", "BS", "TAB", "LF", "VT", "FF", "CR", "SO", "SI",
        "DLE", "DC1", "DC2", "DC3", "DC4", "NAK", "SYN", "ETB", "CAN", "EM", "SUB", "ESC", "FS", "GS", "RS", "US"]


class CharPanel(QWidget):
    def __init__(self, main, name):
        super().__init__()
        self.main = main
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(256, 6)
        self.table.setHorizontalHeaderLabels(["Value", "Hex", "Character", "HTML Name", "HTML Decimal", "HTML Hexadecimal"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.verticalHeader().setDefaultSectionSize(18)
        self.table.cellDoubleClicked.connect(self.insert)
        lay.addWidget(self.table)
        self.fill()

    def fill(self):
        cp = enc.system_ansi(self.main.S)
        rev = {v: k for k, v in html.entities.codepoint2name.items()}
        for i in range(256):
            if i < 32:
                ch, shown = chr(i), CTRL[i]
            elif i == 127:
                ch, shown = chr(i), "DEL"
            elif i < 128:
                ch = shown = chr(i)
            else:
                try:
                    ch = bytes([i]).decode(cp)
                except (UnicodeDecodeError, LookupError):
                    ch = chr(i)
                shown = ch
            name = html.entities.codepoint2name.get(ord(ch))
            vals = [str(i), "%02X" % i, shown, "&%s;" % name if name else "",
                    "&#%d;" % ord(ch) if i >= 32 else "", "&#x%X;" % ord(ch) if i >= 32 else ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, ch)
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()

    def insert(self, row, col):
        it = self.table.item(row, col)
        ch = it.data(Qt.ItemDataRole.UserRole)
        text = it.text() if col >= 3 and it.text() else ch
        ed = self.main.editor()
        ed.replaceSelectedText(text)
        ed.setFocus()
