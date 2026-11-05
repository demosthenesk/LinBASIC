"""Notepad++ functionList/*.xml parser engine (FunctionMixParser semantics):
comment zones, classRange (mainExpr + open/close symbols), nested functions and
className/functionName nameExpr chains."""
import os
import xml.etree.ElementTree as ET
import bisect
import re

import regex

from . import paths
from .search import translate_boost

FLAGS = regex.MULTILINE | regex.DOTALL | regex.V0

# lang -> parser file (overrideMap.xml uses N++ LangType numbers; same idea)
FILE_FOR = {"javascript.js": "javascript.js", "javascript": "javascript.js", "fortran77": "fortran77",
            "gdscript": "gdscript", "scheme": "scheme", "nim": "nim", "objc": "objc"}

_cache = {}


def _rx(expr):
    if not expr:
        return None
    try:
        return regex.compile(translate_boost(expr), FLAGS)
    except regex.error:
        try:
            return regex.compile(expr, FLAGS)
        except regex.error:
            return None


class Parser:
    def __init__(self, el):
        self.name = el.get("displayName", "")
        self.comment = _rx(el.get("commentExpr"))
        cr = el.find("classRange")
        self.cls = None
        if cr is not None:
            self.cls = {
                "main": _rx(cr.get("mainExpr")),
                "open": cr.get("openSymbole") or "",
                "close": cr.get("closeSymbole") or "",
                "names": [_rx(n.get("expr")) for n in cr.findall("className/nameExpr")],
                "func": None, "func_names": [],
            }
            f = cr.find("function")
            if f is not None:
                self.cls["func"] = _rx(f.get("mainExpr"))
                self.cls["func_names"] = [_rx(n.get("expr")) for n in f.findall("functionName/funcNameExpr")]
        f = el.find("function")
        self.func = None
        if f is not None:
            self.func = {
                "main": _rx(f.get("mainExpr")),
                "names": [_rx(n.get("expr")) for n in f.findall("functionName/nameExpr")],
                "cls_names": [_rx(n.get("expr")) for n in f.findall("className/nameExpr")],
            }


def get_parser(lang):
    if lang in _cache:
        return _cache[lang]
    fn = FILE_FOR.get(lang, lang)
    p = None
    for d in (paths.cfg("functionList"), paths.data("functionList")):
        path = os.path.join(d, fn + ".xml")
        if os.path.exists(path):
            try:
                # TinyXML (used by Notepad++) keeps newlines inside attribute values;
                # standard XML parsers normalise them to spaces, which would turn
                # every (?x) '# comment' into a comment running to the end.
                with open(path, encoding="utf-8") as f:
                    raw = f.read()
                raw = re.sub(r'(=\s*")([^"]*)(")',
                             lambda m: m.group(1) + m.group(2).replace("\r\n", "&#10;").replace("\n", "&#10;") + m.group(3),
                             raw)
                root = ET.fromstring(raw)
                el = root.find(".//parser")
                if el is not None:
                    p = Parser(el)
            except ET.ParseError:
                p = None
            break
    _cache[lang] = p
    return p


def _chain(text, exprs):
    """Apply successive nameExpr regexes; return (offset, name) or None."""
    off = 0
    cur = text
    for rx in exprs:
        if rx is None:
            continue
        # Notepad++'s function parser ignores zero-length matches
        m = next((x for x in rx.finditer(cur) if x.end() > x.start()), None)
        if not m:
            return None
        off += m.start()
        cur = m.group(0)
    return off, cur.strip()


def parse(text, lang, timeout=2.0):
    """Return list of (class_name or None, func_name, char_offset)."""
    p = get_parser(lang)
    if p is None:
        return None
    zones = []
    if p.comment is not None:
        try:
            for m in p.comment.finditer(text, timeout=timeout):
                if m.end() > m.start():
                    zones.append((m.start(), m.end()))
        except TimeoutError:
            pass
    starts = [z[0] for z in zones]

    def in_comment(pos):
        i = bisect.bisect_right(starts, pos) - 1
        return i >= 0 and zones[i][0] <= pos < zones[i][1]

    out = []
    ranges = []
    if p.cls and p.cls["main"] is not None:
        try:
            for m in p.cls["main"].finditer(text, timeout=timeout):
                if m.end() == m.start() or in_comment(m.start()):
                    continue
                r = _chain(m.group(0), p.cls["names"])
                cname = r[1] if r else None
                start = m.start()
                end = m.end()
                if p.cls["open"] and p.cls["close"]:
                    ro = _rx(p.cls["open"])
                    rc = _rx(p.cls["close"])
                    om = ro.search(text, m.start()) if ro else None
                    if om is None:
                        continue
                    depth = 0
                    pos = om.start()
                    end = len(text)
                    combo = regex.compile("(%s)|(%s)" % (ro.pattern, rc.pattern), FLAGS)
                    for t in combo.finditer(text, om.start()):
                        if in_comment(t.start()):
                            continue
                        if t.group(1) is not None:
                            depth += 1
                        else:
                            depth -= 1
                            if depth == 0:
                                end = t.end()
                                break
                ranges.append((start, end))
                if cname:
                    out.append((cname, None, start))
                if p.cls["func"] is not None:
                    for fm in p.cls["func"].finditer(text, m.start() if not p.cls["open"] else m.end(), end, timeout=timeout):
                        if fm.end() == fm.start() or in_comment(fm.start()):
                            continue
                        r2 = _chain(fm.group(0), p.cls["func_names"])
                        if r2 and r2[1]:
                            out.append((cname, r2[1], fm.start() + r2[0]))
        except TimeoutError:
            pass
    if p.func and p.func["main"] is not None:
        rstarts = [r[0] for r in ranges]

        def in_class(pos):
            i = bisect.bisect_right(rstarts, pos) - 1
            return i >= 0 and ranges[i][0] <= pos < ranges[i][1]
        try:
            for m in p.func["main"].finditer(text, timeout=timeout):
                if m.end() == m.start() or in_comment(m.start()) or in_class(m.start()):
                    continue
                r = _chain(m.group(0), p.func["names"])
                if not r or not r[1]:
                    continue
                cname = None
                if p.func["cls_names"]:
                    rc = _chain(m.group(0), p.func["cls_names"])
                    if rc and rc[1]:
                        cname = rc[1]
                out.append((cname, r[1], m.start() + r[0]))
        except TimeoutError:
            pass
    out.sort(key=lambda x: x[2])
    return out
