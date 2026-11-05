"""Native re-implementations of the three plugins shipped in the Notepad++
portable package: MIME Tools, Converter and NppExport (command names recovered
from mimeTools.dll / NppConverter.dll / NppExport.dll)."""
import base64
import binascii
import configparser
import html
import quopri
import urllib.parse
import zlib

from PyQt6.QtCore import QMimeData, QByteArray
from PyQt6.QtWidgets import (QApplication, QMessageBox, QFileDialog, QDialog, QGridLayout, QLabel,
                             QLineEdit, QPushButton)
from PyQt6.Qsci import QsciScintilla as S

from . import paths


# ----------------------------------------------------------------- helpers
def _target(main):
    ed = main.editor()
    a, b = ed.sel_range()
    if a == b:
        return ed, 0, ed.length()
    return ed, a, b


def _apply(main, fn, title):
    ed, a, b = _target(main)
    raw = ed.get_bytes(a, b)
    try:
        out = fn(raw)
    except Exception as ex:   # mirrors the plugins' "Problem!" boxes
        QMessageBox.warning(main, title, "%s\n\n%s" % (title, ex))
        return
    if isinstance(out, str):
        out = out.encode("utf-8")
    ed.SendScintilla(S.SCI_BEGINUNDOACTION)
    ed.SendScintilla(S.SCI_SETTARGETRANGE, a, b)
    ed.SendScintilla(S.SCI_REPLACETARGET, len(out), out)
    ed.SendScintilla(S.SCI_ENDUNDOACTION)
    ed.set_sel(a, a + len(out))


def _by_line(fn):
    def g(raw):
        lines = raw.splitlines(keepends=True)
        out = []
        for l in lines:
            body = l.rstrip(b"\r\n")
            eol = l[len(body):]
            out.append(fn(body) + eol)
        return b"".join(out)
    return g


def b64enc(pad=False, unix=False):
    def f(raw):
        s = base64.b64encode(raw)
        if not pad:
            s = s.rstrip(b"=")
        if unix:
            s = b"\n".join(s[i:i + 64] for i in range(0, len(s), 64))
        return s
    return f


