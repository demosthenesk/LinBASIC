"""Search engine shared by Find / Replace / Mark / Find in Files.

Notepad++ uses Boost.Regex through Scintilla; here the `regex` module plays
that role (it supports \\K, possessive/atomic groups, recursion (?&name)), with
the remaining Boost-only escapes translated. Positions given to/returned from
Scintilla are UTF-8 byte offsets, so matches found on the decoded text are
mapped back incrementally."""
import fnmatch
import os

import regex

MODE_NORMAL, MODE_EXTENDED, MODE_REGEX = "normal", "extended", "regex"


class Opts:
    def __init__(self, text="", replace="", mode=MODE_NORMAL, match_case=False, whole_word=False,
                 wrap=True, backward=False, in_selection=False, dot_nl=False):
        self.text = text
        self.replace = replace
        self.mode = mode
        self.match_case = match_case
        self.whole_word = whole_word
        self.wrap = wrap
        self.backward = backward
        self.in_selection = in_selection
        self.dot_nl = dot_nl

    def copy(self, **kw):
        o = Opts(self.text, self.replace, self.mode, self.match_case, self.whole_word,
                 self.wrap, self.backward, self.in_selection, self.dot_nl)
        for k, v in kw.items():
            setattr(o, k, v)
        return o


def expand_extended(s):
    """\\n \\r \\t \\0 \\\\ \\xHH \\uHHHH \\oOOO \\dDDD \\bBBBBBBBB (Notepad++ Extended mode)."""
    out = []
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        e = s[i + 1]
        simple = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\", "a": "\a",
                  "f": "\f", "v": "\v"}
        if e in simple:
            out.append(simple[e])
            i += 2
            continue
        spec = {"x": (2, 16), "u": (4, 16), "o": (3, 8), "d": (3, 10), "b": (8, 2)}
        if e in spec:
            ln, base = spec[e]
            digits = s[i + 2:i + 2 + ln]
            try:
                if len(digits) == ln:
                    out.append(chr(int(digits, base)))
                    i += 2 + ln
                    continue
            except ValueError:
                pass
        out.append(c)
        i += 1
    return "".join(out)


def translate_boost(p):
    """Translate the Boost-only bits the regex module lacks."""
    out = []
    i = 0
    n = len(p)
    in_class = False
    while i < n:
        c = p[i]
        if c == "\\" and i + 1 < n:
            e = p[i + 1]
            if e == "h":
                out.append(r"\t\x20" if in_class else r"[\t\x20]")
            elif e == "H":
                out.append(r"[^\t\x20]")
            elif e == "R" and not in_class:
                out.append(r"(?:\r\n|\n|\r)")
            elif e == "<" and not in_class:
                out.append(r"\b(?=\w)")
            elif e == ">" and not in_class:
                out.append(r"\b(?<=\w)")
            elif e == "Q":
                j = p.find(r"\E", i + 2)
                lit = p[i + 2:] if j < 0 else p[i + 2:j]
                out.append(regex.escape(lit))
                i = n if j < 0 else j + 2
                continue
            else:
                out.append(c + e)
            i += 2
            continue
        if in_class:
            if c == "[" and p.startswith("[:", i):
                j = p.find(":]", i + 2)
                if j > 0:
                    out.append(p[i:j + 2])
                    i = j + 2
                    continue
            if c == "]":
                in_class = False
            out.append(c)
            i += 1
            continue
        if c == "[":
            in_class = True
            out.append(c)
            i += 1
            if i < n and p[i] == "^":
                out.append("^")
                i += 1
            if i < n and p[i] == "]":
                out.append(r"\]")
                i += 1
            continue
        if c == "(" and p.startswith("(?'", i):
            j = p.find("'", i + 3)
            if j > 0:
                out.append("(?P<%s>" % p[i + 3:j])
                i = j + 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def compile_opts(opts, extra_word_chars=""):
    text = opts.text
    if opts.mode == MODE_REGEX:
        pat = translate_boost(text)
    elif opts.mode == MODE_EXTENDED:
        pat = regex.escape(expand_extended(text))
    else:
        pat = regex.escape(text)
    if opts.whole_word:
        wc = r"\w" + regex.escape(extra_word_chars) if extra_word_chars else r"\w"
        pat = r"(?<![%s])(?:%s)(?![%s])" % (wc, pat, wc)
    flags = regex.MULTILINE | regex.V0
    if not opts.match_case:
        flags |= regex.IGNORECASE
    if opts.mode == MODE_REGEX and opts.dot_nl:
        flags |= regex.DOTALL
    return regex.compile(pat, flags)


_CASE_OPS = {"U", "L", "E", "u", "l"}


