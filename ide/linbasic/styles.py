"""Style engine: reads Notepad++ stylers.xml / theme files and applies them to a
Scintilla view by style ID, exactly as Notepad++'s ScintillaEditView does."""
import copy
import xml.etree.ElementTree as ET

from PyQt6.QtGui import QColor, QFontDatabase
from PyQt6.Qsci import QsciScintilla as S

# Indicator numbers Notepad++ uses (SCE_UNIVERSAL_FOUND_STYLE_*)
IND_URL = 8
IND_MARK5, IND_MARK4, IND_MARK3, IND_MARK2, IND_MARK1 = 21, 22, 23, 24, 25
IND_TAGATTR, IND_TAGMATCH, IND_INC, IND_SMART, IND_FOUND = 26, 27, 28, 29, 31
MARK_STYLE_INDICS = [IND_MARK1, IND_MARK2, IND_MARK3, IND_MARK4, IND_MARK5]

# Marker numbers
MARK_BOOKMARK = 24
MARK_HIDEBEGIN = 23
MARK_HIDEEND = 22
MARK_CH_MODIFIED = 21
MARK_CH_SAVED = 20

FONT_FALLBACKS = {
    "courier new": ["Liberation Mono", "DejaVu Sans Mono", "Noto Mono", "Monospace"],
    "consolas": ["Liberation Mono", "DejaVu Sans Mono", "Ubuntu Mono", "Monospace"],
    "lucida console": ["DejaVu Sans Mono", "Liberation Mono", "Monospace"],
    "arial": ["Liberation Sans", "DejaVu Sans", "Sans Serif"],
    "times new roman": ["Liberation Serif", "DejaVu Serif", "Serif"],
    "comic sans ms": ["Comic Neue", "DejaVu Sans", "Sans Serif"],
    "verdana": ["DejaVu Sans", "Liberation Sans", "Sans Serif"],
    "tahoma": ["DejaVu Sans", "Liberation Sans", "Sans Serif"],
}
_families = None


def font_family(name):
    global _families
    if not name:
        return name
    if _families is None:
        _families = {f.lower(): f for f in QFontDatabase.families()}
    low = name.lower()
    if low in _families:
        return _families[low]
    for alt in FONT_FALLBACKS.get(low, ["DejaVu Sans Mono", "Monospace"]):
        if alt.lower() in _families:
            return _families[alt.lower()]
    return name


def parse_color(s):
    if not s:
        return None
    s = s.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return QColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def color_hex(c):
    return "%02X%02X%02X" % (c.red(), c.green(), c.blue()) if c is not None else ""


class Style:
    __slots__ = ("name", "id", "fg", "bg", "font", "fstyle", "size", "kwclass", "words", "elem")

    def __init__(self, el):
        self.elem = el
        self.name = el.get("name", "")
        try:
            self.id = int(el.get("styleID", "0"))
        except ValueError:
            self.id = 0
        self.fg = parse_color(el.get("fgColor"))
        self.bg = parse_color(el.get("bgColor"))
        self.font = el.get("fontName") or ""
        fs = el.get("fontStyle")
        self.fstyle = int(fs) if fs not in (None, "") and fs.lstrip("-").isdigit() else None
        sz = el.get("fontSize")
        self.size = int(sz) if sz not in (None, "") and sz.isdigit() else None
        self.kwclass = el.get("keywordClass")
        self.words = " ".join((el.text or "").split())

    def sync(self):
        el = self.elem
        if self.fg is not None:
            el.set("fgColor", color_hex(self.fg))
        if self.bg is not None:
            el.set("bgColor", color_hex(self.bg))
        if el.get("fontName") is not None or self.font:
            el.set("fontName", self.font)
        if self.fstyle is not None:
            el.set("fontStyle", str(self.fstyle))
        if el.get("fontSize") is not None or self.size:
            el.set("fontSize", str(self.size) if self.size else "")
        if self.kwclass:
            el.text = self.words


class LexerStyles:
    def __init__(self, el):
        self.elem = el
        self.name = el.get("name")
        self.desc = el.get("desc") or self.name
        self.ext = el.get("ext") or ""
        self.styles = [Style(w) for w in el.findall("WordsStyle")]


