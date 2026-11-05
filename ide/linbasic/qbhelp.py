#!/usr/bin/env python3
"""
qbhelp -- decoder for Microsoft QuickHelp (.HLP) help databases.

Written for the help files shipped with QB 4.5 (QB45ADVR.HLP,
QB45ENER.HLP, QB45QCK.HLP) but works with any QuickHelp database
(signature "LN", version 2).  Standard library only, Python 3.8+.

Pipeline (see the QuickHelp format description):

    file bytes -> [database ...]            (databases may be concatenated)
    topic blob -> OUTLEN + Huffman bitstream
               -> Huffman decode            -> compact stream
               -> keyword / RLE expansion   -> binary topic (OUTLEN bytes)
               -> lines (text + attributes) -> colon commands / visible lines

Public API
----------
HelpDatabase      one database: name, topics, contexts, ...
Topic, Line       decoded topic / line
HelpLibrary       several databases (a directory of .HLP files), link
                  resolution, F1 keyword lookup, HTML rendering
load_file(path)   -> list[HelpDatabase]

CLI
---
    python3 qbhelp.py DIR --list
    python3 qbhelp.py DIR --topic PRINT
    python3 qbhelp.py DIR --html PRINT out.html
    python3 qbhelp.py DIR --check          (decode everything, verify OUTLEN)
"""

from __future__ import annotations

import html as _html
import os
import re
import struct
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

__all__ = [
    "HelpFormatError", "Line", "Topic", "HelpDatabase", "HelpLibrary",
    "load_file", "decode_text", "DEFAULT_CSS",
    "STYLE_BOLD", "STYLE_ITALIC", "STYLE_UNDERLINE",
]

STYLE_BOLD = 1
STYLE_ITALIC = 2
STYLE_UNDERLINE = 4

LinkTarget = Union[str, int]


class HelpFormatError(Exception):
    """Raised for malformed database metadata (not for bad topics)."""


# ---------------------------------------------------------------------------
# Character set: CP437 with 0x00-0x1F and 0x7F shown as graphics
# ---------------------------------------------------------------------------

_LOW_GRAPHICS = (" ☺☻♥♦♣♠•◘○◙♂♀♪♫☼"
                 "►◄↕‼¶§▬↨↑↓→←∟↔▲▼")
_CP437_TABLE = [bytes([b]).decode("cp437") for b in range(256)]
for _i in range(32):
    _CP437_TABLE[_i] = _LOW_GRAPHICS[_i]
_CP437_TABLE[0x7F] = "⌂"
_CP437_MAP = str.maketrans({i: c for i, c in enumerate(_CP437_TABLE)})
del _i


def decode_text(raw: bytes) -> str:
    """Decode CP437 bytes, mapping 0-31 and 127 to their graphic glyphs.
    Every byte maps to exactly one character, so byte offsets equal string
    offsets (important for style and link ranges)."""
    return "".join(_CP437_TABLE[b] for b in raw)


def _latin(raw: bytes) -> str:
    """Decode a context string (ASCII in practice; latin-1 never fails)."""
    return raw.decode("latin-1")


# ---------------------------------------------------------------------------
# Huffman decoding (table driven: one step per input byte)
# ---------------------------------------------------------------------------

class _HuffmanTree:
    """Huffman tree in QuickHelp's serialized form.

    Node[i] < 0 (high bit set): leaf, symbol = low byte.
    Node[i] >= 0: internal; right child (bit 1) = i+1, left child (bit 0) =
    Node[i] // 2.  Root = Node[0].
    """

    def __init__(self, nodes: Sequence[int]):
        n = len(nodes)
        if n == 0 or n % 2 == 0:
            raise HelpFormatError("invalid Huffman tree (%d nodes)" % n)
        self.leaf = [-1] * n            # symbol for leaves, -1 for internal
        self.left = [0] * n
        self.right = [0] * n
        for i, v in enumerate(nodes):
            if v & 0x8000:
                self.leaf[i] = v & 0xFF
            else:
                c0, c1 = v // 2, i + 1
                if not (c1 < c0 < n):
                    raise HelpFormatError("invalid Huffman tree child link")
                self.left[i], self.right[i] = c0, c1
        if self.leaf[0] >= 0:
            raise HelpFormatError("degenerate Huffman tree")
        self._table: Optional[List[Optional[Tuple[bytes, int]]]] = None

    def _build_table(self):
        # For each internal node and each input byte: (emitted bytes, end node)
        leaf, left, right = self.leaf, self.left, self.right
        n = len(leaf)
        table: List[Optional[List[Tuple[bytes, int]]]] = [None] * n
        for start in range(n):
            if leaf[start] >= 0:
                continue
            row = []
            for byte in range(256):
                node = start
                out = bytearray()
                for bit in range(7, -1, -1):
                    node = right[node] if (byte >> bit) & 1 else left[node]
                    s = leaf[node]
                    if s >= 0:
                        out.append(s)
                        node = 0
                row.append((bytes(out), node))
            table[start] = row
        self._table = table

    def decode(self, data: bytes, max_out: int) -> bytes:
        """Decode the bit stream (MSB first).  Stops after max_out symbols
        or at the end of data; trailing padding bits are ignored."""
        if self._table is None:
            self._build_table()
        table = self._table
        out = bytearray()
        node = 0
        for b in data:
            emitted, node = table[node][b]
            out += emitted
            if len(out) >= max_out:
                break
        return bytes(out)


# ---------------------------------------------------------------------------
# Keyword / run-length expansion
# ---------------------------------------------------------------------------

