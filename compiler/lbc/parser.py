# LinBASIC compiler - parser (tokens -> AST)
# Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later.
from .lexer import Tok, QBError, KEYWORDS, SUFFIX_TYPE, parse_meta

class N:
    """Generic AST node."""
    def __init__(self, kind, line=0, **kw):
        self.kind = kind
        self.line = line
        self.__dict__.update(kw)
    def __repr__(self):
        d = {k: v for k, v in self.__dict__.items() if k not in ('kind', 'line')}
        return f"N({self.kind}@{self.line} {d})"

TYPE_NAMES = {'INTEGER': 'i', 'LONG': 'l', 'SINGLE': 's', 'DOUBLE': 'd', 'STRING': '$', 'ANY': 'any'}

# builtin functions: name -> (result type or callable, min args, max args)
BUILTIN_FUNCS = {
    'ABS': ('num', 1, 1), 'ASC': ('i', 1, 1), 'ATN': ('f', 1, 1), 'CDBL': ('d', 1, 1), 'CHR$': ('$', 1, 1),
    'CINT': ('i', 1, 1), 'CLNG': ('l', 1, 1), 'COS': ('f', 1, 1), 'CSNG': ('s', 1, 1), 'CSRLIN': ('i', 0, 0),
    'CVD': ('d', 1, 1), 'CVDMBF': ('d', 1, 1), 'CVI': ('i', 1, 1), 'CVL': ('l', 1, 1), 'CVS': ('s', 1, 1),
    'CVSMBF': ('s', 1, 1), 'DATE$': ('$', 0, 0), 'ENVIRON$': ('$', 1, 1), 'EOF': ('i', 1, 1), 'ERDEV': ('i', 0, 0),
    'ERDEV$': ('$', 0, 0), 'ERL': ('l', 0, 0), 'ERR': ('i', 0, 0), 'EXP': ('f', 1, 1), 'FILEATTR': ('l', 2, 2),
    'FIX': ('num', 1, 1), 'FRE': ('l', 1, 1), 'FREEFILE': ('i', 0, 0), 'HEX$': ('$', 1, 1), 'INKEY$': ('$', 0, 0),
    'INP': ('i', 1, 1), 'INPUT$': ('$', 1, 2), 'INSTR': ('i', 2, 3), 'INT': ('num', 1, 1), 'IOCTL$': ('$', 1, 1),
    'LBOUND': ('i', 1, 2), 'LCASE$': ('$', 1, 1), 'LEFT$': ('$', 2, 2), 'LEN': ('i', 1, 1), 'LOC': ('l', 1, 1),
    'LOF': ('l', 1, 1), 'LOG': ('f', 1, 1), 'LPOS': ('i', 1, 1), 'LTRIM$': ('$', 1, 1), 'MID$': ('$', 2, 3),
    'MKD$': ('$', 1, 1), 'MKDMBF$': ('$', 1, 1), 'MKI$': ('$', 1, 1), 'MKL$': ('$', 1, 1), 'MKS$': ('$', 1, 1),
    'MKSMBF$': ('$', 1, 1), 'OCT$': ('$', 1, 1), 'PEEK': ('i', 1, 1), 'PEN': ('i', 1, 1), 'PLAY': ('i', 1, 1),
    'PMAP': ('s', 2, 2), 'POINT': ('i', 1, 2), 'POS': ('i', 1, 1), 'RIGHT$': ('$', 2, 2), 'RND': ('s', 0, 1),
    'RTRIM$': ('$', 1, 1), 'SADD': ('i', 1, 1), 'SCREEN': ('i', 2, 3), 'SEEK': ('l', 1, 1), 'SETMEM': ('l', 1, 1),
    'SGN': ('i', 1, 1), 'SIN': ('f', 1, 1), 'SPACE$': ('$', 1, 1), 'SQR': ('f', 1, 1), 'STICK': ('i', 1, 1),
    'STR$': ('$', 1, 1), 'STRIG': ('i', 1, 1), 'STRING$': ('$', 2, 2), 'TAN': ('f', 1, 1), 'TIME$': ('$', 0, 0),
    'TIMER': ('s', 0, 0), 'UBOUND': ('i', 1, 2), 'UCASE$': ('$', 1, 1), 'VAL': ('d', 1, 1), 'VARPTR': ('i', 1, 1),
    'VARPTR$': ('$', 1, 1), 'VARSEG': ('i', 1, 1), 'COMMAND$': ('$', 0, 0),
}

class Program:
    def __init__(self):
        self.main = []          # module-level statements
        self.procs = []         # SUB / FUNCTION nodes
        self.deffns = []        # DEF FN nodes (in order)
        self.types = {}         # TYPE name -> list of (field, typeinfo)
        self.type_order = []
        self.data = []          # (label-scope position) list of raw items
        self.declares = {}      # name -> DECLARE node
        self.uses_error = False
        self.uses_events = False
        self.uses_erl = False
        self.option_base = 0
        self.source_lines = []

