"""Auto-completion driven by Notepad++'s autoCompletion/*.xml API files
(function/word completion, function parameter hints, path completion)."""
import os
import re
import xml.etree.ElementTree as ET

from PyQt6.Qsci import QsciScintilla as S

from . import paths

FILEMAP = {"javascript.js": "javascript", "baanc": "BaanC", "coffeescript": "coffee", "typescript": "typescript",
           "mssql": "sql", "objc": "c", "json5": "javascript", "gdscript": "gdscript"}


class API:
    def __init__(self, path):
        self.words = []
        self.funcs = {}
        self.ignore_case = False
        self.start, self.stop, self.sep, self.term = "(", ")", ",", ""
        self.extra = ""
        if not path:
            return
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return
        env = root.find(".//Environment")
        if env is not None:
            self.ignore_case = env.get("ignoreCase", "no") == "yes"
            self.start = env.get("startFunc", "(") or "("
            self.stop = env.get("stopFunc", ")") or ")"
            self.sep = env.get("paramSeparator", ",") or ","
            self.term = env.get("terminal", "") or ""
            self.extra = env.get("additionalWordChar", "") or ""
        for kw in root.iter("KeyWord"):
            name = kw.get("name")
            if not name:
                continue
            self.words.append(name)
            if kw.get("func") == "yes":
                ovs = []
                for ov in kw.findall("Overload"):
                    params = [p.get("name", "") for p in ov.findall("Param")]
                    ovs.append((ov.get("retVal", ""), params, ov.get("descr", "")))
                self.funcs[name if not self.ignore_case else name.lower()] = (name, ovs)