# Markdown has no LexerType in Notepad++ (it ships as a UDL); these are the
# UDL's colours mapped onto Scintilla's markdown lexer style IDs.
MD_LIGHT = {0: None, 1: None, 2: ("000000", 1), 3: ("000000", 1), 4: ("000000", 2), 5: ("000000", 2),
            6: ("0000FF", 1), 7: ("0000FF", 1), 8: ("0000FF", 1), 9: ("0000FF", 1), 10: ("0000FF", 1),
            11: ("0000FF", 1), 12: ("808080", 0), 13: ("FF8000", 0), 14: ("FF8000", 0),
            15: ("008000", 2), 16: ("808080", 0), 17: ("808080", 1), 18: ("0080C0", 4),
            19: ("8000FF", 0), 20: ("8000FF", 0), 21: ("8000FF", 0)}
MD_DARK = {2: ("E0E0E0", 1), 3: ("E0E0E0", 1), 4: ("E0E0E0", 2), 5: ("E0E0E0", 2),
           6: ("6FA8FF", 1), 7: ("6FA8FF", 1), 8: ("6FA8FF", 1), 9: ("6FA8FF", 1), 10: ("6FA8FF", 1),
           11: ("6FA8FF", 1), 12: ("909090", 0), 13: ("FFB050", 0), 14: ("FFB050", 0),
           15: ("80C080", 2), 16: ("909090", 0), 17: ("909090", 1), 18: ("60B0F0", 4),
           19: ("D0A0FF", 0), 20: ("D0A0FF", 0), 21: ("D0A0FF", 0)}