def _expand(data: bytes, outlen: int, keywords: Sequence[bytes]) -> bytes:
    """Expand the compact stream (step 2) until outlen bytes are produced.
    Bad dictionary indexes or truncated arguments end decoding early; the
    caller compares the result length with outlen."""
    out = bytearray()
    i, n = 0, len(data)
    nkw = len(keywords)
    while i < n and len(out) < outlen:
        b = data[i]
        i += 1
        if b < 0x10 or b > 0x1A:
            out.append(b)
        elif b == 0x1A:                       # escape
            if i >= n:
                break
            out.append(data[i]); i += 1
        elif b == 0x19:                       # repeat byte
            if i + 1 >= n:
                break
            out += bytes([data[i]]) * data[i + 1]; i += 2
        elif b == 0x18:                       # run of spaces
            if i >= n:
                break
            out += b" " * data[i]; i += 1
        else:                                 # 0x10-0x17 dictionary entry
            if i >= n:
                break
            idx = ((b & 3) << 8) | data[i]; i += 1
            if idx >= nkw:
                raise HelpFormatError("keyword index %d out of range (%d)"
                                      % (idx, nkw))
            out += keywords[idx]
            if b & 4:
                out.append(0x20)
    return bytes(out[:outlen])


# ---------------------------------------------------------------------------
# Lines and topics
# ---------------------------------------------------------------------------

class Line:
    """A visible line of a topic.

    text    unicode string (CP437, low bytes mapped to graphics)
    raw     the original bytes of the text
    styles  list of (start, end, stylebits), end exclusive, 0-based,
            only runs with stylebits != 0 (bold=1, italic=2, underline=4)
    links   list of (start, end, target), end exclusive, 0-based;
            target is a context string (str) or a topic index (int) in the
            same database
    """

    __slots__ = ("text", "raw", "styles", "links")

    def __init__(self, text: str, raw: bytes = b"",
                 styles: Optional[List[Tuple[int, int, int]]] = None,
                 links: Optional[List[Tuple[int, int, LinkTarget]]] = None):
        self.text = text
        self.raw = raw
        self.styles = styles if styles is not None else []
        self.links = links if links is not None else []

    def style_at(self, pos: int) -> int:
        for s, e, st in self.styles:
            if s <= pos < e:
                return st
        return 0

    def link_at(self, pos: int) -> Optional[LinkTarget]:
        for s, e, t in self.links:
            if s <= pos < e:
                return t
        return None

    def __repr__(self):
        return "Line(%r, styles=%r, links=%r)" % (self.text, self.styles,
                                                 self.links)


class Topic:
    """A decoded topic.

    index        topic number in its database
    lines        visible lines (list of Line)
    contexts     context strings that resolve to this topic
    title        from :n (None if absent)
    length       :l window height (int or None)
    freeze       :z number of frozen lines at the top (int or None)
    hidden       :x  (topic is a command topic, not normally shown)
    is_list      :i
    is_popup     :g
    is_raw       :u
    category     :c
    next, prev   :> / :<  context strings
    execute      list of :y parameters
    refs         list of :r context strings
    marks        list of (name, line, column) from :m
    pastes       list of (name, start_line, end_line) from :p ... :e
    commands     every command in order: (line_number_in_visible_lines,
                 command_char, parameter)
    outlen       stored decompressed length
    decoded_len  bytes actually produced by decompression
    error        None, or a message describing a decoding problem
    """

    def __init__(self, index: int):
        self.index = index
        self.lines: List[Line] = []
        self.contexts: List[str] = []
        self.title: Optional[str] = None
        self.length: Optional[int] = None
        self.freeze: Optional[int] = None
        self.hidden = False
        self.is_list = False
        self.is_popup = False
        self.is_raw = False
        self.category: Optional[str] = None
        self.next: Optional[str] = None
        self.prev: Optional[str] = None
        self.execute: List[str] = []
        self.refs: List[str] = []
        self.marks: List[Tuple[str, int, int]] = []
        self.pastes: List[Tuple[str, int, int]] = []
        self.commands: List[Tuple[int, str, str]] = []
        self.outlen = 0
        self.decoded_len = 0
        self.error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.decoded_len == self.outlen

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    def iter_links(self):
        """Yield (line_no, start, end, target) for every link."""
        for no, line in enumerate(self.lines):
            for s, e, t in line.links:
                yield no, s, e, t

    def __repr__(self):
        return "<Topic %d %r, %d lines>" % (self.index, self.title,
                                            len(self.lines))


def _parse_line(buf: bytes, pos: int) -> Tuple[bytes, List[Tuple[int, int, int]],
                                               List[Tuple[int, int, LinkTarget]],
                                               int]:
    """Parse one line at buf[pos].  Returns (raw_text, styles, links, newpos).
    Raises HelpFormatError on structural errors."""
    n = len(buf)
    tlen = buf[pos]
    if tlen == 0:
        raise HelpFormatError("zero text block length")
    tend = pos + tlen
    if tend > n:
        raise HelpFormatError("text block runs past topic end")
    raw = buf[pos + 1:tend]
    if tend >= n:
        raise HelpFormatError("missing attribute block")
    alen = buf[tend]
    if alen == 0:
        raise HelpFormatError("zero attribute block length")
    aend = tend + alen
    if aend > n:
        raise HelpFormatError("attribute block runs past topic end")
    attr = buf[tend + 1:aend]
    width = len(raw)

    # --- styles: ChunkLen0 [Style ChunkLen]... [0xFF links]
    styles: List[Tuple[int, int, int]] = []
    i, na = 0, len(attr)
    col = 0
    style = 0
    first = True
    while i < na:
        if not first:
            a = attr[i]
            i += 1
            if a == 0xFF:
                break
            style = a & 7
            if i >= na:
                break
        first = False
        cnt = attr[i]
        i += 1
        cnt = max(0, min(cnt, width - col))
        if style and cnt:
            if styles and styles[-1][2] == style and styles[-1][1] == col:
                styles[-1] = (styles[-1][0], col + cnt, style)
            else:
                styles.append((col, col + cnt, style))
        col += cnt
    else:
        i = na  # no link section

    # --- links: start(1-based) end(1-based incl.) ctx\0 [WORD topic]
    links: List[Tuple[int, int, LinkTarget]] = []
    while i + 2 <= na:
        s, e = attr[i], attr[i + 1]
        i += 2
        z = attr.find(b"\0", i)
        if z < 0:
            raise HelpFormatError("unterminated link context string")
        ctx = attr[i:z]
        i = z + 1
        if ctx:
            target: LinkTarget = _latin(ctx)
        else:
            if i + 2 > na:
                raise HelpFormatError("truncated link topic index")
            num = attr[i] | (attr[i + 1] << 8)
            i += 2
            target = num & 0x7FFF if num & 0x8000 else "@L%04X" % num
        if s == 0 or s > e:
            continue  # invalid range, skip
        e = min(e, width)
        if s - 1 < e:
            links.append((s - 1, e, target))
    return raw, styles, links, aend