class AutoCompleteMixin:
    def ac_init(self):
        self._apis = {}
        self._ct = None
        for v in self.views:
            v.editor.SCN_CALLTIPCLICK.connect(lambda pos, ed=v.editor: self.ac_calltip_cycle(ed, -1 if pos == 1 else 1))

    def api(self, lang):
        if lang not in self._apis:
            name = FILEMAP.get(lang, lang)
            p = paths.data("autoCompletion", name + ".xml")
            self._apis[lang] = API(p if os.path.exists(p) else None)
        return self._apis[lang]

    def _word_before(self, ed, extra=""):
        p = ed.pos()
        line = ed.line_from_pos(p)
        ls = ed.line_start(line)
        before = ed.get_range(max(ls, p - 400), p)
        m = re.search(r"[\w%s]+$" % re.escape(extra), before) if extra else re.search(r"\w+$", before)
        return m.group(0) if m else ""

    def ac_on_char(self, ed, c):
        if ed.buffer is None:
            return
        api = self.api(ed.buffer.lang)
        if self.S["param_hint"] and api.funcs and c in (api.start, api.sep, api.stop):
            if c == api.start:
                self.ac_calltip(ed)
            elif c == api.stop:
                ed.SendScintilla(S.SCI_CALLTIPCANCEL)
                self._ct = None
            elif self._ct:
                self._ct_highlight(ed)
            return
        if self._ct and ed.SendScintilla(S.SCI_CALLTIPACTIVE):
            self._ct_highlight(ed)
        if not self.S["ac_enable"]:
            return
        if not (c.isalnum() or c == "_" or (api.extra and c in api.extra)):
            return
        w = self._word_before(ed, api.extra)
        if len(w) < max(1, int(self.S["ac_from"])):
            return
        if self.S["ac_ignore_numbers"] and w[0].isdigit():
            return
        self.ac_complete(ed, self.S["ac_mode"])

    def ac_complete(self, ed, mode, manual=False):
        if ed.buffer is None:
            return
        api = self.api(ed.buffer.lang)
        w = self._word_before(ed, api.extra)
        if not w and not manual:
            return
        ic = api.ignore_case
        lw = w.lower()
        cands = set()
        if mode in ("func", "both"):
            for k in api.words:
                if (k.lower().startswith(lw) if ic else k.startswith(w)) and k != w:
                    cands.add(k)
        if mode in ("word", "both"):
            text = ed.get_bytes(0, min(ed.length(), 2_000_000)).decode("utf-8", "replace")
            rx = re.compile(r"(?<![\w%s])%s[\w%s]+" % (re.escape(api.extra), re.escape(w), re.escape(api.extra)) if w
                            else r"[A-Za-z_][\w]{2,}", re.I if ic else 0)
            for m in rx.finditer(text):
                t = m.group(0)
                if t != w and not (self.S["ac_ignore_numbers"] and t[0].isdigit()):
                    cands.add(t)
                if len(cands) > 3000:
                    break
        if not cands:
            if manual:
                ed.SendScintilla(S.SCI_AUTOCCANCEL)
            return
        items = sorted(cands, key=lambda s: (s.lower(), s))
        ed.SendScintilla(S.SCI_AUTOCSETIGNORECASE, True)
        ed.SendScintilla(S.SCI_AUTOCSETCASEINSENSITIVEBEHAVIOUR, 1)
        ed.SendScintilla(S.SCI_AUTOCSETSEPARATOR, ord("\n"))
        ed.SendScintilla(S.SCI_AUTOCSHOW, len(w.encode("utf-8")), "\n".join(items).encode("utf-8"))

    def ac_path(self, ed):
        p = ed.pos()
        line = ed.line_from_pos(p)
        before = ed.get_range(ed.line_start(line), p)
        m = re.search(r"[^\s\"'<>|]*$", before)
        frag = m.group(0) if m else ""
        if not frag:
            return
        exp = os.path.expanduser(frag)
        d, part = os.path.split(exp)
        if not d:
            b = self.buf()
            d = os.path.dirname(b.path) if b and b.path else os.getcwd()
        try:
            names = sorted(n for n in os.listdir(d) if n.startswith(part))
        except OSError:
            return
        names = [n + ("/" if os.path.isdir(os.path.join(d, n)) else "") for n in names]
        if names:
            ed.SendScintilla(S.SCI_AUTOCSETSEPARATOR, ord("\n"))
            ed.SendScintilla(S.SCI_AUTOCSHOW, len(part.encode()), "\n".join(names).encode("utf-8"))

    # ----------------------------------------------------------- call tips
    def _call_context(self, ed, api):
        """Find the innermost unclosed startFunc before the caret -> (name, open_pos_bytes)."""
        p = ed.pos()
        start = max(0, p - 4000)
        text = ed.get_range(start, p)
        depth = 0
        i = len(text) - 1
        while i >= 0:
            ch = text[i]
            if ch == api.stop:
                depth += 1
            elif ch == api.start:
                if depth == 0:
                    m = re.search(r"([\w%s]+)\s*$" % re.escape(api.extra), text[:i])
                    if m:
                        return m.group(1), start + len(text[:i].encode("utf-8")), text[i + 1:]
                    return None
                depth -= 1
            elif ch in "\n;{}" and depth == 0 and ch != "\n":
                return None
            i -= 1
        return None

    def ac_calltip(self, ed, manual=False):
        if ed.buffer is None:
            return
        api = self.api(ed.buffer.lang)
        ctx = self._call_context(ed, api)
        if not ctx:
            return
        name, open_pos, _ = ctx
        key = name.lower() if api.ignore_case else name
        f = api.funcs.get(key)
        if not f or not f[1]:
            return
        self._ct = {"name": f[0], "ovs": f[1], "idx": 0, "pos": open_pos, "api": api}
        self._ct_show(ed)

    def _ct_text(self):
        ct = self._ct
        api = ct["api"]
        ret, params, descr = ct["ovs"][ct["idx"]]
        head = "%s %s%s" % (ret, ct["name"], api.start) if ret else "%s%s" % (ct["name"], api.start)
        spans = []
        cur = len(head.encode("utf-8"))
        parts = []
        for j, prm in enumerate(params):
            if j:
                parts.append(api.sep + " ")
                cur += len((api.sep + " ").encode("utf-8"))
            spans.append((cur, cur + len(prm.encode("utf-8"))))
            parts.append(prm)
            cur += len(prm.encode("utf-8"))
        txt = head + "".join(parts) + api.stop
        prefix = ""
        if len(ct["ovs"]) > 1:
            prefix = "\001 %d of %d \002" % (ct["idx"] + 1, len(ct["ovs"]))
            off = len(prefix.encode("utf-8"))
            spans = [(a + off, b + off) for a, b in spans]
        if descr:
            txt += "\n" + descr
        return prefix + txt, spans

    def _ct_show(self, ed):
        txt, spans = self._ct_text()
        self._ct["spans"] = spans
        ed.SendScintilla(S.SCI_CALLTIPSHOW, self._ct["pos"], txt.encode("utf-8"))
        self._ct_highlight(ed)

    def _ct_highlight(self, ed):
        ct = self._ct
        if not ct:
            return
        api = ct["api"]
        p = ed.pos()
        if p <= ct["pos"]:
            ed.SendScintilla(S.SCI_CALLTIPCANCEL)
            self._ct = None
            return
        inside = ed.get_range(ct["pos"] + 1, p)
        depth = 0
        n = 0
        for ch in inside:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth < 0:
                    ed.SendScintilla(S.SCI_CALLTIPCANCEL)
                    self._ct = None
                    return
            elif ch == api.sep and depth == 0:
                n += 1
        spans = ct.get("spans") or []
        if n < len(spans):
            ed.SendScintilla(S.SCI_CALLTIPSETHLT, spans[n][0], spans[n][1])
        else:
            ed.SendScintilla(S.SCI_CALLTIPSETHLT, 0, 0)

    def ac_calltip_cycle(self, ed, d):
        if not self._ct:
            self.ac_calltip(ed, manual=True)
            return
        n = len(self._ct["ovs"])
        self._ct["idx"] = (self._ct["idx"] + d) % n
        self._ct_show(ed)