class StyleSet:
    def __init__(self, path):
        self.path = path
        self.tree = ET.parse(path)
        root = self.tree.getroot()
        self.lexers = {}
        self.lexer_order = []
        for lt in root.iter("LexerType"):
            ls = LexerStyles(lt)
            self.lexers[ls.name] = ls
            self.lexer_order.append(ls.name)
        self.globals = []
        gs = root.find(".//GlobalStyles")
        if gs is not None:
            self.globals = [Style(w) for w in gs.findall("WidgetStyle")]
        self.gmap = {g.name: g for g in self.globals}
        self.override = {}

    def clone(self):
        return copy.deepcopy(self)

    def g(self, name):
        return self.gmap.get(name)

    def gfg(self, name, default=None):
        st = self.gmap.get(name)
        return st.fg if st is not None and st.fg is not None else default

    def gbg(self, name, default=None):
        st = self.gmap.get(name)
        return st.bg if st is not None and st.bg is not None else default

    def default_style(self):
        return self.gmap.get("Default Style")

    def is_dark(self):
        bg = self.gbg("Default Style", QColor("white"))
        return bg.lightness() < 128

    def user_keywords(self, lexer, kwclass):
        ls = self.lexers.get(lexer)
        if not ls:
            return ""
        for st in ls.styles:
            if st.kwclass == kwclass and st.words:
                return st.words
        return ""

    def save(self, path=None):
        for g in self.globals:
            g.sync()
        for ls in self.lexers.values():
            for st in ls.styles:
                st.sync()
        try:
            ET.indent(self.tree, space="    ")
        except AttributeError:
            pass
        self.tree.write(path or self.path, encoding="UTF-8", xml_declaration=True)

    # ------------------------------------------------------------------ apply
    def _set_style(self, ed, sid, st, base_font, base_size):
        snd = ed.SendScintilla
        ov = self.override
        default = self.default_style()
        if st.fg is not None and not ov.get("fg"):
            snd(S.SCI_STYLESETFORE, sid, st.fg)
        if st.bg is not None and not ov.get("bg"):
            snd(S.SCI_STYLESETBACK, sid, st.bg)
        if st.font and not ov.get("font"):
            snd(S.SCI_STYLESETFONT, sid, font_family(st.font).encode())
        if st.size and not ov.get("size"):
            snd(S.SCI_STYLESETSIZE, sid, st.size)
        if st.fstyle is not None and st.fstyle >= 0:
            fs = st.fstyle
            if ov.get("bold"):
                fs = (fs & ~1) | ((default.fstyle or 0) & 1)
            if ov.get("italic"):
                fs = (fs & ~2) | ((default.fstyle or 0) & 2)
            if ov.get("underline"):
                fs = (fs & ~4) | ((default.fstyle or 0) & 4)
            snd(S.SCI_STYLESETBOLD, sid, bool(fs & 1))
            snd(S.SCI_STYLESETITALIC, sid, bool(fs & 2))
            snd(S.SCI_STYLESETUNDERLINE, sid, bool(fs & 4))

    def apply(self, ed, langdb, lang, settings):
        snd = ed.SendScintilla
        snd(S.SCI_STYLERESETDEFAULT)
        d = self.default_style()
        font = font_family(d.font if d and d.font else "Courier New")
        size = d.size if d and d.size else 10
        snd(S.SCI_STYLESETFONT, S.STYLE_DEFAULT, font.encode())
        snd(S.SCI_STYLESETSIZE, S.STYLE_DEFAULT, size)
        if d is not None:
            if d.fg is not None:
                snd(S.SCI_STYLESETFORE, S.STYLE_DEFAULT, d.fg)
            if d.bg is not None:
                snd(S.SCI_STYLESETBACK, S.STYLE_DEFAULT, d.bg)
            fs = d.fstyle or 0
            snd(S.SCI_STYLESETBOLD, S.STYLE_DEFAULT, bool(fs & 1))
            snd(S.SCI_STYLESETITALIC, S.STYLE_DEFAULT, bool(fs & 2))
            snd(S.SCI_STYLESETUNDERLINE, S.STYLE_DEFAULT, bool(fs & 4))
        snd(S.SCI_STYLECLEARALL)

        lg = langdb.get(lang)
        if lang == "markdown":
            table = MD_DARK if self.is_dark() else MD_LIGHT
            for sid, v in table.items():
                if v:
                    snd(S.SCI_STYLESETFORE, sid, parse_color(v[0]))
                    snd(S.SCI_STYLESETBOLD, sid, bool(v[1] & 1))
                    snd(S.SCI_STYLESETITALIC, sid, bool(v[1] & 2))
                    snd(S.SCI_STYLESETUNDERLINE, sid, bool(v[1] & 4))
            snd(S.SCI_STYLESETSIZE, 6, size + 3)
            snd(S.SCI_STYLESETSIZE, 7, size + 2)
            snd(S.SCI_STYLESETSIZE, 8, size + 1)
        else:
            for src in lg.style_sources:
                ls = self.lexers.get(src)
                if not ls:
                    continue
                for st in ls.styles:
                    if 0 <= st.id <= 255:
                        self._set_style(ed, st.id, st, font, size)

        # global widget styles with real style IDs
        for name, sid in (("Line number margin", S.STYLE_LINENUMBER),
                          ("Brace highlight style", S.STYLE_BRACELIGHT),
                          ("Bad brace colour", S.STYLE_BRACEBAD),
                          ("Indent guideline style", S.STYLE_INDENTGUIDE)):
            st = self.gmap.get(name)
            if st is not None:
                self._set_style(ed, sid, st, font, size)
        self.apply_widget_colors(ed, settings)

    def apply_widget_colors(self, ed, settings):
        snd = ed.SendScintilla
        dflt_bg = self.gbg("Default Style", QColor("white"))
        dflt_fg = self.gfg("Default Style", QColor("black"))
        # current line
        cl = self.gbg("Current line background colour", QColor("#E8E8FF"))
        mode = settings["caretline_mode"]
        snd(S.SCI_SETCARETLINEBACK, cl)
        snd(S.SCI_SETCARETLINEVISIBLE, mode != 0)
        snd(S.SCI_SETCARETLINEFRAME, settings["caretline_frame_width"] if mode == 2 else 0)
        snd(S.SCI_SETCARETLINEVISIBLEALWAYS, True)
        # selection
        sel = self.g("Selected text colour")
        if sel is not None and sel.bg is not None:
            snd(S.SCI_SETSELBACK, True, sel.bg)
        msel = self.gbg("Multi-selected text color")
        if msel is not None:
            snd(S.SCI_SETADDITIONALSELBACK, msel)
        snd(S.SCI_SETSELALPHA, 256)
        caret = self.gfg("Caret colour", QColor("#8000FF"))
        snd(S.SCI_SETCARETFORE, caret)
        mcaret = self.gfg("Multi-edit carets color")
        if mcaret is not None:
            snd(S.SCI_SETADDITIONALCARETFORE, mcaret)
        edge = self.gfg("Edge colour", QColor("#80FFFF"))
        snd(S.SCI_SETEDGECOLOUR, edge)
        # margins
        ln = self.g("Line number margin")
        bm = self.gbg("Bookmark margin", QColor("#E0E0E0"))
        ch = self.gbg("Change History margin", bm)
        ed.setMarginsBackgroundColor(ln.bg if ln is not None and ln.bg is not None else QColor("#E4E4E4"))
        ed.setMarginsForegroundColor(ln.fg if ln is not None and ln.fg is not None else QColor("#808080"))
        try:
            ed.setMarginBackgroundColor(1, bm)
            ed.setMarginBackgroundColor(2, ch)
        except Exception:
            pass
        fm = self.g("Fold margin")
        if fm is not None:
            snd(S.SCI_SETFOLDMARGINCOLOUR, True, fm.bg if fm.bg is not None else dflt_bg)
            snd(S.SCI_SETFOLDMARGINHICOLOUR, True, fm.fg if fm.fg is not None else dflt_bg)
        fold = self.g("Fold")
        ffg = fold.fg if fold is not None and fold.fg is not None else QColor("#808080")
        fbg = fold.bg if fold is not None and fold.bg is not None else QColor("#F3F3F3")
        fact = self.gfg("Fold active", QColor("#FF0000"))
        for m in range(25, 32):
            snd(S.SCI_MARKERSETFORE, m, fbg)
            snd(S.SCI_MARKERSETBACK, m, ffg)
            snd(S.SCI_MARKERSETBACKSELECTED, m, fact)
        snd(S.SCI_MARKERENABLEHIGHLIGHT, True)
        # change history markers
        snd(S.SCI_MARKERSETBACK, MARK_CH_MODIFIED, self.gbg("Change History modified", QColor("#FF8000")))
        snd(S.SCI_MARKERSETFORE, MARK_CH_MODIFIED, self.gfg("Change History modified", QColor("#FF8000")))
        snd(S.SCI_MARKERSETBACK, MARK_CH_SAVED, self.gbg("Change History saved", QColor("#00A000")))
        snd(S.SCI_MARKERSETFORE, MARK_CH_SAVED, self.gfg("Change History saved", QColor("#00A000")))
        # whitespace
        ws = self.gfg("White space symbol", QColor("#FFB56A"))
        snd(S.SCI_SETWHITESPACEFORE, True, ws)
        # indicators
        def indic(n, color, style=S.INDIC_ROUNDBOX, alpha=100, outline=150):
            snd(S.SCI_INDICSETSTYLE, n, style)
            snd(S.SCI_INDICSETFORE, n, color)
            snd(S.SCI_INDICSETALPHA, n, alpha)
            snd(S.SCI_INDICSETOUTLINEALPHA, n, outline)
            snd(S.SCI_INDICSETUNDER, n, True)
        indic(IND_SMART, self.gbg("Smart Highlighting", QColor("#00FF00")))
        indic(IND_FOUND, self.gbg("Find Mark Style", QColor("#FF0000")))
        for i, n in enumerate(MARK_STYLE_INDICS):
            indic(n, self.gbg("Mark Style %d" % (i + 1), QColor("#00FFFF")))
        indic(IND_INC, self.gbg("Incremental highlight all", QColor("#0080FF")))
        indic(IND_TAGMATCH, self.gbg("Tags match highlighting", QColor("#8000FF")))
        indic(IND_TAGATTR, self.gbg("Tags attribute", QColor("#FFFF00")))
        url = self.gfg("URL hovered", QColor("#0000FF"))
        if settings["link_fullbox"]:
            indic(IND_URL, url, S.INDIC_FULLBOX, 40, 100)
        else:
            snd(S.SCI_INDICSETSTYLE, IND_URL, S.INDIC_PLAIN if settings["link_underline"] else S.INDIC_HIDDEN)
            snd(S.SCI_INDICSETFORE, IND_URL, url)
            snd(S.SCI_INDICSETUNDER, IND_URL, False)
        snd(S.SCI_INDICSETHOVERSTYLE, IND_URL, S.INDIC_PLAIN)
        snd(S.SCI_INDICSETHOVERFORE, IND_URL, url)
        # call tips / autocompletion follow the theme
        ed.setCallTipsBackgroundColor(dflt_bg)
        ed.setCallTipsForegroundColor(dflt_fg)


def load_styleset(path):
    try:
        return StyleSet(path)
    except (ET.ParseError, OSError):
        from . import paths
        return StyleSet(paths.data("stylers.model.xml"))
