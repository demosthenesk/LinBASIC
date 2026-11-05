# LinBASIC compiler - lexer
# Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later.
import re

class QBError(Exception):
    def __init__(self, msg, line=0, col=0, file=None):
        super().__init__(msg)
        self.msg = msg
        self.line = line
        self.col = col
        self.file = file

    def __str__(self):
        return f"{self.file or ''}:{self.line}:{self.col}: {self.msg}"

KEYWORDS = set("""
ABS ACCESS ALIAS AND ANY APPEND AS ASC ATN BASE BEEP BINARY BLOAD BSAVE BYVAL CALL CALLS CASE CDBL CDECL
CHAIN CHDIR CHR$ CINT CIRCLE CLEAR CLNG CLOSE CLS COLOR COM COMMAND$ COMMON CONST COS CSNG CSRLIN CVD CVDMBF
CVI CVL CVS CVSMBF DATA DATE$ DECLARE DEF DEFDBL DEFINT DEFLNG DEFSNG DEFSTR DIM DO DOUBLE DRAW ELSE ELSEIF
END ENVIRON ENVIRON$ EOF EQV ERASE ERDEV ERDEV$ ERL ERR ERROR EXIT EXP FIELD FILEATTR FILES FIX FOR FRE
FREEFILE FUNCTION GET GOSUB GOTO HEX$ IF IMP INKEY$ INP INPUT INPUT$ INSTR INT INTEGER IOCTL IOCTL$ IS KEY
KILL LBOUND LCASE$ LEFT$ LEN LET LINE LIST LOC LOCAL LOCATE LOCK LOF LOG LONG LOOP LPOS LPRINT LSET LTRIM$
MID$ MKD$ MKDIR MKDMBF$ MKI$ MKL$ MKS$ MKSMBF$ MOD NAME NEXT NOT OCT$ OFF ON OPEN OPTION OR OUT OUTPUT
PAINT PALETTE PCOPY PEEK PEN PLAY PMAP POINT POKE POS PRESET PRINT PSET PUT RANDOM RANDOMIZE READ REDIM
REM RESET RESTORE RESUME RETURN RIGHT$ RMDIR RND RSET RTRIM$ RUN SADD SCREEN SEEK SEG SELECT SETMEM SGN
SHARED SHELL SIGNAL SIN SINGLE SLEEP SOUND SPACE$ SPC SQR STATIC STEP STICK STOP STR$ STRIG STRING STRING$
SUB SWAP SYSTEM TAB TAN THEN TIME$ TIMER TO TROFF TRON TYPE UBOUND UCASE$ UEVENT UNLOCK UNTIL USING VAL
VARPTR VARPTR$ VARSEG VIEW WAIT WEND WHILE WIDTH WINDOW WRITE XOR
""".split())

class Tok:
    __slots__ = ("kind", "value", "line", "col", "suffix", "raw")
    def __init__(self, kind, value, line, col, suffix=None, raw=None):
        self.kind = kind      # 'num' 'str' 'id' 'kw' 'op' 'nl' 'eof' 'data' 'rem' 'meta'
        self.value = value
        self.line = line
        self.col = col
        self.suffix = suffix
        self.raw = raw
    def __repr__(self):
        return f"Tok({self.kind},{self.value!r},{self.line})"
    def is_kw(self, *names):
        return self.kind == 'kw' and self.value in names
    def is_op(self, *ops):
        return self.kind == 'op' and self.value in ops

SUFFIX_TYPE = {'%': 'i', '&': 'l', '!': 's', '#': 'd', '$': '$'}

def number_type(text, suffix, is_float, has_d_exp, value):
    if suffix:
        return SUFFIX_TYPE[suffix]
    if has_d_exp:
        return 'd'
    if not is_float:
        if -32768 <= value <= 32767:
            return 'i'
        if -2147483648 <= value <= 2147483647:
            return 'l'
        return 'd'
    mant = re.split('[EeDd]', text)[0].replace('.', '').lstrip('0').rstrip('0')
    return 'd' if len(mant) > 7 else 's'

_ident_re = re.compile(r"[A-Za-z][A-Za-z0-9.]*")
_num_re = re.compile(r"(\d+\.?\d*|\.\d+)([EeDd][+-]?\d+)?")

def tokenize(text, filename=None, line_map=None):
    """Tokenize QB source (str with chars 0-255). line_map maps physical line index -> (file, line)."""
    toks = []
    lines = text.split('\n')
    i = 0
    nlines = len(lines)
    while i < nlines:
        src_line = i + 1
        line = lines[i].rstrip('\r')
        # line continuation: a lone '_' at the end of the line outside a string
        while True:
            s = line.rstrip()
            if s.endswith(' _') or s == '_':
                # check not inside string / comment
                q = s.count('"') % 2 == 0 and "'" not in s
                if q and i + 1 < nlines:
                    line = s[:-1] + ' ' + lines[i + 1].rstrip('\r')
                    i += 1
                    continue
            break
        lex_line(line, src_line, toks, filename)
        toks.append(Tok('nl', None, src_line, len(line) + 1))
        i += 1
    toks.append(Tok('eof', None, nlines + 1, 1))
    return toks