# Colon-command letters stored by HELPMAKE.  A line that starts with the
# control character followed by anything else is ordinary text (QB45ADVR
# topic 451 has the BASIC code line ": PRINT").
COMMAND_CHARS = frozenset("nlzxigucy<>rmpe")


def _decompile_topic(topic: Topic, buf: bytes, ctrl: int):
    """Split binary topic text into lines and process colon commands."""
    pos, n = 0, len(buf)
    open_paste: Optional[Tuple[str, int]] = None
    while pos < n:
        try:
            raw, styles, links, pos = _parse_line(buf, pos)
        except (HelpFormatError, IndexError) as exc:
            topic.error = "line %d: %s" % (len(topic.lines), exc)
            topic.lines.append(Line("[decode error: %s]" % exc))
            break
        if (raw[:1] == bytes([ctrl]) and len(raw) >= 2
                and chr(raw[1]) in COMMAND_CHARS):
            cmd = chr(raw[1])
            param = decode_text(raw[2:])
            lineno = len(topic.lines)
            topic.commands.append((lineno, cmd, param))
            p = param.strip()
            if cmd == "n":
                topic.title = param.strip()
            elif cmd == "l":
                topic.length = _int_or_none(p)
            elif cmd == "z":
                topic.freeze = _int_or_none(p)
            elif cmd == "x":
                topic.hidden = True
            elif cmd == "i":
                topic.is_list = True
            elif cmd == "g":
                topic.is_popup = True
            elif cmd == "u":
                topic.is_raw = True
            elif cmd == "c":
                topic.category = p
            elif cmd == ">":
                topic.next = p
            elif cmd == "<":
                topic.prev = p
            elif cmd == "y":
                topic.execute.append(p)
            elif cmd == "r":
                topic.refs.extend(x.strip() for x in p.split(",") if x.strip())
            elif cmd == "m":
                parts = p.split()
                col = _int_or_none(parts[1]) if len(parts) > 1 else 0
                topic.marks.append((parts[0] if parts else "", lineno,
                                    col or 0))
            elif cmd == "p":
                if open_paste:
                    topic.pastes.append((open_paste[0], open_paste[1], lineno))
                open_paste = (p, lineno)
            elif cmd == "e":
                if open_paste:
                    topic.pastes.append((open_paste[0], open_paste[1], lineno))
                    open_paste = None
            continue
        topic.lines.append(Line(decode_text(raw), raw, styles, links))
    if open_paste:
        topic.pastes.append((open_paste[0], open_paste[1], len(topic.lines)))


def _int_or_none(s: str) -> Optional[int]:
    m = re.match(r"\s*(-?\d+)", s)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

_HEADER = struct.Struct("<2sHHBBHHHH14sIIIIIIIIII")
assert _HEADER.size == 0x46