def b64dec(strict=False):
    def f(raw):
        s = b"".join(raw.split())
        if strict:
            return base64.b64decode(s, validate=True)
        s = bytes(c for c in s if c in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/-_")
        s = s.replace(b"-", b"+").replace(b"_", b"/")
        return base64.b64decode(s + b"=" * (-len(s) % 4))
    return f


def url_enc(kind):
    safe = {"rfc1738": "$-_.+!*'(),", "extended": "-_.~", "full": ""}[kind]

    def f(raw):
        if kind == "full":
            return "".join("%%%02X" % c for c in raw)
        return urllib.parse.quote_from_bytes(raw, safe=safe)
    return f


def url_dec(raw):
    return urllib.parse.unquote_to_bytes(raw.replace(b"+", b" "))


def saml_dec(raw):
    s = urllib.parse.unquote_to_bytes(raw)
    d = base64.b64decode(b"".join(s.split()) + b"=" * (-len(b"".join(s.split())) % 4))
    return zlib.decompress(d, -15)


def qp_enc(raw):
    return quopri.encodestring(raw)


def qp_dec(raw):
    return quopri.decodestring(raw)


# --------------------------------------------------------------- converter
def _conv_cfg():
    cp = configparser.ConfigParser()
    p = paths.cfg("plugins", "Config", "converter.ini")
    if not cp.read(p):
        cp["ascii2Hex"] = {"insertSpace": "0", "uppercase": "1", "nbCharPerLine": "16"}
        try:
            with open(p, "w") as f:
                f.write("; ASCII -> Hex parameters (insertSpace, uppercase, nbCharPerLine)\n")
                cp.write(f)
        except OSError:
            pass
    sec = cp["ascii2Hex"] if "ascii2Hex" in cp else {}
    return (sec.get("insertSpace", "0") == "1", sec.get("uppercase", "1") == "1",
            int(sec.get("nbCharPerLine", "16") or 0))


def ascii2hex(raw):
    space, upper, per_line = _conv_cfg()
    fmt = "%02X" if upper else "%02x"
    hx = [fmt % c for c in raw]
    sep = " " if space else ""
    if per_line > 0:
        return "\n".join(sep.join(hx[i:i + per_line]) for i in range(0, len(hx), per_line))
    return sep.join(hx)


def hex2ascii(raw):
    s = b"".join(raw.split())
    return binascii.unhexlify(s)


class ConversionPanel(QDialog):
    def __init__(self, main):
        super().__init__(main)
        self.setWindowTitle("Conversion Panel")
        g = QGridLayout(self)
        self.fields = {}
        for row, (name, base) in enumerate((("ASCII", None), ("Decimal", 10), ("Hexadecimal", 16),
                                            ("Binary", 2), ("Octal", 8))):
            g.addWidget(QLabel(name), row, 0)
            le = QLineEdit()
            le.textEdited.connect(lambda t, b=base: self.update_from(b, t))
            g.addWidget(le, row, 1)
            ins = QPushButton("Insert")
            ins.clicked.connect(lambda checked=False, l=le: main.editor().replaceSelectedText(l.text()))
            g.addWidget(ins, row, 2)
            self.fields[base] = le
        self.resize(420, 200)

    def update_from(self, base, text):
        try:
            if base is None:
                v = ord(text[-1]) if text else None
            else:
                v = int(text, base) if text else None
        except ValueError:
            return
        for b, le in self.fields.items():
            if b == base:
                continue
            if v is None:
                le.setText("")
            elif b is None:
                le.setText(chr(v) if 0 <= v < 0x110000 else "")
            else:
                le.setText({10: str, 16: lambda x: "%X" % x, 2: lambda x: bin(x)[2:], 8: lambda x: oct(x)[2:]}[b](v))


# ---------------------------------------------------------------- NppExport
def _styled_runs(ed, a, b):
    ed.SendScintilla(S.SCI_COLOURISE, 0, -1)
    runs = []
    p = a
    while p < b:
        st = ed.SendScintilla(S.SCI_GETSTYLEAT, p)
        q = p + 1
        while q < b and ed.SendScintilla(S.SCI_GETSTYLEAT, q) == st:
            q += 1
        runs.append((st, ed.get_bytes(p, q).decode("utf-8", "replace")))
        p = q
    return runs


def _style_info(ed, st):
    def rgb(bgr):
        return (bgr & 0xFF, (bgr >> 8) & 0xFF, (bgr >> 16) & 0xFF)
    return {
        "fg": rgb(ed.SendScintilla(S.SCI_STYLEGETFORE, st)),
        "bg": rgb(ed.SendScintilla(S.SCI_STYLEGETBACK, st)),
        "b": bool(ed.SendScintilla(S.SCI_STYLEGETBOLD, st)),
        "i": bool(ed.SendScintilla(S.SCI_STYLEGETITALIC, st)),
        "u": bool(ed.SendScintilla(S.SCI_STYLEGETUNDERLINE, st)),
    }


def _font(ed):
    from .styles import font_family
    d = ed.main.styles.default_style()
    return font_family(d.font if d and d.font else "Courier New"), (d.size if d and d.size else 10)


def to_html(main):
    ed, a, b = _target(main)
    runs = _styled_runs(ed, a, b)
    used = sorted({s for s, _ in runs})
    font, size = _font(ed)
    css = []
    for st in used:
        i = _style_info(ed, st)
        css.append(".sc%d { color:#%02X%02X%02X; background:#%02X%02X%02X;%s%s%s }" % (
            (st,) + i["fg"] + i["bg"] + (" font-weight:bold;" if i["b"] else "",
                                         " font-style:italic;" if i["i"] else "",
                                         " text-decoration:underline;" if i["u"] else "")))
    dflt = _style_info(ed, S.STYLE_DEFAULT)
    body = "".join('<span class="sc%d">%s</span>' % (st, html.escape(t).replace("\t", "    ")) for st, t in runs)
    name = main.buf().name() if main.buf() else "export"
    return ("<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"UTF-8\">\n<title>%s</title>\n<style>\n"
            "div { font-family:'%s', monospace; font-size:%dpt; white-space:pre; background:#%02X%02X%02X; }\n%s\n"
            "</style>\n</head>\n<body>\n<div>%s</div>\n</body>\n</html>\n"
            % (html.escape(name), font, size, *dflt["bg"], "\n".join(css), body))


def to_rtf(main):
    ed, a, b = _target(main)
    runs = _styled_runs(ed, a, b)
    font, size = _font(ed)
    colors = []

    def cidx(c):
        if c not in colors:
            colors.append(c)
        return colors.index(c) + 1
    parts = []
    for st, t in runs:
        i = _style_info(ed, st)
        fg, bg = cidx(i["fg"]), cidx(i["bg"])
        esc = []
        for ch in t:
            o = ord(ch)
            if ch in "\\{}":
                esc.append("\\" + ch)
            elif ch == "\n":
                esc.append("\\par\n")
            elif ch == "\r":
                continue
            elif ch == "\t":
                esc.append("\\tab ")
            elif o > 127:
                esc.append("\\u%d?" % (o if o < 32768 else o - 65536))
            else:
                esc.append(ch)
        parts.append("{\\cf%d\\highlight%d%s%s%s %s}" % (fg, bg, "\\b" if i["b"] else "", "\\i" if i["i"] else "",
                                                         "\\ul" if i["u"] else "", "".join(esc)))
    ct = "".join("\\red%d\\green%d\\blue%d;" % c for c in colors)
    return "{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0\\fmodern %s;}}{\\colortbl;%s}\\f0\\fs%d %s}" % (font, ct, size * 2, "".join(parts))


def export_file(main, kind):
    data = to_html(main) if kind == "html" else to_rtf(main)
    b = main.buf()
    start = (b.path if b and b.path else (b.name() if b else "export")) + "." + kind
    p, _ = QFileDialog.getSaveFileName(main, "Export", start, ("HTML file (*.html)" if kind == "html" else "RTF file (*.rtf)") + ";;All files (*)")
    if p:
        with open(p, "w", encoding="utf-8") as f:
            f.write(data)


def copy_formats(main, kinds):
    md = QMimeData()
    ed, a, b = _target(main)
    md.setText(ed.get_bytes(a, b).decode("utf-8", "replace"))
    if "html" in kinds:
        md.setHtml(to_html(main))
    if "rtf" in kinds:
        r = to_rtf(main).encode("utf-8")
        md.setData("text/rtf", QByteArray(r))
        md.setData("application/rtf", QByteArray(r))
    QApplication.clipboard().setMimeData(md)


def menu_spec():
    def ap(fn, title):
        return lambda m: _apply(m, fn, title)
    mime = [
        ("Base64 Encode", ap(b64enc(), "Base64")), ("Base64 Encode with padding", ap(b64enc(pad=True), "Base64")),
        ("Base64 Encode with Unix EOL", ap(b64enc(pad=True, unix=True), "Base64")),
        ("Base64 Encode by line", ap(_by_line(b64enc(pad=True)), "Base64")),
        ("Base64 Decode", ap(b64dec(), "Base64")), ("Base64 Decode strict", ap(b64dec(True), "Base64")),
        ("Base64 Decode by line", ap(_by_line(b64dec()), "Base64")), (None, None),
        ("Quoted-printable Encode", ap(qp_enc, "Quoted-printable encoding")),
        ("Quoted-printable Decode", ap(qp_dec, "Quoted-printable decode error")), (None, None),
        ("URL Encode (RFC1738)", ap(url_enc("rfc1738"), "URL Encode")),
        ("URL Encode (RFC1738) by line", ap(_by_line(url_enc("rfc1738")), "URL Encode")),
        ("URL Encode (Extended)", ap(url_enc("extended"), "URL Encode")),
        ("URL Encode (Extended) by line", ap(_by_line(url_enc("extended")), "URL Encode")),
        ("URL Encode (Full)", ap(url_enc("full"), "URL Encode")),
        ("URL Encode (Full) by line", ap(_by_line(url_enc("full")), "URL Encode")),
        ("URL Decode", ap(url_dec, "URL Decode")), (None, None),
        ("SAML Decode", ap(saml_dec, "SAML Decode")), (None, None),
        ("About", lambda m: QMessageBox.about(m, "MIME Tools", "MIME Tools — built into LinBASIC\n(Base64, Quoted-printable, URL, SAML)")),
    ]
    conv = [
        ("ASCII -> HEX", ap(ascii2hex, "Converter")), ("HEX -> ASCII", ap(hex2ascii, "Converter")), (None, None),
        ("Conversion Panel", lambda m: ConversionPanel(m).show()),
        ("Edit Configuration File", lambda m: (_conv_cfg(), m.open_file(paths.cfg("plugins", "Config", "converter.ini")))),
        ("About", lambda m: QMessageBox.about(m, "Converter", "Converter — built into LinBASIC")),
    ]
    exp = [
        ("&Export to RTF", lambda m: export_file(m, "rtf")), ("&Export to HTML", lambda m: export_file(m, "html")),
        (None, None),
        ("&Copy RTF to clipboard", lambda m: copy_formats(m, ["rtf"])),
        ("&Copy HTML to clipboard", lambda m: copy_formats(m, ["html"])),
        ("&Copy all formats to clipboard", lambda m: copy_formats(m, ["rtf", "html"])),
    ]
    return [("MIME Tools", mime), ("Converter", conv), ("NppExport", exp)]