def lex_line(line, lno, toks, filename):
    p = 0
    n = len(line)
    stmt_start = True
    while p < n:
        c = line[p]
        if c in ' \t\x1a':
            p += 1
            continue
        col = p + 1
        if c == "'":
            toks.append(Tok('rem', line[p + 1:], lno, col))
            return
        if c == '"':
            e = line.find('"', p + 1)
            if e < 0:
                s = line[p + 1:]
                p = n
            else:
                s = line[p + 1:e]
                p = e + 1
            toks.append(Tok('str', s, lno, col))
            stmt_start = False
            continue
        if c.isdigit() or (c == '.' and p + 1 < n and line[p + 1].isdigit()):
            m = _num_re.match(line, p)
            text = m.group(0)
            p = m.end()
            suffix = None
            if p < n and line[p] in '%&!#':
                # '#' after a number may also be a file number marker (e.g. PRINT #1) - not here
                suffix = line[p]
                p += 1
            is_float = '.' in text or (m.group(2) is not None)
            has_d = m.group(2) is not None and m.group(2)[0] in 'Dd'
            t = text.replace('D', 'E').replace('d', 'E')
            if is_float or suffix in ('!', '#'):
                try:
                    val = float(t)
                except ValueError:
                    val = 0.0
                if not is_float and suffix in ('!', '#'):
                    val = float(int(text))
            else:
                val = int(text)
                if suffix in ('!', '#'):
                    val = float(val)
            typ = number_type(text, suffix, is_float, has_d, val)
            if typ in ('s', 'd') and not isinstance(val, float):
                val = float(val)
            if typ in ('i', 'l') and isinstance(val, float):
                val = int(round(val))
            toks.append(Tok('num', val, lno, col, suffix=typ, raw=text))
            stmt_start = False
            continue
        if c == '&':
            # &H / &O / & octal
            q = p + 1
            base = 8
            if q < n and line[q] in 'Hh':
                base = 16
                q += 1
            elif q < n and line[q] in 'Oo':
                base = 8
                q += 1
            st = q
            digits = '0123456789ABCDEFabcdef' if base == 16 else '01234567'
            while q < n and line[q] in digits:
                q += 1
            if q > st:
                v = int(line[st:q], base)
                suffix = None
                if q < n and line[q] in '%&':
                    suffix = line[q]
                    q += 1
                if suffix == '&' or v > 0xFFFF:
                    v &= 0xFFFFFFFF
                    if v > 0x7FFFFFFF:
                        v -= 0x100000000
                    typ = 'l'
                else:
                    if v > 0x7FFF:
                        v -= 0x10000
                    typ = 'i'
                toks.append(Tok('num', v, lno, col, suffix=typ, raw=line[p:q]))
                p = q
                stmt_start = False
                continue
            toks.append(Tok('op', '&', lno, col))
            p += 1
            continue
        if c.isalpha():
            m = _ident_re.match(line, p)
            word = m.group(0)
            q = m.end()
            # trailing dots are not part of a name in practice
            up = word.upper()
            suffix = None
            if q < n and line[q] == '$' and (up + '$') in KEYWORDS:
                up = up + '$'
                word = word + '$'
                q += 1
                toks.append(Tok('kw', up, lno, col))
                p = q
                stmt_start = False
                continue
            if up in KEYWORDS and q < n and line[q] in '$%!&' and up not in ('REM', 'DATA') and \
                    not (line[q] == '&' and q + 1 < n and (line[q + 1] in 'HhOo' or line[q + 1].isdigit())):
                # a keyword with a type suffix is an ordinary variable name (e.g. Option$)
                toks.append(Tok('id', word, lno, col, suffix=line[q]))
                p = q + 1
                stmt_start = False
                continue
            if up in KEYWORDS:
                if up == 'REM':
                    toks.append(Tok('rem', line[q:], lno, col))
                    return
                if up == 'DATA':
                    # raw data until ':' outside quotes or end of line
                    r = q
                    inq = False
                    while r < n:
                        if line[r] == '"':
                            inq = not inq
                        elif line[r] == ':' and not inq:
                            break
                        r += 1
                    toks.append(Tok('data', line[q:r], lno, col))
                    p = r
                    continue
                toks.append(Tok('kw', up, lno, col))
                p = q
                stmt_start = False
                continue
            if q < n and line[q] in '$%&!#':
                suffix = line[q]
                q += 1
            # FN names keep their case-insensitive identity
            toks.append(Tok('id', word, lno, col, suffix=suffix))
            p = q
            stmt_start = False
            continue
        # operators
        two = line[p:p + 2]
        if two in ('<=', '>=', '<>', '=<', '=>', '><'):
            v = {'=<': '<=', '=>': '>=', '><': '<>'}.get(two, two)
            toks.append(Tok('op', v, lno, col))
            p += 2
            continue
        if c in '+-*/\\^=<>(),;:#.':
            toks.append(Tok('op', c, lno, col))
            p += 1
            continue
        if c == '?':
            toks.append(Tok('kw', 'PRINT', lno, col))
            p += 1
            continue
        # unknown character: ignore with error token
        toks.append(Tok('op', c, lno, col))
        p += 1
    return

META_RE = re.compile(r"^\s*\$(\w+)\s*(?::\s*'([^']*)'?)?", re.I)

def parse_meta(comment):
    """Return list of (name, arg) metacommands in a comment text."""
    res = []
    for part in re.finditer(r"\$(INCLUDE|DYNAMIC|STATIC)\s*(?::\s*'([^']*)')?", comment, re.I):
        res.append((part.group(1).upper(), part.group(2)))
    return res