class HelpDatabase:
    """One QuickHelp help database.

    name              database name from the header (e.g. "qb45advr.hlp")
    topics            list of Topic (decoded eagerly; a bad topic gets an
                      error line instead of raising)
    contexts          dict context string -> topic index
    case_sensitive    header attribute bit 0
    control_char      the colon-command lead byte (usually ':')
    display_width     width of the help viewer
    keywords          keyword-compression dictionary (list of bytes)
    source            path the database was read from (or None)
    offset            byte offset of the database in its file
    size              DatabaseSize
    truncated         True if the file ends before DatabaseSize
    """

    def __init__(self, data: Union[bytes, str, os.PathLike], offset: int = 0,
                 source: Optional[str] = None, lazy: bool = False):
        """data: the whole file's bytes (or a path); offset: where this
        database starts.  Use load_file() to get every database of a file."""
        if isinstance(data, (str, os.PathLike)):
            source = source or os.fspath(data)
            with open(data, "rb") as f:
                data = f.read()
        data = bytes(data)
        self.source = source
        self.offset = offset
        if len(data) - offset < _HEADER.size:
            raise HelpFormatError("truncated header")
        (sig, version, attrs, ctrl, _pad1, ntopics, nctx, width,
         npredef, rawname, _res1, o_index, o_ctx, o_map, o_kw, o_huff,
         o_text, _res2, _res3, dbsize) = _HEADER.unpack_from(data, offset)
        if sig != b"LN":
            raise HelpFormatError("bad signature %r at offset %d"
                                  % (sig, offset))
        self.version = version
        self.attributes = attrs
        self.case_sensitive = bool(attrs & 1)
        self.locked = bool(attrs & 2)
        self.control_byte = ctrl
        self.control_char = _CP437_TABLE[ctrl]
        self.display_width = width & 0xFF
        self.predefined_count = npredef
        self.name = _latin(rawname.split(b"\0", 1)[0])
        if dbsize < _HEADER.size:
            raise HelpFormatError("bad database size %d" % dbsize)
        self.size = dbsize                     # declared size
        # A truncated file is tolerated: topics past the end of the data
        # become error topics.
        self.truncated = offset + dbsize > len(data)
        db = data[offset:offset + dbsize]
        self._raw = db
        avail = len(db)

        def chk(o, what):
            if not (0 < o <= avail):
                raise HelpFormatError("bad %s offset %d" % (what, o))

        for o, w in ((o_index, "topic index"), (o_ctx, "context strings"),
                     (o_map, "context map"), (o_text, "topic text")):
            chk(o, w)

        # Topic index
        if o_index + 4 * (ntopics + 1) > avail:
            raise HelpFormatError("topic index runs past database end")
        self._topic_offsets = list(struct.unpack_from(
            "<%dI" % (ntopics + 1), db, o_index))

        # Context strings + map
        names: List[str] = []
        p = o_ctx
        for _ in range(nctx):
            z = db.find(b"\0", p, o_map)
            if z < 0:
                raise HelpFormatError("context strings section truncated")
            names.append(_latin(db[p:z]))
            p = z + 1
        if o_map + 2 * nctx > avail:
            raise HelpFormatError("context map runs past database end")
        cmap = struct.unpack_from("<%dH" % nctx, db, o_map)
        self.contexts: Dict[str, int] = {}
        self.context_list: List[Tuple[str, int]] = []
        for nm, ti in zip(names, cmap):
            self.context_list.append((nm, ti))
            if ti < ntopics:
                self.contexts.setdefault(nm, ti)
        self._ctx_fold: Dict[str, int] = {}
        for nm, ti in self.contexts.items():
            self._ctx_fold.setdefault(nm.lower(), ti)

        # Keywords
        self.keywords: List[bytes] = []
        if o_kw:
            chk(o_kw, "keywords")
            kend = o_huff if o_huff else o_text
            p = o_kw
            while p < min(kend, avail):
                ln = db[p]
                self.keywords.append(db[p + 1:p + 1 + ln])
                p += 1 + ln

        # Huffman tree
        self._huffman: Optional[_HuffmanTree] = None
        if o_huff:
            chk(o_huff, "huffman tree")
            nodes = []
            p = o_huff
            while True:
                if p + 2 > o_text:
                    raise HelpFormatError("huffman tree not terminated")
                v = db[p] | (db[p + 1] << 8)
                p += 2
                if v == 0:
                    break
                nodes.append(v)
            self._huffman = _HuffmanTree(nodes)

        # Topics
        self._topics: List[Optional[Topic]] = [None] * ntopics
        ctx_by_topic: Dict[int, List[str]] = {}
        for nm, ti in self.context_list:
            ctx_by_topic.setdefault(ti, []).append(nm)
        self._ctx_by_topic = ctx_by_topic
        if not lazy:
            for i in range(ntopics):
                self.topic(i)

    # -- topics -------------------------------------------------------------

    @property
    def topic_count(self) -> int:
        return len(self._topics)

    @property
    def topics(self) -> List[Topic]:
        """All topics (decodes any not yet decoded)."""
        return [self.topic(i) for i in range(len(self._topics))]

    def topic(self, index: int) -> Topic:
        """Return topic `index`, decoding it on first use.  Never raises for
        a bad topic: an error topic with an explanatory line is returned.
        Raises IndexError only for an index outside the database."""
        if not 0 <= index < len(self._topics):
            raise IndexError("topic index %d out of range" % index)
        t = self._topics[index]
        if t is None:
            t = self._decode_topic(index)
            self._topics[index] = t
        return t

    def _decode_topic(self, index: int) -> Topic:
        topic = Topic(index)
        topic.contexts = list(self._ctx_by_topic.get(index, []))
        try:
            a, b = self._topic_offsets[index], self._topic_offsets[index + 1]
            if not (0 < a <= b <= self.size):
                raise HelpFormatError("bad topic offsets %d..%d" % (a, b))
            if b > len(self._raw):
                raise HelpFormatError("topic data missing (file truncated)")
            blob = self._raw[a:b]
            if len(blob) < 2:
                raise HelpFormatError("topic too short")
            outlen = blob[0] | (blob[1] << 8)
            topic.outlen = outlen
            payload = blob[2:]
            if self._huffman is not None:
                # An escaped byte (0x1A xx) takes two compact symbols for one
                # output byte, so up to 2*OUTLEN symbols may be needed; the
                # padding bits after the stream are ignored by _expand.
                compact = self._huffman.decode(payload, 2 * outlen + 8)
            else:
                compact = payload
            binary = _expand(compact, outlen, self.keywords)
            topic.decoded_len = len(binary)
            if len(binary) != outlen:
                topic.error = ("decompressed %d bytes, expected %d"
                               % (len(binary), outlen))
            _decompile_topic(topic, binary, self.control_byte)
        except Exception as exc:  # noqa: BLE001 - must never crash
            topic.error = "%s: %s" % (type(exc).__name__, exc)
            topic.lines.append(Line("[error decoding topic %d: %s]"
                                    % (index, topic.error)))
        return topic

    # -- contexts -----------------------------------------------------------

    def resolve_context(self, ctx: str) -> Optional[int]:
        """Topic index for a context string in this database, or None."""
        if ctx in self.contexts:
            return self.contexts[ctx]
        if not self.case_sensitive:
            return self._ctx_fold.get(ctx.lower())
        return None

    def contexts_of(self, index: int) -> List[str]:
        return list(self._ctx_by_topic.get(index, []))

    def __repr__(self):
        return "<HelpDatabase %r: %d topics, %d contexts>" % (
            self.name, len(self._topics), len(self.contexts))


def _iter_databases(data: bytes, source: Optional[str] = None,
                    lazy: bool = False) -> Iterable[HelpDatabase]:
    off = 0
    while off + _HEADER.size <= len(data):
        if data[off:off + 2] != b"LN":
            break
        db = HelpDatabase(data, off, source, lazy=lazy)
        yield db
        off += db.size


def load_file(path_or_bytes: Union[str, bytes, os.PathLike],
              lazy: bool = False) -> List[HelpDatabase]:
    """Load all databases contained in a .HLP file (path or bytes)."""
    if isinstance(path_or_bytes, (bytes, bytearray, memoryview)):
        return list(_iter_databases(bytes(path_or_bytes), None, lazy))
    path = os.fspath(path_or_bytes)
    with open(path, "rb") as f:
        data = f.read()
    return list(_iter_databases(data, path, lazy))


HelpDatabase.load_all = staticmethod(load_file)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# HTML styling
# ---------------------------------------------------------------------------