class Parser:
    def __init__(self, toks, filename='MAIN'):
        self.toks = toks
        self.pos = 0
        self.filename = filename
        self.prog = Program()
        self.deftypes = {chr(c): 's' for c in range(ord('A'), ord('Z') + 1)}
        self.in_proc = None
        self.pending_next = 0
        self.dynamic = False
        self.data_count = 0
        self.at_line_start = True

    # ---- token helpers -------------------------------------------------
    @property
    def tok(self):
        return self.toks[self.pos]

    def peek(self, k=1):
        p = self.pos + k
        return self.toks[p] if p < len(self.toks) else self.toks[-1]

    def next(self):
        t = self.toks[self.pos]
        if self.pos < len(self.toks) - 1:
            self.pos += 1
        return t

    def error(self, msg, t=None):
        t = t or self.tok
        raise QBError(msg, t.line, t.col, self.filename)

    def accept_op(self, op):
        if self.tok.kind == 'op' and self.tok.value == op:
            self.next()
            return True
        return False

    def expect_op(self, op, what=None):
        if not self.accept_op(op):
            self.error(f"Expected: {what or op}")

    def accept_kw(self, *kws):
        if self.tok.kind == 'kw' and self.tok.value in kws:
            return self.next().value
        return None

    def expect_kw(self, kw):
        if not self.accept_kw(kw):
            self.error(f"Expected: {kw}")

    def at_end_of_stmt(self):
        t = self.tok
        return t.kind in ('nl', 'eof', 'rem') or (t.kind == 'op' and t.value == ':') or (t.kind == 'kw' and t.value == 'ELSE')

    def skip_rem(self):
        while self.tok.kind == 'rem':
            self.handle_rem(self.next())

    def handle_rem(self, t):
        for name, arg in parse_meta(t.value):
            if name == 'DYNAMIC':
                self.dynamic = True
            elif name == 'STATIC':
                self.dynamic = False

    def deftype_of(self, name):
        c = name[0].upper()
        return self.deftypes.get(c, 's')

    # ---- program ----------------------------------------------------------
    def parse_program(self):
        body = self.parse_block(lambda: False, top=True)
        self.prog.main = body
        return self.prog

    def line_label(self):
        """At line start: line number or alphanumeric label."""
        t = self.tok
        if t.kind == 'num' and t.suffix in ('i', 'l') and isinstance(t.value, int) and t.raw and t.raw.isdigit():
            self.next()
            return N('label', t.line, name=str(t.value), numeric=True)
        if t.kind == 'id' and t.suffix is None and self.peek().kind == 'op' and self.peek().value == ':':
            self.next(); self.next()
            return N('label', t.line, name=t.value.upper(), numeric=False)
        return None

    def parse_block(self, stop, top=False):
        """Parse statements until stop() is true at the start of a statement."""
        out = []
        while True:
            t = self.tok
            if t.kind == 'eof':
                return out
            if t.kind == 'nl':
                self.next()
                self.at_line_start = True
                continue
            if t.kind == 'op' and t.value == ':':
                self.next()
                continue
            if t.kind == 'rem':
                self.handle_rem(self.next())
                continue
            if self.at_line_start:
                self.at_line_start = False
                lab = self.line_label()
                if lab:
                    out.append(lab)
                    continue
            if self.pending_next:
                return out
            if stop():
                return out
            st = self.parse_statement(top)
            if st is not None:
                if isinstance(st, list):
                    out.extend(st)
                else:
                    out.append(st)
            # after a statement we expect ':' / newline / comment
            t = self.tok
            prev = self.toks[self.pos - 1] if self.pos > 0 else None
            if prev is not None and (prev.kind == 'nl' or (prev.kind == 'op' and prev.value == ':')) and self.pos > 0:
                continue
            if not (t.kind in ('nl', 'eof', 'rem') or (t.kind == 'op' and t.value == ':')):
                if t.kind == 'kw' and t.value == 'ELSE':
                    self.error("ELSE without IF")
                self.error("Expected: end-of-statement")

    def stop_kw(self, *seqs):
        """Build a stop predicate for keyword sequences such as ('END','IF')."""
        def f():
            t = self.tok
            for seq in seqs:
                if isinstance(seq, str):
                    seq = (seq,)
                ok = True
                for k, kw in enumerate(seq):
                    tk = self.peek(k)
                    if not (tk.kind == 'kw' and tk.value == kw):
                        ok = False
                        break
                if ok:
                    return True
            return False
        return f

    # ---- statements --------------------------------------------------------
    def parse_statement(self, top=False):
        t = self.tok
        line = t.line
        if t.kind == 'data':
            self.next()
            items = split_data(t.value)
            self.prog.data.extend(items)
            n = N('data', line, index=self.data_count, count=len(items))
            self.data_count += len(items)
            return n
        if t.kind == 'kw':
            kw = t.value
            m = getattr(self, 'st_' + kw.replace('$', 'S'), None)
            if m:
                return m()
            if kw in ('MID$',):
                return self.st_MIDS()
            self.error(f"Syntax error: unexpected {kw}")
        if t.kind == 'id':
            # assignment or SUB call without CALL
            nt = self.peek()
            if self.is_sub_call_candidate():
                return self.parse_implicit_call()
            return self.parse_assignment()
        if t.kind == 'op' and t.value == '.':
            self.error("Syntax error")
        self.error("Syntax error")

    def is_sub_call_candidate(self):
        t = self.tok
        nt = self.peek()
        if t.suffix is not None:
            return False
        name = t.value.upper()
        if name in self.known_subs:
            # name followed by '=' is an assignment to a variable of the same name: not allowed in QB
            return not (nt.kind == 'op' and nt.value == '=')
        return False

    known_subs = set()

    def parse_implicit_call(self):
        t = self.next()
        args = []
        if not self.at_end_of_stmt():
            args = self.parse_call_args_noparen()
        return N('call', t.line, name=t.value.upper(), args=args)

    def parse_call_args_noparen(self):
        args = []
        while True:
            args.append(self.parse_arg())
            if not self.accept_op(','):
                break
        return args

    def parse_arg(self):
        # array passed as A() ; BYVAL / SEG keywords
        if self.accept_kw('BYVAL', 'SEG'):
            pass
        t = self.tok
        if t.kind == 'id' and self.peek().kind == 'op' and self.peek().value == '(' and \
                self.peek(2).kind == 'op' and self.peek(2).value == ')':
            self.next(); self.next(); self.next()
            return N('arrayarg', t.line, name=t.value, suffix=t.suffix, deftype=self.deftype_of(t.value))
        return self.parse_expr()

    def parse_assignment(self):
        line = self.tok.line
        self.accept_kw('LET')
        lv = self.parse_lvalue()
        if not self.accept_op('='):
            self.error("Expected: =")
        e = self.parse_expr()
        return N('assign', line, target=lv, expr=e)

    def st_LET(self):
        self.next()
        if self.tok.kind == 'kw' and self.tok.value == 'MID$':
            return self.st_MIDS()
        return self.parse_assignment()

    def parse_lvalue(self):
        t = self.tok
        if t.kind != 'id':
            self.error("Expected: variable")
        self.next()
        node = N('ref', t.line, name=t.value, suffix=t.suffix, deftype=self.deftype_of(t.value), args=None, members=[])
        if self.tok.kind == 'op' and self.tok.value == '(':
            self.next()
            args = []
            if not (self.tok.kind == 'op' and self.tok.value == ')'):
                while True:
                    args.append(self.parse_expr())
                    if not self.accept_op(','):
                        break
            self.expect_op(')')
            node.args = args
        # member access after array element: a(1).b.c  (the lexer gives ".b" as op '.', id)
        while self.tok.kind == 'op' and self.tok.value == '.':
            self.next()
            m = self.tok
            if m.kind not in ('id', 'kw'):
                self.error("Expected: element name")
            self.next()
            node.members.append((m.value, m.suffix))
        return node

    # ---------- PRINT family ----------
    def parse_filenum(self):
        """'#' expr ','  -> expr  (the '#' already seen?)"""
        self.expect_op('#')
        e = self.parse_expr()
        return e

    def parse_print_items(self, allow_using=True):
        using = None
        if allow_using and self.accept_kw('USING'):
            using = self.parse_expr()
            if not self.accept_op(';'):
                self.expect_op(',')
        items = []
        while not self.at_end_of_stmt():
            if self.accept_op(';'):
                items.append(('semi',))
                continue
            if self.accept_op(','):
                items.append(('comma',))
                continue
            if self.tok.kind == 'kw' and self.tok.value in ('TAB', 'SPC') and self.peek().kind == 'op' and self.peek().value == '(':
                k = self.next().value
                self.next()
                e = self.parse_expr()
                self.expect_op(')')
                items.append((k.lower(), e))
                continue
            if self.tok.kind == 'kw' and self.tok.value == 'USING' and allow_using:
                self.next()
                using = self.parse_expr()
                if not self.accept_op(';'):
                    self.expect_op(',')
                continue
            items.append(('expr', self.parse_expr()))
        return using, items

    def st_PRINT(self):
        line = self.next().line
        fileno = None
        if self.tok.kind == 'op' and self.tok.value == '#':
            self.next()
            fileno = self.parse_expr()
            if not self.at_end_of_stmt():
                self.expect_op(',')
        using, items = self.parse_print_items()
        return N('print', line, fileno=fileno, using=using, items=items, lprint=False)

    def st_LPRINT(self):
        line = self.next().line
        using, items = self.parse_print_items()
        return N('print', line, fileno=None, using=using, items=items, lprint=True)

    def st_WRITE(self):
        line = self.next().line
        fileno = None
        if self.accept_op('#'):
            fileno = self.parse_expr()
            if not self.at_end_of_stmt():
                self.expect_op(',')
        items = []
        while not self.at_end_of_stmt():
            items.append(self.parse_expr())
            if not self.accept_op(',') and not self.accept_op(';'):
                break
        return N('write', line, fileno=fileno, items=items)

    def st_INPUT(self):
        line = self.next().line
        if self.accept_op('#'):
            fn = self.parse_expr()
            self.expect_op(',')
            vars_ = self.parse_lvalue_list()
            return N('input', line, fileno=fn, prompt=None, semi=False, nq=False, vars=vars_)
        semi = self.accept_op(';')
        prompt = None
        nq = False
        if self.tok.kind == 'str':
            prompt = self.next().value
            if self.accept_op(','):
                nq = True
            else:
                self.expect_op(';')
        vars_ = self.parse_lvalue_list()
        return N('input', line, fileno=None, prompt=prompt, semi=semi, nq=nq, vars=vars_)

    def parse_lvalue_list(self):
        out = []
        while True:
            out.append(self.parse_lvalue())
            if not self.accept_op(','):
                break
        return out

    def st_LINE(self):
        t = self.next()
        if self.accept_kw('INPUT'):
            if self.accept_op('#'):
                fn = self.parse_expr()
                self.expect_op(',')
                v = self.parse_lvalue()
                return N('lineinput', t.line, fileno=fn, prompt=None, semi=False, var=v)
            semi = self.accept_op(';')
            prompt = None
            if self.tok.kind == 'str':
                prompt = self.next().value
                if not self.accept_op(';'):
                    self.expect_op(',')
            v = self.parse_lvalue()
            return N('lineinput', t.line, fileno=None, prompt=prompt, semi=semi, var=v)
        # graphics LINE [[STEP](x1,y1)]-[STEP](x2,y2)[,[color][,[B[F]][,style]]]
        step1 = step2 = False
        p1 = None
        if self.accept_kw('STEP'):
            step1 = True
        if self.tok.kind == 'op' and self.tok.value == '(':
            p1 = self.parse_point()
        self.expect_op('-')
        if self.accept_kw('STEP'):
            step2 = True
        p2 = self.parse_point()
        color = box = style = None
        if self.accept_op(','):
            if not (self.tok.kind == 'op' and self.tok.value == ',') and not self.at_end_of_stmt():
                color = self.parse_expr()
            if self.accept_op(','):
                if self.tok.kind == 'id' and self.tok.value.upper() in ('B', 'BF'):
                    box = self.next().value.upper()
                if self.accept_op(','):
                    style = self.parse_expr()
        return N('gline', t.line, step1=step1, p1=p1, step2=step2, p2=p2, color=color, box=box, style=style)

    def parse_point(self):
        self.expect_op('(')
        x = self.parse_expr()
        self.expect_op(',')
        y = self.parse_expr()
        self.expect_op(')')
        return (x, y)

    def opt_args(self, maxn):
        """Comma separated optional arguments: returns list with None for missing."""
        args = []
        if self.at_end_of_stmt():
            return args
        while True:
            if (self.tok.kind == 'op' and self.tok.value == ',') or self.at_end_of_stmt():
                args.append(None)
            else:
                args.append(self.parse_expr())
            if not self.accept_op(','):
                break
        return args

    # ---------- control flow ----------
    def st_IF(self):
        line = self.next().line
        cond = self.parse_expr()
        if self.accept_kw('GOTO'):
            target = self.parse_label_ref()
            then = [N('goto', line, target=target)]
            els = None
            if self.accept_kw('ELSE'):
                els = self.parse_inline_else(line)
            return N('if', line, cond=cond, then=then, elifs=[], els=els)
        self.expect_kw('THEN')
        if self.tok.kind in ('nl', 'eof', 'rem'):
            # block IF
            self.skip_rem()
            then = self.parse_block(self.stop_kw('ELSEIF', 'ELSE', ('END', 'IF'), 'ENDIF'))
            elifs = []
            els = None
            while True:
                if self.accept_kw('ELSEIF'):
                    c = self.parse_expr()
                    self.expect_kw('THEN')
                    b = self.parse_block(self.stop_kw('ELSEIF', 'ELSE', ('END', 'IF'), 'ENDIF'))
                    elifs.append((c, b))
                    continue
                if self.accept_kw('ELSE'):
                    els = self.parse_block(self.stop_kw(('END', 'IF'), 'ENDIF'))
                    continue
                if self.tok.is_kw('END'):
                    self.next()
                    self.expect_kw('IF')
                    break
                self.error("Block IF without END IF")
            return N('if', line, cond=cond, then=then, elifs=elifs, els=els)
        # single-line IF
        then = self.parse_inline_stmts(line)
        els = None
        if self.accept_kw('ELSE'):
            els = self.parse_inline_else(line)
        return N('if', line, cond=cond, then=then, elifs=[], els=els)

    def parse_inline_else(self, line):
        if self.tok.kind == 'num':
            return [N('goto', line, target=self.parse_label_ref())]
        return self.parse_inline_stmts(line)

    def parse_inline_stmts(self, line):
        out = []
        if self.tok.kind == 'num':
            out.append(N('goto', line, target=self.parse_label_ref()))
            return out
        while True:
            if self.tok.kind in ('nl', 'eof', 'rem') or self.tok.is_kw('ELSE'):
                break
            if self.accept_op(':'):
                continue
            st = self.parse_statement()
            if st is not None:
                if isinstance(st, list):
                    out.extend(st)
                else:
                    out.append(st)
            if not self.accept_op(':'):
                break
        return out

    def parse_label_ref(self):
        t = self.tok
        if t.kind == 'num':
            self.next()
            return str(int(t.value)) if isinstance(t.value, int) else t.raw
        if t.kind == 'id':
            self.next()
            return t.value.upper()
        self.error("Expected: label or line number")

    def st_GOTO(self):
        line = self.next().line
        return N('goto', line, target=self.parse_label_ref())

    def st_GOSUB(self):
        line = self.next().line
        return N('gosub', line, target=self.parse_label_ref())

    def st_RETURN(self):
        line = self.next().line
        target = None
        if self.tok.kind in ('num', 'id'):
            target = self.parse_label_ref()
        return N('return', line, target=target)

    def st_FOR(self):
        line = self.next().line
        var = self.parse_lvalue()
        self.expect_op('=')
        start = self.parse_expr()
        self.expect_kw('TO')
        end = self.parse_expr()
        step = None
        if self.accept_kw('STEP'):
            step = self.parse_expr()
        body = self.parse_block(self.stop_kw('NEXT'))
        if self.pending_next:
            self.pending_next -= 1
        elif self.accept_kw('NEXT'):
            nvars = 0
            if not self.at_end_of_stmt():
                self.parse_lvalue()
                nvars = 1
                while self.accept_op(','):
                    self.parse_lvalue()
                    nvars += 1
            if nvars > 1:
                self.pending_next = nvars - 1
        else:
            self.error("FOR without NEXT")
        return N('for', line, var=var, start=start, end=end, step=step, body=body)

    def st_NEXT(self):
        self.error("NEXT without FOR")

    def st_DO(self):
        line = self.next().line
        pre = None
        if self.tok.is_kw('WHILE', 'UNTIL'):
            k = self.next().value
            pre = (k, self.parse_expr())
        body = self.parse_block(self.stop_kw('LOOP'))
        if not self.accept_kw('LOOP'):
            self.error("DO without LOOP")
        post = None
        if self.tok.is_kw('WHILE', 'UNTIL'):
            k = self.next().value
            post = (k, self.parse_expr())
        return N('do', line, pre=pre, post=post, body=body)

    def st_LOOP(self):
        self.error("LOOP without DO")

    def st_WHILE(self):
        line = self.next().line
        cond = self.parse_expr()
        body = self.parse_block(self.stop_kw('WEND'))
        if not self.accept_kw('WEND'):
            self.error("WHILE without WEND")
        return N('do', line, pre=('WHILE', cond), post=None, body=body, wend=True)

    def st_WEND(self):
        self.error("WEND without WHILE")

    def st_SELECT(self):
        line = self.next().line
        self.expect_kw('CASE')
        sel = self.parse_expr()
        cases = []
        els = None
        # skip until first CASE
        pre = self.parse_block(self.stop_kw('CASE', ('END', 'SELECT')))
        while True:
            if self.accept_kw('CASE'):
                if self.accept_kw('ELSE'):
                    els = self.parse_block(self.stop_kw('CASE', ('END', 'SELECT')))
                    continue
                tests = []
                while True:
                    if self.accept_kw('IS'):
                        op = self.next()
                        if op.kind != 'op' or op.value not in ('=', '<>', '<', '>', '<=', '>='):
                            self.error("Expected: relational operator")
                        tests.append(('is', op.value, self.parse_expr()))
                    else:
                        a = self.parse_expr()
                        if self.accept_kw('TO'):
                            b = self.parse_expr()
                            tests.append(('range', a, b))
                        elif self.tok.kind == 'op' and self.tok.value in ('=', '<>', '<', '>', '<=', '>=') and False:
                            pass
                        else:
                            tests.append(('eq', a))
                    if not self.accept_op(','):
                        break
                body = self.parse_block(self.stop_kw('CASE', ('END', 'SELECT')))
                cases.append((tests, body))
                continue
            if self.accept_kw('END'):
                self.expect_kw('SELECT')
                break
            self.error("SELECT without END SELECT")
        return N('select', line, expr=sel, cases=cases, els=els)

    def st_CASE(self):
        self.error("CASE without SELECT")

    def st_ON(self):
        line = self.next().line
        if self.accept_kw('ERROR'):
            self.prog.uses_error = True
            self.expect_kw('GOTO')
            t = self.tok
            if t.kind == 'num' and t.value == 0:
                self.next()
                return N('onerror', line, target=None)
            return N('onerror', line, target=self.parse_label_ref())
        # event traps
        if self.tok.is_kw('KEY', 'TIMER', 'PLAY', 'STRIG', 'PEN', 'COM') or (self.tok.kind == 'id' and self.tok.value.upper() == 'UEVENT'):
            ev = self.next().value.upper()
            arg = None
            if self.accept_op('('):
                arg = self.parse_expr()
                self.expect_op(')')
            self.expect_kw('GOSUB')
            self.prog.uses_events = True
            target = self.parse_label_ref()
            return N('onevent', line, event=ev, arg=arg, target=target)
        e = self.parse_expr()
        kw = self.accept_kw('GOTO', 'GOSUB')
        if not kw:
            self.error("Expected: GOTO or GOSUB")
        targets = [self.parse_label_ref()]
        while self.accept_op(','):
            targets.append(self.parse_label_ref())
        return N('ongoto', line, expr=e, gosub=(kw == 'GOSUB'), targets=targets)

    def st_RESUME(self):
        line = self.next().line
        self.prog.uses_error = True
        if self.accept_kw('NEXT'):
            return N('resume', line, mode='next', target=None)
        if self.tok.kind == 'num' and self.tok.value == 0:
            self.next()
            return N('resume', line, mode='retry', target=None)
        if self.tok.kind in ('num', 'id'):
            return N('resume', line, mode='label', target=self.parse_label_ref())
        return N('resume', line, mode='retry', target=None)

    def st_ERROR(self):
        line = self.next().line
        return N('error', line, expr=self.parse_expr())

    def st_END(self):
        line = self.next().line
        if self.tok.kind == 'kw' and self.tok.value in ('IF', 'SELECT', 'SUB', 'FUNCTION', 'TYPE', 'DEF'):
            self.error(f"END {self.tok.value} without block")
        return N('end', line)

    def st_STOP(self):
        return N('stop', self.next().line)

    def st_SYSTEM(self):
        return N('system', self.next().line)

    def st_EXIT(self):
        line = self.next().line
        k = self.accept_kw('FOR', 'DO', 'SUB', 'FUNCTION', 'DEF')
        if not k:
            self.error("Expected: FOR, DO, SUB, FUNCTION or DEF")
        return N('exit', line, what=k)

    # ---------- declarations ----------
    def parse_type_name(self):
        t = self.tok
        if t.kind == 'kw' and t.value in TYPE_NAMES:
            self.next()
            if t.value == 'STRING' and self.accept_op('*'):
                n = self.parse_expr()
                return ('fixed', n)
            return TYPE_NAMES[t.value]
        if t.kind == 'id':
            self.next()
            return ('udt', t.value.upper())
        self.error("Expected: type name")

    def parse_dim_list(self, kind):
        line = self.tok.line
        shared = bool(self.accept_kw('SHARED'))
        out = []
        while True:
            t = self.tok
            if t.kind != 'id':
                self.error("Expected: identifier")
            self.next()
            dims = None
            if self.accept_op('('):
                dims = []
                if not (self.tok.kind == 'op' and self.tok.value == ')'):
                    while True:
                        a = self.parse_expr()
                        if self.accept_kw('TO'):
                            b = self.parse_expr()
                            dims.append((a, b))
                        else:
                            dims.append((None, a))
                        if not self.accept_op(','):
                            break
                self.expect_op(')')
            astype = None
            if self.accept_kw('AS'):
                astype = self.parse_type_name()
            out.append(N('dimvar', t.line, name=t.value, suffix=t.suffix, deftype=self.deftype_of(t.value),
                         dims=dims, astype=astype))
            if not self.accept_op(','):
                break
        return N(kind, line, shared=shared, vars=out, dynamic=self.dynamic)

    def st_DIM(self):
        self.next()
        return self.parse_dim_list('dim')

    def st_REDIM(self):
        self.next()
        self.accept_kw('PRESERVE') if False else None
        return self.parse_dim_list('redim')

    def st_STATIC(self):
        self.next()
        return self.parse_shared_static('static')

    def st_SHARED(self):
        self.next()
        return self.parse_shared_static('shared')

    def parse_shared_static(self, kind):
        line = self.tok.line
        out = []
        while True:
            t = self.tok
            if t.kind != 'id':
                self.error("Expected: identifier")
            self.next()
            isarr = False
            dims = None
            if self.accept_op('('):
                isarr = True
                # STATIC a(10) is allowed in QB (dimension)
                if not (self.tok.kind == 'op' and self.tok.value == ')'):
                    dims = []
                    while True:
                        a = self.parse_expr()
                        if self.accept_kw('TO'):
                            dims.append((a, self.parse_expr()))
                        else:
                            dims.append((None, a))
                        if not self.accept_op(','):
                            break
                self.expect_op(')')
            astype = None
            if self.accept_kw('AS'):
                astype = self.parse_type_name()
            out.append(N('dimvar', t.line, name=t.value, suffix=t.suffix, deftype=self.deftype_of(t.value),
                         isarr=isarr, dims=dims, astype=astype))
            if not self.accept_op(','):
                break
        return N(kind, line, vars=out)

    def st_COMMON(self):
        line = self.next().line
        shared = bool(self.accept_kw('SHARED'))
        if self.accept_op('/'):
            self.next()
            self.expect_op('/')
        st = self.parse_shared_static('common')
        st.shared = shared
        return st

    def st_CONST(self):
        line = self.next().line
        out = []
        while True:
            t = self.tok
            if t.kind != 'id':
                self.error("Expected: identifier")
            self.next()
            self.expect_op('=')
            e = self.parse_expr()
            out.append((t.value, t.suffix, e))
            if not self.accept_op(','):
                break
        return N('const', line, items=out)

    def def_letters(self, typ):
        line = self.next().line
        while True:
            t = self.next()
            if t.kind not in ('id', 'kw'):
                self.error("Expected: letter range")
            a = t.value[0].upper()
            b = a
            if self.accept_op('-'):
                t2 = self.next()
                b = t2.value[0].upper()
            for c in range(ord(a), ord(b) + 1):
                self.deftypes[chr(c)] = typ
            if not self.accept_op(','):
                break
        return N('deftype', line, typ=typ)

    def st_DEFINT(self): return self.def_letters('i')
    def st_DEFLNG(self): return self.def_letters('l')
    def st_DEFSNG(self): return self.def_letters('s')
    def st_DEFDBL(self): return self.def_letters('d')
    def st_DEFSTR(self): return self.def_letters('$')

    def st_OPTION(self):
        line = self.next().line
        self.expect_kw('BASE')
        t = self.next()
        if t.kind != 'num' or t.value not in (0, 1):
            self.error("Expected: 0 or 1")
        self.prog.option_base = t.value
        return N('optionbase', line, base=t.value)

    def st_TYPE(self):
        line = self.next().line
        name_t = self.next()
        if name_t.kind != 'id':
            self.error("Expected: type name")
        name = name_t.value.upper()
        fields = []
        while True:
            t = self.tok
            if t.kind in ('nl', 'rem') or (t.kind == 'op' and t.value == ':'):
                self.next()
                continue
            if t.kind == 'eof':
                self.error("TYPE without END TYPE")
            if t.is_kw('END'):
                self.next()
                self.expect_kw('TYPE')
                break
            if t.kind not in ('id', 'kw'):
                self.error("Expected: element name")
            self.next()
            if self.accept_op('('):
                self.error("Arrays not allowed in TYPE")
            self.expect_kw('AS')
            ty = self.parse_type_name()
            fields.append((t.value.upper(), ty))
        self.prog.types[name] = fields
        self.prog.type_order.append(name)
        return None

    def st_DECLARE(self):
        line = self.next().line
        kind = self.accept_kw('SUB', 'FUNCTION')
        if not kind:
            self.error("Expected: SUB or FUNCTION")
        t = self.next()
        name = t.value.upper()
        cdecl = False
        if self.accept_kw('CDECL'):
            cdecl = True
        if self.accept_kw('ALIAS'):
            self.next()
        params = None
        if self.accept_op('('):
            params = self.parse_params()
        n = N('declare', line, what=kind, name=name, suffix=t.suffix, deftype=self.deftype_of(name), params=params)
        self.prog.declares[name] = n
        if kind == 'SUB':
            Parser.known_subs.add(name)
        return n

    def parse_params(self):
        params = []
        if self.accept_op(')'):
            return params
        while True:
            byval = bool(self.accept_kw('BYVAL'))
            self.accept_kw('SEG')
            t = self.next()
            if t.kind not in ('id', 'kw'):
                self.error("Expected: parameter")
            isarr = False
            if self.accept_op('('):
                # may contain number of dimensions
                if self.tok.kind == 'num':
                    self.next()
                self.expect_op(')')
                isarr = True
            astype = None
            if self.accept_kw('AS'):
                astype = self.parse_type_name()
            params.append(N('param', t.line, name=t.value, suffix=t.suffix, deftype=self.deftype_of(t.value),
                            isarr=isarr, astype=astype, byval=byval))
            if not self.accept_op(','):
                break
        self.expect_op(')')
        return params

    def st_SUB(self):
        return self.parse_proc('SUB')

    def st_FUNCTION(self):
        return self.parse_proc('FUNCTION')

    def parse_proc(self, kind):
        line = self.next().line
        if self.in_proc:
            self.error(f"{kind} not allowed in procedure")
        t = self.next()
        name = t.value.upper()
        params = []
        if self.accept_op('('):
            params = self.parse_params()
        static = bool(self.accept_kw('STATIC'))
        saved_def = dict(self.deftypes)
        saved_dyn = self.dynamic
        proc = N('proc', line, what=kind, name=name, suffix=t.suffix, deftype=self.deftype_of(name),
                 params=params, static=static, body=None)
        self.in_proc = proc
        if kind == 'SUB':
            Parser.known_subs.add(name)
        body = self.parse_block(self.stop_kw(('END', kind)))
        if not self.accept_kw('END'):
            self.error(f"{kind} without END {kind}")
        self.expect_kw(kind)
        proc.body = body
        self.in_proc = None
        self.deftypes = saved_def
        self.dynamic = saved_dyn
        self.prog.procs.append(proc)
        return None

    def st_DEF(self):
        line = self.next().line
        if self.tok.is_kw('SEG'):
            self.next()
            if self.accept_op('='):
                return N('defseg', line, expr=self.parse_expr())
            return N('defseg', line, expr=None)
        t = self.next()
        if t.kind != 'id' or not t.value.upper().startswith('FN'):
            self.error("Expected: FN name")
        name = t.value.upper()
        params = []
        if self.accept_op('('):
            while True:
                p = self.next()
                astype = None
                if self.accept_kw('AS'):
                    astype = self.parse_type_name()
                params.append(N('param', p.line, name=p.value, suffix=p.suffix, deftype=self.deftype_of(p.value),
                                isarr=False, astype=astype, byval=True))
                if not self.accept_op(','):
                    break
            self.expect_op(')')
        fn = N('deffn', line, name=name, suffix=t.suffix, deftype=self.deftype_of(name), params=params, expr=None, body=None)
        if self.accept_op('='):
            fn.expr = self.parse_expr()
        else:
            body = self.parse_block(self.stop_kw(('END', 'DEF')))
            if not self.accept_kw('END'):
                self.error("DEF without END DEF")
            self.expect_kw('DEF')
            fn.body = body
        self.prog.deffns.append(fn)
        return N('deffn_decl', line, fn=fn)

    def st_CALL(self):
        line = self.next().line
        t = self.next()
        if t.kind not in ('id', 'kw'):
            self.error("Expected: procedure name")
        name = t.value.upper()
        args = []
        if self.accept_op('('):
            if not self.accept_op(')'):
                while True:
                    args.append(self.parse_arg())
                    if not self.accept_op(','):
                        break
                self.expect_op(')')
        return N('call', line, name=name, args=args)

    def st_CALLS(self):
        return self.st_CALL()

    # ---------- data ----------
    def st_READ(self):
        line = self.next().line
        return N('read', line, vars=self.parse_lvalue_list())

    def st_RESTORE(self):
        line = self.next().line
        target = None
        if self.tok.kind in ('num', 'id'):
            target = self.parse_label_ref()
        return N('restore', line, target=target)

    def st_SWAP(self):
        line = self.next().line
        a = self.parse_lvalue()
        self.expect_op(',')
        b = self.parse_lvalue()
        return N('swap', line, a=a, b=b)

    def st_ERASE(self):
        line = self.next().line
        names = []
        while True:
            t = self.next()
            names.append((t.value, t.suffix, self.deftype_of(t.value)))
            if not self.accept_op(','):
                break
        return N('erase', line, names=names)

    def st_MIDS(self):
        line = self.next().line
        self.expect_op('(')
        v = self.parse_lvalue()
        self.expect_op(',')
        start = self.parse_expr()
        ln = None
        if self.accept_op(','):
            ln = self.parse_expr()
        self.expect_op(')')
        self.expect_op('=')
        e = self.parse_expr()
        return N('midstmt', line, var=v, start=start, len=ln, expr=e)

    def st_LSET(self):
        line = self.next().line
        v = self.parse_lvalue()
        self.expect_op('=')
        return N('lset', line, var=v, expr=self.parse_expr(), right=False)

    def st_RSET(self):
        line = self.next().line
        v = self.parse_lvalue()
        self.expect_op('=')
        return N('lset', line, var=v, expr=self.parse_expr(), right=True)

    # ---------- screen / graphics ----------
    def simple(kind, maxn=8):
        def f(self):
            line = self.next().line
            return N('simple', line, what=kind, args=self.opt_args(maxn))
        return f

    st_CLS = simple('CLS')
    st_LOCATE = simple('LOCATE')
    st_COLOR = simple('COLOR')
    st_BEEP = simple('BEEP')
    st_SOUND = simple('SOUND')
    st_PLAYSTMT = simple('PLAY')
    st_RANDOMIZE = simple('RANDOMIZE')
    st_SLEEP = simple('SLEEP')
    st_POKE = simple('POKE')
    st_OUT = simple('OUT')
    st_WAIT = simple('WAIT')
    st_PCOPY = simple('PCOPY')
    st_DRAW = simple('DRAW')
    st_KILL = simple('KILL')
    st_MKDIR = simple('MKDIR')
    st_RMDIR = simple('RMDIR')
    st_CHDIR = simple('CHDIR')
    st_FILES = simple('FILES')
    st_SHELL = simple('SHELL')
    st_CHAIN = simple('CHAIN')
    st_BLOAD = simple('BLOAD')
    st_BSAVE = simple('BSAVE')
    st_ENVIRON = simple('ENVIRON')
    st_RESET = simple('RESET')
    st_CLEAR = simple('CLEAR')
    st_TRON = simple('TRON')
    st_TROFF = simple('TROFF')
    st_IOCTL = simple('IOCTL')
    st_RUN = simple('RUN')

    def st_PLAY(self):
        line = self.next().line
        if self.tok.is_kw('ON', 'OFF', 'STOP'):
            return N('evstate', line, event='PLAY', arg=None, state=self.next().value)
        return N('simple', line, what='PLAY', args=self.opt_args(1))

    def st_TIMER(self):
        line = self.next().line
        st = self.accept_kw('ON', 'OFF', 'STOP')
        if not st:
            self.error("Expected: ON, OFF or STOP")
        return N('evstate', line, event='TIMER', arg=None, state=st)

    def st_STRIG(self):
        line = self.next().line
        arg = None
        if self.accept_op('('):
            arg = self.parse_expr(); self.expect_op(')')
        st = self.accept_kw('ON', 'OFF', 'STOP')
        return N('evstate', line, event='STRIG', arg=arg, state=st or 'ON')

    def st_PEN(self):
        line = self.next().line
        st = self.accept_kw('ON', 'OFF', 'STOP')
        return N('evstate', line, event='PEN', arg=None, state=st or 'ON')

    def st_COM(self):
        line = self.next().line
        arg = None
        if self.accept_op('('):
            arg = self.parse_expr(); self.expect_op(')')
        st = self.accept_kw('ON', 'OFF', 'STOP')
        return N('evstate', line, event='COM', arg=arg, state=st or 'ON')

    def st_KEY(self):
        line = self.next().line
        if self.accept_op('('):
            arg = self.parse_expr()
            self.expect_op(')')
            st = self.accept_kw('ON', 'OFF', 'STOP')
            if not st:
                self.error("Expected: ON, OFF or STOP")
            return N('evstate', line, event='KEY', arg=arg, state=st)
        if self.tok.is_kw('ON', 'OFF', 'LIST'):
            return N('keystmt', line, what=self.next().value, args=[])
        args = self.opt_args(2)
        return N('keystmt', line, what='SET', args=args)

    def st_UEVENT(self):
        line = self.next().line
        self.accept_kw('ON', 'OFF', 'STOP')
        return None

    def st_SCREEN(self):
        line = self.next().line
        return N('simple', line, what='SCREEN', args=self.opt_args(4))

    def st_WIDTH(self):
        line = self.next().line
        if self.accept_op('#'):
            fn = self.parse_expr()
            self.expect_op(',')
            return N('simple', line, what='WIDTHFILE', args=[fn, self.parse_expr()])
        if self.accept_kw('LPRINT'):
            return N('simple', line, what='WIDTHLPRINT', args=[self.parse_expr()])
        if self.tok.kind == 'str':
            dev = self.parse_expr()
            self.expect_op(',')
            return N('simple', line, what='WIDTHDEV', args=[dev, self.parse_expr()])
        return N('simple', line, what='WIDTH', args=self.opt_args(2))

    def st_VIEW(self):
        line = self.next().line
        if self.accept_kw('PRINT'):
            if self.at_end_of_stmt():
                return N('viewprint', line, top=None, bottom=None)
            top = self.parse_expr()
            self.expect_kw('TO')
            return N('viewprint', line, top=top, bottom=self.parse_expr())
        screen = bool(self.accept_kw('SCREEN'))
        if self.at_end_of_stmt():
            return N('view', line, screen=screen, p1=None, p2=None, fill=None, border=None)
        p1 = self.parse_point()
        self.expect_op('-')
        p2 = self.parse_point()
        fill = border = None
        if self.accept_op(','):
            if not (self.tok.kind == 'op' and self.tok.value == ','):
                fill = self.parse_expr()
            if self.accept_op(','):
                border = self.parse_expr()
        return N('view', line, screen=screen, p1=p1, p2=p2, fill=fill, border=border)

    def st_WINDOW(self):
        line = self.next().line
        screen = bool(self.accept_kw('SCREEN'))
        if self.at_end_of_stmt():
            return N('window', line, screen=screen, p1=None, p2=None)
        p1 = self.parse_point()
        self.expect_op('-')
        p2 = self.parse_point()
        return N('window', line, screen=screen, p1=p1, p2=p2)

    def st_PSET(self):
        return self.parse_pset(False)

    def st_PRESET(self):
        return self.parse_pset(True)

    def parse_pset(self, preset):
        line = self.next().line
        step = bool(self.accept_kw('STEP'))
        p = self.parse_point()
        color = None
        if self.accept_op(','):
            color = self.parse_expr()
        return N('pset', line, step=step, p=p, color=color, preset=preset)

    def st_CIRCLE(self):
        line = self.next().line
        step = bool(self.accept_kw('STEP'))
        p = self.parse_point()
        self.expect_op(',')
        r = self.parse_expr()
        rest = []
        if self.accept_op(','):
            rest = self.opt_args(4)
        while len(rest) < 4:
            rest.append(None)
        return N('circle', line, step=step, p=p, r=r, color=rest[0], start=rest[1], end=rest[2], aspect=rest[3])

    def st_PAINT(self):
        line = self.next().line
        step = bool(self.accept_kw('STEP'))
        p = self.parse_point()
        rest = []
        if self.accept_op(','):
            rest = self.opt_args(3)
        while len(rest) < 3:
            rest.append(None)
        return N('paint', line, step=step, p=p, paint=rest[0], border=rest[1], bg=rest[2])

    def st_PALETTE(self):
        line = self.next().line
        if self.accept_kw('USING'):
            arr = self.parse_lvalue()
            return N('paletteusing', line, arr=arr)
        return N('simple', line, what='PALETTE', args=self.opt_args(2))

    def st_GET(self):
        return self.parse_getput('GET')

    def st_PUT(self):
        return self.parse_getput('PUT')

    def parse_getput(self, what):
        line = self.next().line
        if self.tok.is_kw('STEP') or (self.tok.kind == 'op' and self.tok.value == '('):
            # graphics
            step1 = bool(self.accept_kw('STEP'))
            p1 = self.parse_point()
            if what == 'GET':
                self.expect_op('-')
                step2 = bool(self.accept_kw('STEP'))
                p2 = self.parse_point()
                self.expect_op(',')
                arr = self.parse_lvalue()
                return N('gget', line, step1=step1, p1=p1, step2=step2, p2=p2, arr=arr)
            self.expect_op(',')
            arr = self.parse_lvalue()
            action = None
            if self.accept_op(','):
                a = self.next()
                action = a.value.upper()
            return N('gput', line, step=step1, p=p1, arr=arr, action=action)
        self.accept_op('#')
        fn = self.parse_expr()
        rec = var = None
        if self.accept_op(','):
            if not (self.tok.kind == 'op' and self.tok.value == ','):
                rec = self.parse_expr()
            if self.accept_op(','):
                var = self.parse_lvalue()
        return N('fgetput', line, what=what, fileno=fn, rec=rec, var=var)

    # ---------- files ----------
    def st_OPEN(self):
        line = self.next().line
        first = self.parse_expr()
        if self.accept_op(','):
            # old syntax: OPEN mode$, [#]n, file$[, reclen]
            self.accept_op('#')
            fn = self.parse_expr()
            self.expect_op(',')
            name = self.parse_expr()
            reclen = None
            if self.accept_op(','):
                reclen = self.parse_expr()
            return N('openold', line, mode=first, fileno=fn, name=name, reclen=reclen)
        mode = None
        access = None
        lock = None
        if self.accept_kw('FOR'):
            m = self.next()
            mode = m.value.upper()
            if mode not in ('INPUT', 'OUTPUT', 'APPEND', 'RANDOM', 'BINARY'):
                self.error("Expected: INPUT, OUTPUT, APPEND, RANDOM or BINARY")
        if self.accept_kw('ACCESS'):
            a = self.next().value.upper()
            if self.tok.is_kw('WRITE'):
                self.next()
                a = 'READWRITE'
            access = a
        if self.tok.is_kw('LOCK') or (self.tok.kind == 'id' and self.tok.value.upper() == 'SHARED') or self.tok.is_kw('SHARED'):
            self.next()
            while self.tok.is_kw('READ', 'WRITE'):
                self.next()
        self.expect_kw('AS')
        self.accept_op('#')
        fn = self.parse_expr()
        reclen = None
        if self.accept_kw('LEN'):
            self.expect_op('=')
            reclen = self.parse_expr()
        return N('open', line, name=first, mode=mode, access=access, fileno=fn, reclen=reclen)

    def st_CLOSE(self):
        line = self.next().line
        files = []
        while not self.at_end_of_stmt():
            self.accept_op('#')
            files.append(self.parse_expr())
            if not self.accept_op(','):
                break
        return N('close', line, files=files)

    def st_FIELD(self):
        line = self.next().line
        self.accept_op('#')
        fn = self.parse_expr()
        fields = []
        while self.accept_op(','):
            w = self.parse_expr()
            self.expect_kw('AS')
            v = self.parse_lvalue()
            fields.append((w, v))
        return N('field', line, fileno=fn, fields=fields)

    def st_SEEK(self):
        line = self.next().line
        self.accept_op('#')
        fn = self.parse_expr()
        self.expect_op(',')
        return N('seek', line, fileno=fn, pos=self.parse_expr())

    def st_LOCK(self):
        line = self.next().line
        self.accept_op('#')
        fn = self.parse_expr()
        if self.accept_op(','):
            self.parse_expr()
            if self.accept_kw('TO'):
                self.parse_expr()
        return N('nop', line)

    st_UNLOCK = st_LOCK

    def st_NAME(self):
        line = self.next().line
        a = self.parse_expr()
        self.expect_kw('AS')
        return N('name', line, a=a, b=self.parse_expr())

    def st_DATES(self):
        line = self.next().line
        self.expect_op('=')
        return N('simple', line, what='DATESET', args=[self.parse_expr()])

    def st_TIMES(self):
        line = self.next().line
        self.expect_op('=')
        return N('simple', line, what='TIMESET', args=[self.parse_expr()])

    def st_REM(self):
        self.next()
        return None

    # ---- expressions -------------------------------------------------------
    BINPREC = [
        ('IMP',), ('EQV',), ('XOR',), ('OR',), ('AND',),
    ]

    def parse_expr(self):
        return self.parse_imp()

    def parse_imp(self):
        a = self.parse_eqv()
        while self.tok.is_kw('IMP'):
            line = self.next().line
            a = N('bin', line, op='IMP', a=a, b=self.parse_eqv())
        return a

    def parse_eqv(self):
        a = self.parse_xor()
        while self.tok.is_kw('EQV'):
            line = self.next().line
            a = N('bin', line, op='EQV', a=a, b=self.parse_xor())
        return a

    def parse_xor(self):
        a = self.parse_or()
        while self.tok.is_kw('XOR'):
            line = self.next().line
            a = N('bin', line, op='XOR', a=a, b=self.parse_or())
        return a

    def parse_or(self):
        a = self.parse_and()
        while self.tok.is_kw('OR'):
            line = self.next().line
            a = N('bin', line, op='OR', a=a, b=self.parse_and())
        return a

    def parse_and(self):
        a = self.parse_not()
        while self.tok.is_kw('AND'):
            line = self.next().line
            a = N('bin', line, op='AND', a=a, b=self.parse_not())
        return a

    def parse_not(self):
        if self.tok.is_kw('NOT'):
            line = self.next().line
            return N('un', line, op='NOT', a=self.parse_not())
        return self.parse_rel()

    def parse_rel(self):
        a = self.parse_add()
        while self.tok.kind == 'op' and self.tok.value in ('=', '<>', '<', '>', '<=', '>='):
            t = self.next()
            a = N('bin', t.line, op=t.value, a=a, b=self.parse_add())
        return a

    def parse_add(self):
        a = self.parse_mod()
        while self.tok.kind == 'op' and self.tok.value in ('+', '-'):
            t = self.next()
            a = N('bin', t.line, op=t.value, a=a, b=self.parse_mod())
        return a

    def parse_mod(self):
        a = self.parse_idiv()
        while self.tok.is_kw('MOD'):
            line = self.next().line
            a = N('bin', line, op='MOD', a=a, b=self.parse_idiv())
        return a

    def parse_idiv(self):
        a = self.parse_mul()
        while self.tok.kind == 'op' and self.tok.value == '\\':
            t = self.next()
            a = N('bin', t.line, op='\\', a=a, b=self.parse_mul())
        return a

    def parse_mul(self):
        a = self.parse_unary()
        while self.tok.kind == 'op' and self.tok.value in ('*', '/'):
            t = self.next()
            a = N('bin', t.line, op=t.value, a=a, b=self.parse_unary())
        return a

    def parse_unary(self):
        if self.tok.kind == 'op' and self.tok.value in ('-', '+'):
            t = self.next()
            e = self.parse_unary()
            if t.value == '+':
                return e
            if e.kind == 'num':
                v = -e.value
                typ = e.type
                if typ == 'l' and -32768 <= v <= 32767:
                    typ = 'i'
                return N('num', t.line, value=v, type=typ)
            return N('un', t.line, op='-', a=e)
        return self.parse_pow()

    def parse_pow(self):
        a = self.parse_atom()
        while self.tok.kind == 'op' and self.tok.value == '^':
            t = self.next()
            # exponent may have unary minus: 2 ^ -1
            if self.tok.kind == 'op' and self.tok.value in ('-', '+'):
                s = self.next()
                b = self.parse_atom()
                if s.value == '-':
                    b = N('un', s.line, op='-', a=b)
            else:
                b = self.parse_atom()
            a = N('bin', t.line, op='^', a=a, b=b)
        return a

    def parse_atom(self):
        t = self.tok
        if t.kind == 'num':
            self.next()
            return N('num', t.line, value=t.value, type=t.suffix)
        if t.kind == 'str':
            self.next()
            return N('str', t.line, value=t.value)
        if t.kind == 'op' and t.value == '(':
            self.next()
            e = self.parse_expr()
            self.expect_op(')')
            return N('paren', t.line, a=e)
        if t.kind == 'kw':
            return self.parse_builtin()
        if t.kind == 'id':
            self.next()
            node = N('ref', t.line, name=t.value, suffix=t.suffix, deftype=self.deftype_of(t.value), args=None, members=[])
            if self.tok.kind == 'op' and self.tok.value == '(':
                self.next()
                args = []
                if not (self.tok.kind == 'op' and self.tok.value == ')'):
                    while True:
                        args.append(self.parse_arg())
                        if not self.accept_op(','):
                            break
                self.expect_op(')')
                node.args = args
            while self.tok.kind == 'op' and self.tok.value == '.':
                self.next()
                m = self.next()
                node.members.append((m.value, m.suffix))
            return node
        self.error("Expected: expression")

    def parse_builtin(self):
        t = self.next()
        name = t.value
        if name not in BUILTIN_FUNCS:
            self.error(f"Syntax error: {name} is not a function")
        args = []
        if name in ('INPUT$',):
            self.expect_op('(')
            args.append(self.parse_expr())
            if self.accept_op(','):
                self.accept_op('#')
                args.append(self.parse_expr())
            self.expect_op(')')
            return N('builtin', t.line, name=name, args=args)
        if name in ('LBOUND', 'UBOUND'):
            self.expect_op('(')
            a = self.next()
            if a.kind != 'id':
                self.error("Expected: array name")
            args.append(N('arrayarg', a.line, name=a.value, suffix=a.suffix, deftype=self.deftype_of(a.value)))
            if self.accept_op('('):
                self.expect_op(')')
            if self.accept_op(','):
                args.append(self.parse_expr())
            self.expect_op(')')
            return N('builtin', t.line, name=name, args=args)
        if name in ('EOF', 'LOC', 'LOF', 'SEEK', 'FILEATTR'):
            self.expect_op('(')
            self.accept_op('#')
            args.append(self.parse_expr())
            if self.accept_op(','):
                args.append(self.parse_expr())
            self.expect_op(')')
            return N('builtin', t.line, name=name, args=args)
        if self.tok.kind == 'op' and self.tok.value == '(':
            self.next()
            if not (self.tok.kind == 'op' and self.tok.value == ')'):
                while True:
                    args.append(self.parse_expr())
                    if not self.accept_op(','):
                        break
            self.expect_op(')')
        info = BUILTIN_FUNCS[name]
        if len(args) < info[1] or len(args) > info[2]:
            if not (name == 'RND' and len(args) <= 1):
                self.error(f"Argument-count mismatch in {name}")
        if name == 'ERL':
            self.prog.uses_erl = True
        return N('builtin', t.line, name=name, args=args)


def split_data(raw):
    items = []
    cur = ''
    inq = False
    for ch in raw:
        if ch == '"':
            inq = not inq
            cur += ch
        elif ch == ',' and not inq:
            items.append(cur.strip(' \t'))
            cur = ''
        else:
            cur += ch
    items.append(cur.strip(' \t'))
    return items