def expand_replacement(m, repl, mode):
    """Boost 'format_default' replacement as used by Notepad++."""
    if mode == MODE_NORMAL:
        return repl
    if mode == MODE_EXTENDED:
        return expand_extended(repl)
    out = []
    case = None       # 'U' or 'L' until \E
    once = None       # 'u' or 'l' for the next char

    def emit(s):
        nonlocal once
        if not s:
            return
        if case == "U":
            s = s.upper()
        elif case == "L":
            s = s.lower()
        if once:
            s = (s[0].upper() if once == "u" else s[0].lower()) + s[1:]
            once = None
        out.append(s)

    def grp(key):
        try:
            v = m.group(key)
        except (IndexError, regex.error):
            return ""
        return v or ""

    i = 0
    n = len(repl)
    while i < n:
        c = repl[i]
        if c == "\\" and i + 1 < n:
            e = repl[i + 1]
            if e.isdigit():
                emit(grp(int(e)))
            elif e in _CASE_OPS:
                if e in ("U", "L"):
                    case = e
                elif e == "E":
                    case = None
                else:
                    once = e
            elif e == "n":
                emit("\n")
            elif e == "r":
                emit("\r")
            elif e == "t":
                emit("\t")
            elif e == "x" and i + 3 < n + 1:
                h = repl[i + 2:i + 4]
                if repl[i + 2:i + 3] == "{":
                    j = repl.find("}", i + 3)
                    emit(chr(int(repl[i + 3:j], 16)))
                    i = j + 1
                    continue
                try:
                    emit(chr(int(h, 16)))
                    i += 4
                    continue
                except ValueError:
                    emit("x")
            else:
                emit(e)
            i += 2
            continue
        if c == "$" and i + 1 < n:
            e = repl[i + 1]
            if e == "$":
                emit("$")
                i += 2
                continue
            if e == "&":
                emit(m.group(0))
                i += 2
                continue
            if e.isdigit():
                j = i + 1
                while j < n and repl[j].isdigit() and j - i <= 2:
                    j += 1
                emit(grp(int(repl[i + 1:j])))
                i = j
                continue
            if e == "{":
                j = repl.find("}", i + 2)
                if j > 0:
                    key = repl[i + 2:j]
                    emit(grp(int(key) if key.isdigit() else key))
                    i = j + 1
                    continue
            if e == "+":
                last = m.lastindex
                emit(grp(last) if last else "")
                i += 2
                continue
        if c == "(" and repl.startswith("(?", i) and i + 2 < n and repl[i + 2].isdigit():
            # Boost conditional (?N:yes:no)
            j = i + 2
            while j < n and repl[j].isdigit():
                j += 1
            k = repl.find(":", j)
            close = _find_close(repl, i)
            if k > 0 and close > 0:
                body = repl[k + 1:close]
                parts = _split_top(body)
                yes = parts[0]
                no = parts[1] if len(parts) > 1 else ""
                emit(expand_replacement(m, yes if grp(int(repl[i + 2:j])) else no, mode))
                i = close + 1
                continue
        emit(c)
        i += 1
    return "".join(out)


def _find_close(s, start):
    depth = 0
    i = start
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == "(":
            depth += 1
        elif s[i] == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_top(s):
    parts, depth, cur, i = [], 0, [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            cur.append(s[i:i + 2])
            i += 2
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == ":" and depth == 0 and len(parts) == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    parts.append("".join(cur))
    return parts


class ByteMapper:
    """Map character offsets of `text` to UTF-8 byte offsets, monotonically."""

    def __init__(self, text, char0=0, byte0=0):
        self.text = text
        self.c = char0
        self.b = byte0

    def to_byte(self, ci):
        if ci < self.c:
            self.c, self.b = 0, 0
        self.b += len(self.text[self.c:ci].encode("utf-8", errors="surrogateescape"))
        self.c = ci
        return self.b


class DocText:
    """Raw UTF-8 bytes of a Scintilla document plus its decoded text."""

    def __init__(self, raw):
        self.raw = raw
        self.text = raw.decode("utf-8", errors="surrogateescape")

    def b2c(self, bi):
        return len(self.raw[:bi].decode("utf-8", errors="surrogateescape"))

    def c2b(self, ci):
        return len(self.text[:ci].encode("utf-8", errors="surrogateescape"))


def iter_matches(rx, text, start=0, end=None):
    """Yield (char_start, char_end, match) skipping the empty-match trap."""
    if end is None:
        end = len(text)
    pos = start
    while pos <= end:
        m = rx.search(text, pos, end)
        if not m:
            return
        yield m
        if m.end() == m.start():
            pos = m.end() + 1
        else:
            pos = m.end()


def parse_filters(filters):
    inc, exc, exc_dirs, exc_dirs_rec = [], [], [], []
    for f in filters.replace(";", " ").split():
        if f.startswith("!+\\") or f.startswith("!+/"):
            exc_dirs_rec.append(f[3:])
        elif f.startswith("!\\") or f.startswith("!/"):
            exc_dirs.append(f[2:])
        elif f.startswith("!"):
            exc.append(f[1:])
        else:
            inc.append(f)
    if not inc:
        inc = ["*"]
    return inc, exc, exc_dirs, exc_dirs_rec


def walk_files(directory, filters, recursive=True, hidden=False):
    inc, exc, exc_dirs, exc_dirs_rec = parse_filters(filters)
    for root, dirs, files in os.walk(directory):
        if not hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files = [f for f in files if not f.startswith(".")]
        rel_top = os.path.relpath(root, directory)
        dirs[:] = [d for d in dirs
                   if not any(fnmatch.fnmatch(d, p) for p in exc_dirs_rec)
                   and not (rel_top == "." and any(fnmatch.fnmatch(d, p) for p in exc_dirs))]
        if not recursive:
            dirs[:] = []
        for f in sorted(files, key=str.lower):
            if any(fnmatch.fnmatch(f, p) for p in exc):
                continue
            if any(fnmatch.fnmatch(f.lower(), p.lower()) for p in inc):
                yield os.path.join(root, f)