# Style bits -> CSS.  QuickHelp's native palette (on black) is:
#  0 white, 1 bright white, 2 green, 3 cyan, 4 red, 5 bright white on cyan,
#  6 white, 7 black.  Below is a light, neutral equivalent.
DEFAULT_CSS: Dict[Union[int, str], str] = {
    0: "",
    1: "font-weight:bold;",
    2: "color:#11730b;",
    3: "color:#00707a;font-weight:bold;",
    4: "color:#b00020;",
    5: "font-weight:bold;background-color:#cdeef2;",
    6: "text-decoration:underline;",
    7: "background-color:#d0d0d0;",
    "pre": "font-family:'Courier New','DejaVu Sans Mono',monospace;"
           "font-size:11pt;color:#1a1a1a;margin:0;",
    "body": "background-color:#fbfbf8;",
    "link": "color:#0645ad;text-decoration:none;",
    "broken": "color:#888888;",
    "title": "font-weight:bold;",
}

# Native DOS palette, for an IDE that wants the original look.
DOS_CSS: Dict[Union[int, str], str] = {
    0: "",
    1: "color:#ffffff;font-weight:bold;",
    2: "color:#00aa00;",
    3: "color:#00aaaa;",
    4: "color:#aa0000;",
    5: "color:#ffffff;background-color:#00aaaa;",
    6: "",
    7: "color:#000000;",
    "pre": "font-family:'Courier New',monospace;font-size:11pt;"
           "color:#aaaaaa;background-color:#000000;margin:0;",
    "body": "background-color:#000000;",
    "link": "color:#ffff55;text-decoration:none;",
    "broken": "color:#777777;",
    "title": "font-weight:bold;",
}


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

class HelpLibrary:
    """A set of help databases with cross-database link resolution.

    Link targets understood by resolve():
        int                 topic index in the referring database
        "@L8xxx"            (hex) topic index in the referring database
        "db!context"        context in database db ("qb45advr.hlp!PRINT")
        "db!"               topic 0 of database db
        "!command"          a command (not resolvable, returns None)
        "@context"          local context
        "context"           referring database first, then all databases
    """

    HREF_SCHEME = "qbhelp:"

    def __init__(self, paths: Iterable[Union[str, os.PathLike]] = (),
                 css: Optional[Dict[Union[int, str], str]] = None,
                 lazy: bool = False, lenient: bool = True):
        self.databases: List[HelpDatabase] = []
        self.lenient = lenient
        self.errors: List[Tuple[str, str]] = []
        self.css = dict(DEFAULT_CSS)
        if css:
            self.css.update(css)
        self.lazy = lazy
        for p in paths:
            self.add_file(p)

    # -- loading ------------------------------------------------------------

    @classmethod
    def from_directory(cls, directory: Union[str, os.PathLike], **kw):
        lib = cls(**kw)
        lib.add_directory(directory)
        return lib

    def add_directory(self, directory: Union[str, os.PathLike]) -> int:
        """Load every *.hlp file (case-insensitive) in directory.
        Returns the number of databases added."""
        directory = os.fspath(directory)
        n = 0
        for fn in sorted(os.listdir(directory), key=str.lower):
            full = os.path.join(directory, fn)
            if fn.lower().endswith(".hlp") and os.path.isfile(full):
                n += self.add_file(full)
        return n

    def add_file(self, path: Union[str, os.PathLike]) -> int:
        path = os.fspath(path)
        try:
            dbs = load_file(path, lazy=self.lazy)
        except (OSError, HelpFormatError, struct.error) as exc:
            self.errors.append((path, str(exc)))
            return 0
        self.databases.extend(dbs)
        return len(dbs)

    def add_database(self, db: HelpDatabase):
        self.databases.append(db)

    # -- lookup -------------------------------------------------------------

    def database(self, name: Union[str, HelpDatabase, int]) -> Optional[HelpDatabase]:
        """Find a database by name (case-insensitive; with or without the
        .hlp extension; also matches the file name it was loaded from)."""
        if isinstance(name, HelpDatabase):
            return name
        if isinstance(name, int):
            return self.databases[name] if 0 <= name < len(self.databases) else None
        key = name.lower()
        for db in self.databases:
            if db.name.lower() == key:
                return db
        stem = key[:-4] if key.endswith(".hlp") else key
        for db in self.databases:
            dn = db.name.lower()
            if (dn[:-4] if dn.endswith(".hlp") else dn) == stem:
                return db
        for db in self.databases:
            if db.source and os.path.basename(db.source).lower() in (key, stem + ".hlp"):
                return db
        return None

    def resolve(self, target: LinkTarget,
                referrer: Union[HelpDatabase, str, None] = None,
                lenient: Optional[bool] = None
                ) -> Optional[Tuple[HelpDatabase, int]]:
        """Resolve a link target to (database, topic_index) or None.
        lenient (default: self.lenient) enables recovery of malformed
        external targets."""
        if lenient is None:
            lenient = self.lenient
        ref = self.database(referrer) if referrer is not None else None
        if isinstance(target, int):
            if ref is not None and 0 <= target < ref.topic_count:
                return ref, target
            return None
        if not target:
            return None
        if target.startswith("@L") and len(target) == 6:
            try:
                num = int(target[2:], 16)
            except ValueError:
                num = -1
            if num >= 0 and num & 0x8000:
                return self.resolve(num & 0x7FFF, ref, lenient)
        if target.startswith("!"):
            return None                         # command link
        if "!" in target:
            dbname, ctx = target.split("!", 1)
            db = self.database(dbname)
            if db is not None:
                if not ctx:
                    return (db, 0) if db.topic_count else None
                ti = db.resolve_context(ctx)
                if ti is not None:
                    return db, ti
            if not lenient or not ctx:
                return None
            # Lenient recovery for broken targets found in the QB 4.5
            # files ("ab45advr.hlp!.erasex", "qb45advr.hlp!qb45advr.hlp!.vupri"):
            # use the last '!'-separated part, preferring the named database.
            ctx = ctx.rsplit("!", 1)[-1]
            if db is not None:
                ti = db.resolve_context(ctx)
                if ti is not None:
                    return db, ti
            for d in self.databases:
                ti = d.resolve_context(ctx)
                if ti is not None:
                    return d, ti
            return None
        if target.startswith("@") and ref is not None:
            ti = ref.resolve_context(target)
            if ti is None:
                ti = ref.resolve_context(target[1:])
            return (ref, ti) if ti is not None else None
        if ref is not None:
            ti = ref.resolve_context(target)
            if ti is not None:
                return ref, ti
        for db in self.databases:
            ti = db.resolve_context(target)
            if ti is not None:
                return db, ti
        return None

    def topic(self, db: Union[HelpDatabase, str, int], index: int) -> Optional[Topic]:
        d = self.database(db)
        if d is None or not 0 <= index < d.topic_count:
            return None
        return d.topic(index)

    # -- keyword (F1) lookup -------------------------------------------------
    #
    # QB45QCK.HLP has one context per *single* keyword ("PRINT", "LINE",
    # "CHR$", "SEG" ...), each pointing at a "... QuickSCREEN" topic.
    # Multi-word statements ("LINE INPUT", "ON ERROR", "PRINT USING",
    # "VIEW PRINT") and function/statement twins ("SCREEN Function") only
    # have internal contexts in QB45ADVR.HLP (".linput", ".zpu", ".screenf").
    # So a phrase index is derived from the QuickSCREEN topic titles.

    _KINDS = ("statement", "function", "metacommand", "operator", "keyword")
    _TITLE_RE = re.compile(
        r"^(?P<names>.+?)\s+(?P<kind>Statements?|Functions?|Metacommands?|"
        r"Operators?|Keywords?)\s+QuickSCREEN\s*$", re.I)

    @staticmethod
    def norm_keyword(word: str) -> str:
        """Upper-case, collapse blanks, and separate '#' ("LINE INPUT#" ->
        "LINE INPUT #")."""
        w = word.replace("\t", " ").upper()
        w = re.sub(r"(?<=[A-Z0-9$])#", " #", w)
        return " ".join(w.split())

    def _build_phrases(self):
        idx: Dict[str, List[Tuple[HelpDatabase, int, str]]] = {}
        for db in self.databases:
            for t in db.topics:
                m = self._TITLE_RE.match(t.title or "")
                if not m:
                    continue
                kind = m.group("kind").lower().rstrip("s")
                names = re.sub(r"\([^)]*\)", " ", m.group("names"))
                for part in re.split(r",\s*(?:and\s+|or\s+)?|\s+and\s+|"
                                     r"\s+or\s+", names):
                    for piece in part.split("..."):
                        key = self.norm_keyword(piece)
                        if key and not key.islower():
                            idx.setdefault(key, [])
                            if (db, t.index, kind) not in idx[key]:
                                idx[key].append((db, t.index, kind))
        self._phrases = idx
        self._phrase_gen = len(self.databases)

    @property
    def phrases(self) -> Dict[str, List[Tuple[HelpDatabase, int, str]]]:
        """Keyword phrase -> [(db, topic_index, kind)] from QuickSCREEN
        titles; kind is 'statement', 'function', 'metacommand', ..."""
        if getattr(self, "_phrase_gen", -1) != len(self.databases):
            self._build_phrases()
        return self._phrases

    def find_keyword(self, word: str, kind: Optional[str] = None
                     ) -> Optional[Tuple[HelpDatabase, int]]:
        """QB-style F1 lookup for a keyword or keyword phrase.

        kind: optional hint 'statement' or 'function' (e.g. the IDE passes
        'function' when the word is followed by '(' in an expression), used
        for twins such as SCREEN, PLAY, MID$, SEEK, DATE$.

        Order: phrase index filtered by kind; context string (what QB
        itself does: "PRINT" -> QB45QCK "PRINT Statement QuickSCREEN");
        phrase index; type-suffix variants (LEFT -> LEFT$); title prefix
        ("SCREEN Statement")."""
        w = self.norm_keyword(word)
        if not w:
            return None
        if w in ("CONTENTS", "INDEX") and not kind:
            r = self.special(w.lower())
            if r is not None:
                return r
        m = re.match(r"^(.+?)\s+(STATEMENT|FUNCTION|METACOMMAND|OPERATOR|"
                     r"KEYWORD)S?$", w)
        if m and not kind:
            r = self.find_keyword(m.group(1), m.group(2).lower())
            if r is not None:
                return r
        ph = self.phrases
        if kind:
            for db, ti, k in ph.get(w, []):
                if k == kind.lower():
                    return db, ti
        r = self.resolve(w) if " " not in w else None
        if r is not None:
            return r
        if w in ph:
            return ph[w][0][0], ph[w][0][1]
        r = self.resolve(word.strip())         # internal/odd context strings
        if r is not None:
            return r
        variants = []
        if w[-1] in "$%&!#":
            variants.append(w[:-1].rstrip())
        else:
            variants.append(w + "$")
        for v in variants:
            r = self.resolve(v) if " " not in v else None
            if r is None and v in ph:
                r = ph[v][0][0], ph[v][0][1]
            if r is not None:
                return r
        lw = " ".join(word.lower().split())
        for db in self.databases:
            for t in db.topics:
                if t.title and t.title.lower().startswith(lw):
                    return db, t.index
        if " " in w:                            # "LPRINT USING" -> LPRINT
            return self.find_keyword(w.split(" ", 1)[0], kind)
        return None

    _TOKEN_RE = re.compile(r"\$?[A-Za-z][A-Za-z0-9_.]*[$%&!#]?|#")

    def lookup_at(self, line: str, col: int, kind: Optional[str] = None
                  ) -> Optional[Tuple[str, HelpDatabase, int]]:
        """F1 at a cursor position in a source line: finds the longest
        keyword phrase (up to 3 words) covering column col (0-based), e.g.
        the cursor on INPUT in 'LINE INPUT #1, a$' -> 'LINE INPUT #'.
        If kind is None and the word is directly followed by '(', the
        function variant is preferred.  Returns (phrase, db, index)."""
        toks = [(m.start(), m.end(), m.group())
                for m in self._TOKEN_RE.finditer(line)]
        k = next((i for i, (a, b, _) in enumerate(toks) if a <= col < b or
                  (b == col and i == len(toks) - 1)), None)
        if k is None:
            return None
        if kind is None:
            rest = line[toks[k][1]:].lstrip()
            kind = "function" if rest.startswith("(") else None
        ph = self.phrases
        for size in (3, 2):
            for lo in range(k - size + 1, k + 1):
                hi = lo + size
                if lo < 0 or hi > len(toks):
                    continue
                phrase = self.norm_keyword(" ".join(t[2] for t in toks[lo:hi]))
                if phrase in ph:
                    r = self.find_keyword(phrase, kind)
                    if r:
                        return (phrase,) + r
        word = toks[k][2]
        r = self.find_keyword(word, kind)
        return (self.norm_keyword(word),) + r if r else None

    _KW_RE = re.compile(r"^\$?[A-Z][A-Z0-9]*[$%&!#]?$")

    def keywords(self) -> List[Tuple[str, HelpDatabase, int]]:
        """Keyword index: every upper-case single-word context string
        ("ABS", "CHR$", "LINE") plus every phrase from the QuickSCREEN
        titles ("LINE INPUT #", "ON ERROR", "SCREEN"), sorted.  Internal
        contexts (".linput", "-9996", "h.contents") are excluded.
        Returns (keyword, database, topic_index)."""
        out: Dict[str, Tuple[str, HelpDatabase, int]] = {}
        for db in self.databases:
            for ctx, ti in db.context_list:
                if ti < db.topic_count and self._KW_RE.match(ctx):
                    out.setdefault(ctx.upper(), (ctx, db, ti))
        for key, hits in self.phrases.items():
            if key not in out:
                out[key] = (key, hits[0][0], hits[0][1])
        return [out[k] for k in sorted(out, key=lambda x: x.lstrip("$"))]

    # Standard QuickHelp context names
    def special(self, name: str) -> Optional[Tuple[HelpDatabase, int]]:
        """Resolve a standard topic: 'contents', 'index', 'default',
        'notfound', 'pg1' (= h.<name> in any database)."""
        return self.resolve("h." + name)

    def error_help(self, code: int) -> Optional[Tuple[HelpDatabase, int]]:
        """Help for a BASIC run-time error number (QB45ENER.HLP stores them
        as contexts "-<2000+n>" and "-<n>", e.g. error 9 -> "-2009"/"-9")."""
        return self.resolve("-%d" % (2000 + code)) or self.resolve("-%d" % code)

    def contents(self) -> Optional[Tuple[HelpDatabase, int]]:
        return self.special("contents")

    def index(self) -> Optional[Tuple[HelpDatabase, int]]:
        return self.special("index")

    def search_titles(self, text: str) -> List[Tuple[HelpDatabase, int, str]]:
        """Topics whose :n title contains text (case-insensitive)."""
        t = text.lower()
        res = []
        for db in self.databases:
            for tp in db.topics:
                if tp.title and t in tp.title.lower():
                    res.append((db, tp.index, tp.title))
        return res

    # -- hrefs --------------------------------------------------------------

    def href(self, db: HelpDatabase, index: int) -> str:
        return "%s%s/%d" % (self.HREF_SCHEME, db.name, index)

    def parse_href(self, href: str) -> Optional[Tuple[HelpDatabase, int]]:
        """Inverse of href(): 'qbhelp:DBNAME/INDEX' -> (db, index)."""
        if not href.startswith(self.HREF_SCHEME):
            return None
        rest = href[len(self.HREF_SCHEME):].lstrip("/")
        if "/" not in rest:
            return None
        name, _, idx = rest.rpartition("/")
        db = self.database(name)
        try:
            i = int(idx)
        except ValueError:
            return None
        if db is None or not 0 <= i < db.topic_count:
            return None
        return db, i

    # -- rendering ----------------------------------------------------------

    def topic_text(self, db: Union[HelpDatabase, str], index: int) -> str:
        t = self.topic(db, index)
        return t.text if t else ""

    def topic_html(self, db: Union[HelpDatabase, str, int], index: int,
                   css: Optional[Dict[Union[int, str], str]] = None,
                   full_document: bool = True,
                   include_arrow: bool = True) -> str:
        """Render a topic as HTML suitable for QTextBrowser.

        Styles become <span style=...> using the CSS dict (keys 0-7 for the
        style bits, plus 'pre', 'body', 'link', 'broken').  Links become
        <a href="qbhelp:DBNAME/TOPICINDEX">; unresolved links become
        <a href="qbhelp-unresolved:TARGET"> with the 'broken' style.

        include_arrow: QB 4.5 link ranges start *after* the opening '◄'
        and include the closing '►'; when True the anchor is widened to
        cover the '◄' as well (display only; Line.links is unchanged)."""
        c = dict(self.css)
        if css:
            c.update(css)
        d = self.database(db)
        if d is None:
            return "<pre>[unknown database %s]</pre>" % _html.escape(str(db))
        if not 0 <= index < d.topic_count:
            return "<pre>[topic %d out of range in %s]</pre>" % (
                index, _html.escape(d.name))
        topic = d.topic(index)
        body = []
        for line in topic.lines:
            body.append(self._line_html(d, line, c, include_arrow))
        pre = '<pre style="%s">%s</pre>' % (c.get("pre", ""),
                                             "\n".join(body))
        if not full_document:
            return pre
        title = topic.title or (topic.contexts[0] if topic.contexts else
                                "Topic %d" % index)
        return ('<html><head><meta charset="utf-8"><title>%s</title></head>'
                '<body style="%s">%s</body></html>'
                % (_html.escape(title), c.get("body", ""), pre))

    def _line_html(self, db: HelpDatabase, line: Line,
                   c: Dict[Union[int, str], str],
                   include_arrow: bool = True) -> str:
        text = line.text
        n = len(text)
        if n == 0:
            return ""
        links = line.links
        if include_arrow and links:
            taken = set()
            for s, e, _ in links:
                taken.update(range(s, e))
            links = [(s - 1 if s > 0 and text[s - 1] == "◄"
                      and (s - 1) not in taken else s, e, t)
                     for s, e, t in links]
        # boundaries
        cuts = {0, n}
        for s, e, _ in line.styles:
            cuts.add(s); cuts.add(e)
        for s, e, _ in links:
            cuts.add(s); cuts.add(e)
        cuts = sorted(x for x in cuts if 0 <= x <= n)
        out = []
        cur_link = None
        for a, b in zip(cuts, cuts[1:]):
            if a >= b:
                continue
            link = None
            for s, e, t in links:
                if s <= a < e:
                    link = (s, e, t)
                    break
            if link != cur_link:
                if cur_link is not None:
                    out.append("</a>")
                if link is not None:
                    out.append(self._anchor_open(db, link[2], c))
                cur_link = link
            seg = _html.escape(text[a:b], quote=False)
            st = line.style_at(a)
            sty = c.get(st, "") if st else ""
            if sty:
                out.append('<span style="%s">%s</span>' % (sty, seg))
            else:
                out.append(seg)
        if cur_link is not None:
            out.append("</a>")
        return "".join(out)

    def _anchor_open(self, db: HelpDatabase, target: LinkTarget,
                     c: Dict[Union[int, str], str]) -> str:
        r = self.resolve(target, db)
        tt = _html.escape(str(target), quote=True)
        if r is None:
            return ('<a href="qbhelp-unresolved:%s" style="%s" title="%s">'
                    % (_html.escape(_url_quote(str(target)), quote=True),
                       c.get("broken", ""), tt))
        return '<a href="%s" style="%s" title="%s">' % (
            _html.escape(self.href(*r), quote=True), c.get("link", ""), tt)


def _url_quote(s: str) -> str:
    from urllib.parse import quote
    return quote(s, safe="!@$#%")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _describe_target(lib: HelpLibrary, db: HelpDatabase, t: LinkTarget) -> str:
    r = lib.resolve(t, db)
    if r is None:
        return "%r -> UNRESOLVED" % (t,)
    d, i = r
    tp = d.topic(i)
    return "%r -> %s/%d %s" % (t, d.name, i, tp.title or "")


def _cli(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Decode QuickHelp .HLP files "
                                 "(QB 4.5 help).")
    ap.add_argument("dir", help="directory with .HLP files, or one .HLP file")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true",
                   help="list databases with topic/context counts")
    g.add_argument("--topic", metavar="KEYWORD",
                   help="print plain text and links of a topic")
    g.add_argument("--html", nargs=2, metavar=("KEYWORD", "OUT"),
                   help="write topic as HTML")
    g.add_argument("--check", action="store_true",
                   help="decode all topics and verify OUTLEN and links")
    g.add_argument("--keywords", action="store_true",
                   help="list keyword-like contexts")
    ap.add_argument("--db", help="restrict --topic/--html lookup to a database")
    ap.add_argument("--kind", help="F1 hint: statement or function")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if os.path.isdir(args.dir):
        lib = HelpLibrary.from_directory(args.dir)
    else:
        lib = HelpLibrary([args.dir])
    for p, e in lib.errors:
        print("error: %s: %s" % (p, e), file=sys.stderr)

    if args.list:
        for db in lib.databases:
            bad = sum(1 for t in db.topics if not t.ok)
            print("%-16s %-28s topics=%5d contexts=%5d width=%d ctrl=%r "
                  "keywords=%d huffman=%s bad=%d"
                  % (db.name, os.path.basename(db.source or "?"),
                     db.topic_count, len(db.context_list), db.display_width,
                     db.control_char, len(db.keywords),
                     "yes" if db._huffman else "no", bad))
        return 0

    if args.keywords:
        for ctx, db, ti in lib.keywords():
            print("%-30s %s/%d" % (ctx, db.name, ti))
        return 0

    if args.check:
        total = bad = links = unresolved = repaired = 0
        for db in lib.databases:
            for t in db.topics:
                total += 1
                if not t.ok:
                    bad += 1
                    print("BAD %s/%d: %s (outlen=%d decoded=%d)"
                          % (db.name, t.index, t.error, t.outlen,
                             t.decoded_len))
                for _, _, _, tg in t.iter_links():
                    links += 1
                    r = lib.resolve(tg, db, lenient=True)
                    if r is None:
                        unresolved += 1
                        print("UNRESOLVED %s/%d %r" % (db.name, t.index, tg))
                    elif lib.resolve(tg, db, lenient=False) is None:
                        repaired += 1
                        print("REPAIRED   %s/%d %r -> %s/%d"
                              % (db.name, t.index, tg, r[0].name, r[1]))
        print("topics=%d bad=%d links=%d unresolved=%d repaired=%d"
              % (total, bad, links, unresolved, repaired))
        return 1 if bad else 0

    word = args.topic if args.topic else args.html[0]
    if args.db:
        d = lib.database(args.db)
        r = None
        if d is not None:
            ti = d.resolve_context(word)
            r = (d, ti) if ti is not None else None
    else:
        r = lib.find_keyword(word, args.kind)
    if r is None:
        hits = lib.search_titles(word)
        r = (hits[0][0], hits[0][1]) if hits else None
    if r is None:
        print("not found: %s" % word, file=sys.stderr)
        return 2
    db, ti = r
    topic = db.topic(ti)
    if args.topic:
        print("== %s/%d  title=%r  contexts=%s" % (db.name, ti, topic.title,
                                                   topic.contexts))
        print(topic.text)
        print("-- links:")
        for no, s, e, t in topic.iter_links():
            print("  line %3d [%2d:%2d] %-24r %s"
                  % (no, s, e, topic.lines[no].text[s:e],
                     _describe_target(lib, db, t)))
        return 0
    with open(args.html[1], "w", encoding="utf-8") as f:
        f.write(lib.topic_html(db, ti))
    print("wrote %s (%s/%d %s)" % (args.html[1], db.name, ti,
                                   topic.title or ""))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
