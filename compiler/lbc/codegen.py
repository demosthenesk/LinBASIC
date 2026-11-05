# LinBASIC compiler - semantic analysis and C code generation
# Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later.
import re
from .lexer import QBError, SUFFIX_TYPE
from .parser import N, BUILTIN_FUNCS

RANK = {'i': 1, 'l': 2, 's': 3, 'd': 4}
CT = {'i': 'qb_i16', 'l': 'qb_i32', 's': 'float', 'd': 'double', '$': 'qbs'}
TCHAR = {'i': 'i', 'l': 'l', 's': 's', 'd': 'd', '$': 'S'}


def is_str(t):
    return t == '$' or (isinstance(t, tuple) and t[0] == 'fs')


def is_fs(t):
    return isinstance(t, tuple) and t[0] == 'fs'


def is_udt(t):
    return isinstance(t, tuple) and t[0] == 'udt'


def is_num(t):
    return t in RANK


def tname(t):
    if t in ('i', 'l', 's', 'd', '$'):
        return {'i': 'INTEGER', 'l': 'LONG', 's': 'SINGLE', 'd': 'DOUBLE', '$': 'STRING'}[t]
    if is_fs(t):
        return f'STRING * {t[1]}'
    if is_udt(t):
        return t[1]
    return str(t)


def cident(name):
    s = name.upper().replace('.', '_d_')
    return re.sub(r'[^A-Z0-9_]', '_', s)


def c_string_literal(s):
    """QB string (chars 0..255) -> C string literal with byte escapes."""
    out = ['"']
    prev_hex = False
    for ch in s:
        b = ord(ch) & 0xFF
        if b == 34:
            out.append('\\"'); prev_hex = False
        elif b == 92:
            out.append('\\\\'); prev_hex = False
        elif 32 <= b < 127 and not (prev_hex and ch in '0123456789abcdefABCDEF') and ch != '?':
            out.append(ch); prev_hex = False
        else:
            out.append('\\%03o' % b); prev_hex = False
    out.append('"')
    return ''.join(out)


class E:
    """Generated expression."""
    __slots__ = ('code', 't', 'lv', 'addr', 'fsbuf', 'fslen', 'var', 'cheap')

    def __init__(self, code, t, lv=False, addr=None, fsbuf=None, fslen=None, var=None, cheap=False):
        self.code = code
        self.t = t
        self.lv = lv
        self.addr = addr
        self.fsbuf = fsbuf
        self.fslen = fslen
        self.var = var
        self.cheap = cheap


class Var:
    def __init__(self, name, t, cname, isarr=False, ptr=False, static=False, shared=False, kind='global', ndims=None):
        self.name = name
        self.t = t
        self.cname = cname
        self.isarr = isarr
        self.ptr = ptr
        self.static = static
        self.shared = shared
        self.kind = kind          # global / local / param
        self.ndims = ndims
        self.dimmed = False
        self.implicit = False

    @property
    def ref(self):
        """C lvalue of the variable storage."""
        return f'(*{self.cname})' if self.ptr else self.cname

    @property
    def aptr(self):
        return self.cname if self.ptr else f'&{self.cname}'


class Scope:
    def __init__(self, kind, name='MODULE', parent=None, proc=None):
        self.kind = kind          # module / proc / deffn
        self.name = name
        self.parent = parent
        self.proc = proc
        self.vars = {}            # (NAME, typekey) -> Var
        self.asvars = {}          # NAME -> Var  (declared AS type)
        self.arrays = {}
        self.asarrays = {}
        self.consts = {}          # NAME -> (code, type)
        self.labels = {}
        self.locals_decl = []     # C declarations
        self.cleanup = []
        self.uses_gosub = False
        self.implicit_arrays = []
        self.static_all = False


def tkey(t):
    if isinstance(t, tuple):
        return t[0] + ':' + str(t[1])
    return t


class CodeGen:
    def __init__(self, prog, modname='MAIN', options=None):
        self.prog = prog
        self.modname = modname
        self.opts = options or {}
        self.out = []
        self.globals = []
        self.protos = []
        self.funcs = []
        self.types_c = []
        self.udts = {}            # NAME -> list of (field, t, cname)
        self.procs = {}           # NAME -> proc node
        self.deffns = {}
        self.module = Scope('module')
        self.scope = self.module
        self.tmpn = 0
        self.lbln = 0
        self.loops = []           # stack of (kind, exit_label, cont_label)
        self.handler_ids = {}
        self.resume_ids = {}
        self.event_ids = {}
        self.data_labels = {}
        self.uses_error = prog.uses_error
        self.uses_events = prog.uses_events
        self.cur_line = 0
        self.stmt_tmp = False
        self.copy_strings = False
        self.common_vars = []
        self.warnings = []

    # ---- errors --------------------------------------------------------------
    def err(self, msg, node=None):
        line = node.line if node is not None and hasattr(node, 'line') else self.cur_line
        raise QBError(msg, line, 1, self.modname)

    def newtmp(self, prefix='t'):
        self.tmpn += 1
        return f'__{prefix}{self.tmpn}'

    def newlbl(self, prefix='L'):
        self.lbln += 1
        return f'__{prefix}{self.lbln}'

    def emit(self, s):
        self.out.append(s)

    # ---- types -----------------------------------------------------------------
    def resolve_type(self, ty):
        """Parser type spec -> internal type."""
        if ty is None:
            return None
        if isinstance(ty, str):
            if ty == 'any':
                return 'any'
            return ty
        if ty[0] == 'fixed':
            n = self.const_int(ty[1])
            if n < 1 or n > 32767:
                self.err("Illegal fixed-length string length")
            return ('fs', n)
        if ty[0] == 'udt':
            if ty[1] not in self.prog.types:
                self.err(f"Type not defined: {ty[1]}")
            return ('udt', ty[1])
        return ty

    def ctype(self, t):
        if t in CT:
            return CT[t]
        if is_udt(t):
            return f'struct T_{cident(t[1])}'
        if is_fs(t):
            return 'char'
        return 'qb_i16'

    def tsize(self, t):
        if t in ('i',):
            return 2
        if t in ('l', 's'):
            return 4
        if t == 'd':
            return 8
        if t == '$':
            return 4
        if is_fs(t):
            return t[1]
        if is_udt(t):
            return f'(qb_i32)sizeof(struct T_{cident(t[1])})'
        return 2

    def decl(self, t, cname, init=True, static=False):
        st = 'static ' if static else ''
        if is_fs(t):
            return f'{st}char {cname}[{t[1]}];'
        if t == '$':
            return f'{st}qbs {cname}' + (' = {0, 0, 0};' if init else ';')
        if is_udt(t):
            return f'{st}struct T_{cident(t[1])} {cname}' + (' = {0};' if init else ';')
        return f'{st}{CT[t]} {cname}' + (' = 0;' if init else ';')

    def gen_types(self):
        out = ['#pragma pack(push, 1)']
        for name in self.prog.type_order:
            fields = []
            for fname, fty in self.prog.types[name]:
                t = self.resolve_type(fty)
                fields.append((fname, t, 'f_' + cident(fname)))
            self.udts[name] = fields
        for name in self.prog.type_order:
            out.append(f'struct T_{cident(name)} {{')
            for fname, t, cn in self.udts[name]:
                if is_fs(t):
                    out.append(f'    char {cn}[{t[1]}];')
                elif is_udt(t):
                    out.append(f'    struct T_{cident(t[1])} {cn};')
                elif t == '$':
                    self.err("Variable-length strings not allowed in TYPE")
                else:
                    out.append(f'    {CT[t]} {cn};')
            out.append('};')
        out.append('#pragma pack(pop)')
        self.types_c = out

    # ---- constant evaluation ------------------------------------------------------
    def const_int(self, e):
        v = self.const_value(e)
        if v is None:
            self.err("Invalid constant")
        return int(round(v))

    def const_value(self, e):
        if e.kind == 'num':
            return e.value
        if e.kind == 'paren':
            return self.const_value(e.a)
        if e.kind == 'un' and e.op == '-':
            v = self.const_value(e.a)
            return None if v is None else -v
        if e.kind == 'un' and e.op == 'NOT':
            v = self.const_value(e.a)
            return None if v is None or isinstance(v, str) else ~int(round(v))
        if e.kind == 'ref' and e.args is None and not e.members:
            c = self.lookup_const(e.name)
            if c is not None and c[2] is not None:
                return c[2]
        if e.kind == 'bin':
            a = self.const_value(e.a)
            b = self.const_value(e.b)
            if a is None or b is None or isinstance(a, str) or isinstance(b, str):
                return None
            try:
                if e.op == '+': return a + b
                if e.op == '-': return a - b
                if e.op == '*': return a * b
                if e.op == '/': return a / b
                if e.op == '\\': return int(a) // int(b) if b else None
                if e.op == 'MOD': return int(a) % int(b) if b else None
                if e.op == '^': return a ** b
                if e.op == 'AND': return int(round(a)) & int(round(b))
                if e.op == 'OR': return int(round(a)) | int(round(b))
                if e.op == 'XOR': return int(round(a)) ^ int(round(b))
                if e.op == 'EQV': return ~(int(round(a)) ^ int(round(b)))
                if e.op == 'IMP': return (~int(round(a))) | int(round(b))
                if e.op == '=': return -1 if a == b else 0
                if e.op == '<>': return -1 if a != b else 0
                if e.op == '<': return -1 if a < b else 0
                if e.op == '>': return -1 if a > b else 0
                if e.op == '<=': return -1 if a <= b else 0
                if e.op == '>=': return -1 if a >= b else 0
            except Exception:
                return None
        return None

    def lookup_const(self, name):
        name = name.upper()
        s = self.scope
        while s:
            if name in s.consts:
                return s.consts[name]
            s = s.parent
        if name in self.module.consts:
            return self.module.consts[name]
        return None

    # ---- variables ------------------------------------------------------------------
    def var_cname(self, name, t, kind, isarr=False):
        base = ('a_' if isarr else 'v_') + cident(name) + '_' + (TCHAR.get(t, 'U') if not isinstance(t, tuple) else ('F' if is_fs(t) else 'U'))
        if kind == 'local':
            return base
        if kind == 'static':
            return f'{base}__{cident(self.scope.name)}'
        return 'g' + base

    def ref_type(self, ref):
        if ref.suffix:
            return SUFFIX_TYPE[ref.suffix]
        return ref.deftype

    def find_var(self, name, t_explicit, deftype, arrays=False):
        """Find an existing variable visible from the current scope."""
        name = name.upper()
        scopes = []
        s = self.scope
        scopes.append((s, False))
        if s.kind == 'deffn':
            scopes.append((self.module, False))
        elif s.kind == 'proc':
            scopes.append((self.module, True))
        for sc, need_shared in scopes:
            asd = sc.asarrays if arrays else sc.asvars
            dd = sc.arrays if arrays else sc.vars
            if name in asd:
                v = asd[name]
                if not need_shared or v.shared:
                    if t_explicit is None or self.same_base(v.t, t_explicit):
                        return v
            t = t_explicit if t_explicit else deftype
            k = (name, tkey(t))
            if k in dd:
                v = dd[k]
                if not need_shared or v.shared:
                    return v
            if t_explicit is None and not need_shared:
                pass
        return None

    def same_base(self, vt, t):
        if t == '$':
            return is_str(vt)
        return vt == t

    def get_var(self, ref, create=True):
        name = ref.name.upper()
        texp = SUFFIX_TYPE[ref.suffix] if ref.suffix else None
        v = self.find_var(name, texp, ref.deftype)
        if v or not create:
            return v
        t = texp or ref.deftype
        return self.new_var(name, t, self.scope)

    def new_var(self, name, t, scope, isarr=False, shared=False, static=False, asdecl=False, ndims=None):
        name = name.upper()
        if scope.kind == 'module':
            kind = 'global'
        elif static or scope.static_all:
            kind = 'static'
        else:
            kind = 'local'
        cn = self.var_cname(name, t, kind, isarr)
        # avoid collisions between AS-declared and suffix variables of different types
        if asdecl and is_udt(t):
            cn = cn + '_' + cident(t[1])
        v = Var(name, t, cn, isarr=isarr, shared=shared, static=(kind == 'static'), kind='global' if kind == 'global' else 'local', ndims=ndims)
        if isarr:
            if asdecl:
                scope.asarrays[name] = v
            scope.arrays[(name, tkey(t))] = v
            d = f'qbarr {cn} = {{0}};' if kind != 'static' else f'static qbarr {cn} = {{0}};'
        else:
            if asdecl:
                scope.asvars[name] = v
            scope.vars[(name, tkey(t))] = v
            d = self.decl(t, cn, static=(kind == 'static'))
        if kind == 'global':
            self.globals.append('static ' + d if not d.startswith('static') else d)
        elif kind == 'static':
            self.globals.append(d)
        else:
            scope.locals_decl.append(d)
            if isarr:
                scope.cleanup.append(f'qb_afree(&{cn});')
            elif t == '$':
                scope.cleanup.append(f'qb_sfree(&{cn});')
            elif is_fs(t):
                pass
        if is_fs(t) and kind == 'local':
            scope.locals_decl.append(f'memset({cn}, 0, {t[1]});')
        return v

    def get_array(self, name, suffix, deftype, nidx=None, create=True, node=None):
        name = name.upper()
        texp = SUFFIX_TYPE[suffix] if suffix else None
        v = self.find_var(name, texp, deftype, arrays=True)
        if v:
            return v
        if not create:
            return None
        t = texp or deftype
        # implicit array: dimensioned 0..10 in each dimension at scope start
        v = self.new_var(name, t, self.scope, isarr=True, ndims=nidx)
        v.implicit = True
        self.scope.implicit_arrays.append((v, nidx or 1))
        return v

    # ---- expressions ------------------------------------------------------------------
    def conv(self, e, t, node=None):
        """Convert expression to type t; returns C code."""
        if t == 'any':
            return e.code
        if is_str(t):
            if not is_str(e.t):
                self.err("Type mismatch", node)
            return e.code
        if not is_num(e.t):
            self.err("Type mismatch", node)
        if e.t == t:
            return e.code
        if t == 'i':
            if e.t == 'l':
                return f'qb_ci16({e.code})'
            return f'qb_cint({e.code})'
        if t == 'l':
            if e.t == 'i':
                return f'(qb_i32)({e.code})'
            return f'qb_clng({e.code})'
        if t == 's':
            if e.t == 'd':
                return f'qb_csng({e.code})'
            return f'(float)({e.code})'
        if t == 'd':
            return f'(double)({e.code})'
        return e.code

    def num(self, e, node=None):
        if not is_num(e.t):
            self.err("Type mismatch", node)
        return e

    def sval(self, e, node=None):
        """String expression -> qbs value code."""
        if is_fs(e.t):
            return E(f'qb_fsget({e.fsbuf}, {e.fslen})', '$')
        if e.t != '$':
            self.err("Type mismatch", node)
        return e

    def intval(self, e, node=None, want=None):
        """For integer operators: returns (code, type 'i' or 'l')."""
        self.num(e, node)
        if e.t == 'i':
            return e.code, 'i'
        if e.t == 'l':
            return e.code, 'l'
        if want == 'i':
            return f'qb_cint({e.code})', 'i'
        # floats: QB rounds to INTEGER if it fits, else LONG
        return f'qb_clng({e.code})', 'l'

    def gen_expr(self, e):
        k = e.kind
        if k == 'num':
            t = e.type
            v = e.value
            if t in ('i', 'l'):
                return E(str(int(v)) if v != -2147483648 else '(-2147483647-1)', t, cheap=True)
            if t == 's':
                s = repr(float(v))
                if 'e' not in s and '.' not in s:
                    s += '.0'
                return E(s + 'f', 's', cheap=True)
            s = repr(float(v))
            if 'inf' in s:
                s = '1.7976931348623157e308'
            return E(s, 'd', cheap=True)
        if k == 'str':
            return E(f'qb_slit({c_string_literal(e.value)}, {len(e.value)})', '$', cheap=True)
        if k == 'paren':
            r = self.gen_expr(e.a)
            if is_fs(r.t):
                r = self.sval(r)
            return E(f'({r.code})', r.t)
        if k == 'un':
            if e.op == '-':
                a = self.num(self.gen_expr(e.a), e)
                if a.t == 'i':
                    return E(f'qb_ci16(-(qb_i32)({a.code}))', 'i')
                if a.t == 'l':
                    return E(f'qb_ci32(-(qb_i64)({a.code}))', 'l')
                return E(f'(-({a.code}))', a.t)
            if e.op == 'NOT':
                c, t = self.intval(self.gen_expr(e.a), e)
                return E(f'(({CT[t]})~({c}))', t)
        if k == 'bin':
            return self.gen_bin(e)
        if k == 'ref':
            return self.gen_ref(e)
        if k == 'builtin':
            return self.gen_builtin(e)
        if k == 'arrayarg':
            self.err("Array used without subscripts", e)
        self.err("Expression not supported", e)

    def gen_bin(self, e):
        op = e.op
        a = self.gen_expr(e.a)
        b = self.gen_expr(e.b)
        if op in ('=', '<>', '<', '>', '<=', '>='):
            cop = {'=': '==', '<>': '!='}.get(op, op)
            if is_str(a.t) or is_str(b.t):
                if not (is_str(a.t) and is_str(b.t)):
                    self.err("Type mismatch", e)
                sa, sb = self.sval(a), self.sval(b)
                return E(f'(qb_i16)-(qb_scmp({sa.code}, {sb.code}) {cop} 0)', 'i')
            t = self.promote(a.t, b.t)
            return E(f'(qb_i16)-(({self.conv(a, t)}) {cop} ({self.conv(b, t)}))', 'i')
        if op == '+' and (is_str(a.t) or is_str(b.t)):
            if not (is_str(a.t) and is_str(b.t)):
                self.err("Type mismatch", e)
            self.stmt_tmp = True
            return E(f'qb_sadd({self.sval(a).code}, {self.sval(b).code})', '$')
        self.num(a, e); self.num(b, e)
        if op in ('+', '-', '*'):
            t = self.promote(a.t, b.t)
            ca, cb = self.conv(a, t), self.conv(b, t)
            if t == 'i':
                return E(f'qb_ci16((qb_i32)({ca}) {op} (qb_i32)({cb}))', 'i')
            if t == 'l':
                return E(f'qb_ci32((qb_i64)({ca}) {op} (qb_i64)({cb}))', 'l')
            return E(f'(({ca}) {op} ({cb}))', t)
        if op == '/':
            t = 'd' if (a.t in ('d', 'l') or b.t in ('d', 'l')) else 's'
            if t == 's':
                return E(f'qb_fdivs({self.conv(a, "s")}, {self.conv(b, "s")})', 's')
            return E(f'qb_fdiv({self.conv(a, "d")}, {self.conv(b, "d")})', 'd')
        if op == '\\' or op == 'MOD':
            ca, ta = self.intval(a, e)
            cb, tb = self.intval(b, e)
            t = 'l' if 'l' in (ta, tb) else 'i'
            fn = 'qb_idiv' if op == '\\' else 'qb_imod'
            if t == 'i':
                return E(f'(qb_i16){fn}({ca}, {cb})', 'i')
            return E(f'{fn}({ca}, {cb})', 'l')
        if op == '^':
            t = 'd' if 'd' in (a.t, b.t) else 's'
            if t == 's':
                return E(f'(float)qb_pow({self.conv(a, "d")}, {self.conv(b, "d")})', 's')
            return E(f'qb_pow({self.conv(a, "d")}, {self.conv(b, "d")})', 'd')
        if op in ('AND', 'OR', 'XOR', 'EQV', 'IMP'):
            ca, ta = self.intval(a, e)
            cb, tb = self.intval(b, e)
            t = 'l' if 'l' in (ta, tb) else 'i'
            ct = CT[t]
            if op == 'AND':
                code = f'(({ct})(({ct})({ca}) & ({ct})({cb})))'
            elif op == 'OR':
                code = f'(({ct})(({ct})({ca}) | ({ct})({cb})))'
            elif op == 'XOR':
                code = f'(({ct})(({ct})({ca}) ^ ({ct})({cb})))'
            elif op == 'EQV':
                code = f'(({ct})~(({ct})({ca}) ^ ({ct})({cb})))'
            else:
                code = f'(({ct})(~({ct})({ca}) | ({ct})({cb})))'
            return E(code, t)
        self.err(f"Operator {op} not supported", e)

    def promote(self, ta, tb):
        return ta if RANK[ta] >= RANK[tb] else tb

    # ---- references: variables, arrays, members, function calls -------------------
    def split_dotted(self, ref):
        """'a.b.c' -> if 'a' is a record variable return ('a', ['b','c'])."""
        if '.' not in ref.name:
            return None
        parts = ref.name.split('.')
        base = parts[0]
        # record variable or record array?
        if ref.args is None:
            v = self.find_var(base.upper(), None, ref.deftype)
            if v and is_udt(v.t):
                return base, parts[1:]
        else:
            v = self.find_var(base.upper(), None, ref.deftype, arrays=True)
            if v and is_udt(v.t):
                return base, parts[1:]
        return None

    def member_access(self, base_code, t, members, node):
        code = base_code
        for m in members:
            mname = m[0] if isinstance(m, tuple) else m
            if not is_udt(t):
                self.err("Element not defined", node)
            fields = self.udts[t[1]]
            for fname, ft, cn in fields:
                if fname == mname.upper():
                    code = f'{code}.{cn}'
                    t = ft
                    break
            else:
                self.err(f"Element not defined: {mname}", node)
        return code, t

    def lv_from_storage(self, code, t, var=None):
        if is_fs(t):
            return E(f'qb_fsget({code}, {t[1]})', t, lv=True, addr=code, fsbuf=code, fslen=t[1], var=var)
        return E(code, t, lv=True, addr=f'&{code}', var=var)

    def gen_ref(self, ref, as_lvalue=False):
        name = ref.name.upper()
        members = list(ref.members)
        dotted = self.split_dotted(ref)
        if dotted:
            base, extra = dotted
            members = [(x, None) for x in extra] + members
            name = base.upper()
            ref = N('ref', ref.line, name=base, suffix=None if extra else ref.suffix, deftype=ref.deftype, args=ref.args, members=[])
        # function return value inside its own FUNCTION
        proc = self.scope.proc if self.scope.kind == 'proc' else None
        if ref.args is None and not members:
            if proc is not None and proc.what == 'FUNCTION' and name == proc.name and self.suffix_matches(ref, proc):
                rt = self.proc_rtype(proc)
                if as_lvalue or proc.params:
                    return E('__ret', rt, lv=True, addr='&__ret')
                return self.call_user(proc, [], ref)
            if self.scope.kind == 'deffn' and name == self.scope.name and not as_lvalue:
                pass
            if self.scope.kind == 'deffn' and name == self.scope.name:
                return E('__ret', self.scope.rtype, lv=True, addr='&__ret')
            # constant?
            if not as_lvalue:
                c = self.lookup_const(name)
                if c is not None:
                    return E(c[0], c[1], cheap=True)
                # function without arguments
                if name in self.procs and self.procs[name].what == 'FUNCTION' and self.suffix_matches(ref, self.procs[name]):
                    return self.call_user(self.procs[name], [], ref)
                if name.startswith('FN') and name in self.deffns:
                    return self.call_deffn(self.deffns[name], [], ref)
            v = self.get_var(ref)
            return self.lv_from_storage(v.ref, v.t, v)
        if ref.args is not None and not members and not as_lvalue:
            if name in self.procs and self.procs[name].what == 'FUNCTION' and self.suffix_matches(ref, self.procs[name]):
                return self.call_user(self.procs[name], ref.args, ref)
            if name.startswith('FN') and name in self.deffns:
                return self.call_deffn(self.deffns[name], ref.args, ref)
        if ref.args is not None and as_lvalue and proc is not None and proc.what == 'FUNCTION' and name == proc.name:
            self.err("Function name used as array", ref)
        if ref.args is not None:
            arr = self.get_array(name, ref.suffix, ref.deftype, len(ref.args), node=ref)
            idx = [self.conv(self.num(self.gen_expr(a), ref), 'l') if a.kind != 'arrayarg' else self.err("Syntax error", ref) for a in ref.args]
            ap = arr.aptr
            if len(idx) == 1:
                off = f'qb_aoff1({ap}, {idx[0]})'
            elif len(idx) == 2:
                off = f'qb_aoff2({ap}, {idx[0]}, {idx[1]})'
            else:
                off = f'qb_aoff({ap}, {len(idx)}, {", ".join(idx)})'
            if is_fs(arr.t):
                code = f'(({ap})->data + (qb_i32)({off}) * {arr.t[1]})'
                if members:
                    self.err("Element not defined", ref)
                return E(f'qb_fsget({code}, {arr.t[1]})', arr.t, lv=True, addr=code, fsbuf=code, fslen=arr.t[1], var=arr)
            code = f'QB_AE({ap}, {self.ctype(arr.t)}, {off})'
            t = arr.t
            if members:
                code, t = self.member_access(code, t, members, ref)
            return self.lv_from_storage(code, t, arr)
        v = self.get_var(ref)
        code, t = self.member_access(v.ref, v.t, members, ref)
        return self.lv_from_storage(code, t, v)

    def suffix_matches(self, ref, proc):
        if ref.suffix is None or proc.suffix is None:
            return True
        return ref.suffix == proc.suffix

    def proc_rtype(self, proc):
        if proc.suffix:
            return SUFFIX_TYPE[proc.suffix]
        return proc.deftype

    def param_types(self, proc):
        out = []
        for p in proc.params:
            if p.astype is not None:
                t = self.resolve_type(p.astype)
            elif p.suffix:
                t = SUFFIX_TYPE[p.suffix]
            else:
                t = p.deftype
            out.append((p, t))
        return out

    def gen_args(self, proc, args, node):
        ptypes = self.param_types(proc)
        if len(args) != len(ptypes):
            self.err(f"Argument-count mismatch calling {proc.name}", node)
        out = []
        for (p, t), a in zip(ptypes, args):
            if p.isarr:
                if a.kind != 'arrayarg':
                    self.err("Parameter type mismatch (array expected)", node)
                arr = self.get_array(a.name, a.suffix, a.deftype, None, node=node)
                out.append(arr.aptr)
                continue
            if a.kind == 'arrayarg':
                self.err("Parameter type mismatch", node)
            if t == 'any':
                ex = self.gen_expr(a)
                out.append(ex.addr if ex.lv else f'&({self.ctype(ex.t)}){{{ex.code}}}')
                continue
            if a.kind in ('ref',) and not self.is_function_ref(a):
                ex = self.gen_ref(a)
                if ex.lv and (ex.t == t or (t == '$' and ex.t == '$')) and not is_fs(ex.t):
                    out.append(ex.addr)
                    continue
                if is_udt(t):
                    if ex.t != t:
                        self.err("Parameter type mismatch", node)
                    out.append(ex.addr)
                    continue
            else:
                ex = self.gen_expr(a)
            if is_udt(t):
                self.err("Parameter type mismatch", node)
            if t == '$':
                sv = self.sval(ex, node)
                out.append(f'qb_sbox({sv.code})')
            else:
                out.append(f'&({CT[t]}){{{self.conv(ex, t, node)}}}')
        return out

    def is_function_ref(self, a):
        name = a.name.upper()
        if name in self.procs and self.procs[name].what == 'FUNCTION':
            return True
        if name.startswith('FN') and name in self.deffns:
            return True
        if a.args is None and self.lookup_const(name) is not None:
            return True
        return False

    def call_user(self, proc, args, node):
        self.copy_strings = True
        cargs = self.gen_args(proc, args, node)
        rt = self.proc_rtype(proc)
        if rt == '$':
            self.stmt_tmp = True
        return E(f'F_{cident(proc.name)}({", ".join(cargs)})', rt)

    def call_deffn(self, fn, args, node):
        self.copy_strings = True
        if len(args) != len(fn.params):
            self.err("Argument-count mismatch", node)
        cargs = []
        for p, a in zip(fn.params, args):
            t = self.resolve_type(p.astype) if p.astype else (SUFFIX_TYPE[p.suffix] if p.suffix else p.deftype)
            ex = self.gen_expr(a)
            if t == '$':
                cargs.append(self.sval(ex, node).code)
            else:
                cargs.append(self.conv(ex, t, node))
        rt = SUFFIX_TYPE[fn.suffix] if fn.suffix else fn.deftype
        if rt == '$':
            self.stmt_tmp = True
        return E(f'FN_{cident(fn.name)}({", ".join(cargs)})', rt)

    # ---- builtin functions ---------------------------------------------------------------
    def gen_builtin(self, e):
        n = e.name
        a = e.args
        g = self.gen_expr
        S = lambda x: self.sval(g(x), e).code
        D = lambda x: self.conv(self.num(g(x), e), 'd', e)
        L = lambda x: self.conv(self.num(g(x), e), 'l', e)
        I = lambda x: self.conv(self.num(g(x), e), 'i', e)
        if BUILTIN_FUNCS[n][0] == '$':
            self.stmt_tmp = True
        if n == 'ABS':
            x = self.num(g(a[0]), e)
            if x.t == 'i':
                return E(f'qb_ci16(abs((int){x.code}))' if False else f'qb_ci16((qb_i32)({x.code}) < 0 ? -(qb_i32)({x.code}) : (qb_i32)({x.code}))', 'i')
            if x.t == 'l':
                return E(f'qb_ci32((qb_i64)({x.code}) < 0 ? -(qb_i64)({x.code}) : (qb_i64)({x.code}))', 'l')
            return E(f'({x.t == "s" and "(float)" or ""}qb_abs({x.code}))', x.t)
        if n == 'ASC': return E(f'(qb_i16)qb_asc({S(a[0])})', 'i')
        if n in ('ATN', 'COS', 'SIN', 'TAN', 'EXP', 'LOG', 'SQR'):
            x = self.num(g(a[0]), e)
            fn = {'ATN': 'qb_atn', 'COS': 'qb_cos', 'SIN': 'qb_sin', 'TAN': 'qb_tan', 'EXP': 'qb_exp', 'LOG': 'qb_log', 'SQR': 'qb_sqr'}[n]
            if x.t == 'd':
                return E(f'{fn}({x.code})', 'd')
            return E(f'(float){fn}((double)({x.code}))', 's')
        if n == 'CDBL': return E(D(a[0]), 'd')
        if n == 'CSNG': return E(self.conv(self.num(g(a[0]), e), 's', e), 's')
        if n == 'CINT': return E(f'qb_cint({D(a[0])})', 'i')
        if n == 'CLNG': return E(f'qb_clng({D(a[0])})', 'l')
        if n == 'CHR$': return E(f'qb_chr({L(a[0])})', '$')
        if n == 'CSRLIN': return E('(qb_i16)qb_csrlin()', 'i')
        if n in ('CVI', 'CVL', 'CVS', 'CVD', 'CVSMBF', 'CVDMBF'):
            t = {'CVI': 'i', 'CVL': 'l', 'CVS': 's', 'CVD': 'd', 'CVSMBF': 's', 'CVDMBF': 'd'}[n]
            return E(f'qb_{n.lower()}({S(a[0])})', t)
        if n in ('MKI$', 'MKL$', 'MKS$', 'MKD$', 'MKSMBF$', 'MKDMBF$'):
            t = {'MKI$': 'l', 'MKL$': 'l', 'MKS$': 's', 'MKD$': 'd', 'MKSMBF$': 's', 'MKDMBF$': 'd'}[n]
            x = self.conv(self.num(g(a[0]), e), t, e)
            return E(f'qb_{n[:-1].lower()}({x})', '$')
        if n == 'DATE$': return E('qb_date()', '$')
        if n == 'TIME$': return E('qb_time()', '$')
        if n == 'ENVIRON$':
            x = g(a[0])
            if is_str(x.t):
                return E(f'qb_environ_s({self.sval(x).code})', '$')
            return E(f'qb_environ_n({self.conv(x, "l")})', '$')
        if n == 'EOF': return E(f'(qb_i16)qb_eof({L(a[0])})', 'i')
        if n == 'ERDEV': return E('(qb_i16)qb_erdev()', 'i')
        if n == 'ERDEV$': return E('qb_erdev_s()', '$')
        if n == 'ERL': return E('qb_erl', 'l')
        if n == 'ERR': return E('(qb_i16)qb_err', 'i')
        if n == 'FILEATTR': return E(f'qb_fileattr({L(a[0])}, {L(a[1])})', 'l')
        if n in ('FIX', 'INT'):
            x = self.num(g(a[0]), e)
            if x.t in ('i', 'l'):
                return x
            fn = 'qb_fix' if n == 'FIX' else 'qb_int'
            if x.t == 's':
                return E(f'(float){fn}({x.code})', 's')
            return E(f'{fn}({x.code})', 'd')
        if n == 'FRE':
            x = g(a[0])
            return E('(qb_i32)qb_fre(0)', 'l')
        if n == 'FREEFILE': return E('(qb_i16)qb_freefile()', 'i')
        if n == 'HEX$': return E(f'qb_hex({D(a[0])})', '$')
        if n == 'OCT$': return E(f'qb_oct({D(a[0])})', '$')
        if n == 'INKEY$': return E('qb_inkey()', '$')
        if n == 'INP': return E(f'(qb_i16)qb_inp({L(a[0])})', 'i')
        if n == 'INPUT$':
            fn = L(a[1]) if len(a) > 1 else 'QB_NA'
            return E(f'qb_input_n({L(a[0])}, {fn})', '$')
        if n == 'INSTR':
            if len(a) == 3:
                return E(f'(qb_i16)qb_instr({L(a[0])}, {S(a[1])}, {S(a[2])})', 'i')
            return E(f'(qb_i16)qb_instr(QB_NA, {S(a[0])}, {S(a[1])})', 'i')
        if n == 'IOCTL$': return E(f'qb_ioctl_s({L(a[0])})', '$')
        if n in ('LBOUND', 'UBOUND'):
            arr = self.get_array(a[0].name, a[0].suffix, a[0].deftype, None, node=e)
            d = L(a[1]) if len(a) > 1 else 'QB_NA'
            return E(f'(qb_i16)qb_{n.lower()}({arr.aptr}, {d})', 'i')
        if n == 'LCASE$': return E(f'qb_lcase({S(a[0])})', '$')
        if n == 'UCASE$': return E(f'qb_ucase({S(a[0])})', '$')
        if n == 'LEFT$': return E(f'qb_left({S(a[0])}, {L(a[1])})', '$')
        if n == 'RIGHT$': return E(f'qb_right({S(a[0])}, {L(a[1])})', '$')
        if n == 'MID$':
            ln = L(a[2]) if len(a) > 2 else 'QB_NA'
            return E(f'qb_mid({S(a[0])}, {L(a[1])}, {ln})', '$')
        if n == 'LTRIM$': return E(f'qb_ltrim({S(a[0])})', '$')
        if n == 'RTRIM$': return E(f'qb_rtrim({S(a[0])})', '$')
        if n == 'LEN':
            x = a[0]
            if x.kind == 'ref':
                ex = self.gen_ref(x)
            else:
                ex = g(x)
            if is_fs(ex.t):
                return E(str(ex.t[1]), 'i')
            if ex.t == '$':
                return E(f'(qb_i16)({ex.code}).len' if ex.lv else f'(qb_i16)(({ex.code}).len)', 'i')
            if is_udt(ex.t):
                return E(f'(qb_i16){self.tsize(ex.t)}', 'i')
            return E(str(self.tsize(ex.t)), 'i')
        if n == 'LOC': return E(f'qb_loc({L(a[0])})', 'l')
        if n == 'LOF': return E(f'qb_lof({L(a[0])})', 'l')
        if n == 'SEEK': return E(f'qb_seek_fn({L(a[0])})', 'l')
        if n == 'LPOS': return E(f'(qb_i16)qb_lpos(0)', 'i')
        if n == 'POS': return E(f'(qb_i16)qb_pos(0)', 'i')
        if n == 'PEEK': return E(f'(qb_i16)qb_peek({L(a[0])})', 'i')
        if n == 'PEN': return E(f'(qb_i16)qb_pen({L(a[0])})', 'i')
        if n == 'PLAY': return E(f'(qb_i16)qb_play_fn({L(a[0])})', 'i')
        if n == 'PMAP': return E(f'(float)qb_pmap({D(a[0])}, {L(a[1])})', 's')
        if n == 'POINT':
            if len(a) == 2:
                return E(f'(qb_i16)qb_point({D(a[0])}, {D(a[1])})', 'i')
            return E(f'qb_point_n({L(a[0])})', 's')
        if n == 'RND':
            if a:
                return E(f'qb_rnd({self.conv(self.num(g(a[0]), e), "s", e)})', 's')
            return E('qb_rnd(1.0f)', 's')
        if n == 'SADD': return E(f'(qb_i16)qb_saddr({S(a[0])})', 'i')
        if n == 'SCREEN':
            fl = L(a[2]) if len(a) > 2 else 'QB_NA'
            return E(f'(qb_i16)qb_screen_fn({L(a[0])}, {L(a[1])}, {fl})', 'i')
        if n == 'SETMEM': return E(f'(qb_i32)qb_fre(0)', 'l')
        if n == 'SGN': return E(f'(qb_i16)qb_sgn({D(a[0])})', 'i')
        if n == 'SPACE$': return E(f'qb_space({L(a[0])})', '$')
        if n == 'STICK': return E(f'(qb_i16)qb_stick({L(a[0])})', 'i')
        if n == 'STRIG': return E(f'(qb_i16)qb_strig({L(a[0])})', 'i')
        if n == 'STR$':
            x = self.num(g(a[0]), e)
            if x.t in ('i', 'l'):
                return E(f'qb_str_i({x.code})', '$')
            if x.t == 's':
                return E(f'qb_str_f({x.code})', '$')
            return E(f'qb_str_d({x.code})', '$')
        if n == 'STRING$':
            x = g(a[1])
            if is_str(x.t):
                return E(f'qb_string_s({L(a[0])}, {self.sval(x).code})', '$')
            return E(f'qb_string_n({L(a[0])}, {self.conv(x, "l")})', '$')
        if n == 'TIMER': return E('qb_timer()', 's')
        if n == 'VAL': return E(f'qb_val({S(a[0])})', 'd')
        if n in ('VARPTR', 'VARSEG'):
            x = a[0]
            ex = self.gen_ref(x) if x.kind == 'ref' else g(x)
            addr = ex.addr if ex.lv else '0'
            return E(f'(qb_i16)qb_{n.lower()}((void *){addr})', 'i')
        if n == 'VARPTR$':
            x = g(a[0])
            if is_str(x.t):
                return E(f'qb_varptrs_str({self.sval(x).code})', '$')
            return E(f'qb_varptrs_num({self.conv(x, "d")})', '$')
        if n == 'COMMAND$': return E('qb_command()', '$')
        self.err(f"Function {n} not supported", e)

    # ---- statements ------------------------------------------------------------------------
    def gen_cond(self, expr):
        """Return C code evaluating to non-zero for true; may use temps."""
        self.stmt_tmp = False
        self.copy_strings = False
        ex = self.gen_expr(expr)
        if not is_num(ex.t):
            self.err("Type mismatch", expr)
        if self.stmt_tmp:
            v = self.newtmp('c')
            return f'({{ qb_i32 __m_ = qb_mark(); int {v} = ({ex.code}) != 0; qb_release(__m_); {v}; }})'
        return f'(({ex.code}) != 0)'

    def wrap_stmt(self, code_lines):
        """Wrap statement code with temporary-string release."""
        if self.stmt_tmp:
            self.emit('{ qb_i32 __m = qb_mark();')
            for c in code_lines:
                self.emit('  ' + c)
            self.emit('  qb_release(__m); }')
        else:
            for c in code_lines:
                self.emit(c)

    def gen_block(self, stmts):
        for st in stmts:
            self.gen_stmt(st)

    def err_check(self):
        if not self.uses_error:
            return
        if self.scope.kind == 'module':
            self.emit('if (qb_errpend | qb__unwinding) { int __r = qb__unwinding ? 3 : qb__handle(); if (__r == 1) goto *__rs; if (__r == 2) goto *__rn; goto __unwind; }')
        else:
            self.emit('if (qb_errpend | qb__unwinding) { int __r = qb__unwinding ? 3 : qb__handle(); if (__r == 1) goto *__rs; if (__r == 2) goto *__rn; goto __exit; }')

    def ev_check(self):
        if self.uses_events:
            self.emit('if (qb_evflag) qb__event();')

    def gen_stmt(self, st):
        self.cur_line = st.line
        k = st.kind
        if k == 'label':
            lab = self.label_c(st.name)
            self.emit(f'{lab}:;')
            if st.numeric and self.prog.uses_erl:
                try:
                    self.emit(f'qb__lnum = {int(st.name)};')
                except ValueError:
                    pass
            return
        if k in ('deftype', 'optionbase', 'declare', 'deffn_decl', 'nop', 'data'):
            return
        if k in ('if', 'for', 'do', 'select'):
            self.emit(f'qb_curline = {st.line};')
            getattr(self, 'st_' + k)(st)
            return
        self.stmt_tmp = False
        self.copy_strings = False
        if self.uses_error:
            s = self.newlbl('S')
            self.emit(f'{s}: __rs = &&{s}; __rn = &&{s}n;')
        self.emit(f'qb_curline = {st.line};')
        m = getattr(self, 'st_' + k, None)
        if m is None:
            self.err(f"Statement not supported: {k}", st)
        saved = self.out
        self.out = []
        m(st)
        body = self.out
        self.out = saved
        self.wrap_stmt(body)
        self.err_check()
        if self.uses_error:
            self.emit(f'{s}n:;')
        self.ev_check()

    def label_c(self, name):
        sc = self.scope
        return f'L_{cident(name)}'

    # ----- assignment -----
    def st_assign(self, st):
        lv = self.gen_ref(st.target, as_lvalue=True)
        ex = self.gen_expr(st.expr)
        self.assign(lv, ex, st)

    def assign(self, lv, ex, node):
        t = lv.t
        if is_fs(t):
            self.emit(f'qb_fsset({lv.fsbuf}, {lv.fslen}, {self.sval(ex, node).code});')
        elif t == '$':
            self.emit(f'qb_sset({lv.addr}, {self.sval(ex, node).code});')
        elif is_udt(t):
            if ex.t != t:
                self.err("Type mismatch", node)
            self.emit(f'memcpy({lv.addr}, {ex.addr}, sizeof({self.ctype(t)}));')
        else:
            self.emit(f'{lv.code} = {self.conv(ex, t, node)};')

    # ----- PRINT / WRITE -----
    def st_print(self, st):
        fn = '0'
        if st.lprint:
            fn = '-1'
        elif st.fileno is not None:
            fn = self.conv(self.num(self.gen_expr(st.fileno), st), 'l', st)
        self.emit(f'qb_pr_begin({fn});')
        items = st.items
        if st.using is not None:
            fmt = self.sval(self.gen_expr(st.using), st)
            self.stmt_tmp = True
            self.emit(f'qb_pu_begin({fmt.code});')
            newline = True
            for it in items:
                if it[0] in ('semi', 'comma'):
                    newline = False
                    continue
                newline = True
                if it[0] != 'expr':
                    continue
                ex = self.gen_expr(it[1])
                if is_str(ex.t):
                    self.emit(f'qb_pu_s({self.sval(ex).code});')
                else:
                    self.emit(f'qb_pu_d({self.conv(ex, "d")}, {1 if ex.t == "d" else 0});')
            if not items:
                newline = True
            self.emit(f'qb_pu_end({1 if newline else 0});')
            return
        newline = True
        for it in items:
            if it[0] == 'semi':
                newline = False
                continue
            if it[0] == 'comma':
                self.emit('qb_pr_comma();')
                newline = False
                continue
            newline = True
            if it[0] == 'tab':
                self.emit(f'qb_pr_tab({self.conv(self.num(self.gen_expr(it[1])), "l")});')
                newline = True
                continue
            if it[0] == 'spc':
                self.emit(f'qb_pr_spc({self.conv(self.num(self.gen_expr(it[1])), "l")});')
                continue
            ex = self.gen_expr(it[1])
            if is_str(ex.t):
                self.emit(f'qb_pr_s({self.sval(ex).code});')
            elif ex.t in ('i', 'l'):
                self.emit(f'qb_pr_i({ex.code});')
            elif ex.t == 's':
                self.emit(f'qb_pr_f({ex.code});')
            else:
                self.emit(f'qb_pr_d({ex.code});')
        if items and items[-1][0] in ('tab', 'spc'):
            newline = True
        if newline:
            self.emit('qb_pr_nl();')
        self.emit('qb_pr_end();')

    def st_write(self, st):
        fn = '0' if st.fileno is None else self.conv(self.num(self.gen_expr(st.fileno)), 'l')
        self.emit(f'qb_pr_begin({fn});')
        for it in st.items:
            ex = self.gen_expr(it)
            if is_str(ex.t):
                self.emit(f'qb_wr_s({self.sval(ex).code});')
            elif ex.t in ('i', 'l'):
                self.emit(f'qb_wr_i({ex.code});')
            elif ex.t == 's':
                self.emit(f'qb_wr_f({ex.code});')
            else:
                self.emit(f'qb_wr_d({ex.code});')
        self.emit('qb_wr_end();')

    # ----- INPUT -----
    def st_input(self, st):
        types = ''
        lvs = []
        for v in st.vars:
            lv = self.gen_ref(v, as_lvalue=True)
            lvs.append(lv)
            if is_str(lv.t):
                types += 's'
            elif lv.t in ('i',):
                types += 'i'
            elif lv.t == 'l':
                types += 'l'
            else:
                types += 'd'
        fn = '0' if st.fileno is None else self.conv(self.num(self.gen_expr(st.fileno)), 'l')
        prompt = f'qb_slit({c_string_literal(st.prompt)}, {len(st.prompt)})' if st.prompt is not None else 'qb_slit("", 0)'
        flags = (1 if st.semi else 0) | (2 if st.nq else 0)
        self.stmt_tmp = True
        self.emit(f'qb_in_begin({fn}, {prompt}, {flags}, "{types}");')
        for lv in lvs:
            t = lv.t
            if is_fs(t):
                self.emit(f'qb_in_fs({lv.fsbuf}, {lv.fslen});')
            elif t == '$':
                self.emit(f'qb_in_s({lv.addr});')
            elif t == 'i':
                self.emit(f'qb_in_i16({lv.addr});')
            elif t == 'l':
                self.emit(f'qb_in_i32({lv.addr});')
            elif t == 's':
                self.emit(f'qb_in_f({lv.addr});')
            elif t == 'd':
                self.emit(f'qb_in_d({lv.addr});')
            else:
                self.err("Type mismatch", st)
        self.emit('qb_in_end();')

    def st_lineinput(self, st):
        lv = self.gen_ref(st.var, as_lvalue=True)
        fn = '0' if st.fileno is None else self.conv(self.num(self.gen_expr(st.fileno)), 'l')
        prompt = f'qb_slit({c_string_literal(st.prompt)}, {len(st.prompt)})' if st.prompt is not None else 'qb_slit("", 0)'
        flags = 1 if st.semi else 0
        self.stmt_tmp = True
        if is_fs(lv.t):
            self.emit(f'qb_lineinput_fs({fn}, {prompt}, {flags}, {lv.fsbuf}, {lv.fslen});')
        elif lv.t == '$':
            self.emit(f'qb_lineinput({fn}, {prompt}, {flags}, {lv.addr});')
        else:
            self.err("Type mismatch", st)

    # ----- IF -----
    def st_if(self, st):
        c = self.gen_cond(st.cond)
        if self.uses_error:
            s = self.newlbl('S')
            self.emit(f'{s}: __rs = &&{s}; __rn = &&{s}n;')
        else:
            s = None
        if self.uses_error:
            tv = self.newtmp('if')
            self.emit(f'{{ int {tv} = {c};')
            self.err_check()
            self.emit(f'if ({tv}) {{')
        else:
            self.emit(f'if ({c}) {{')
        self.gen_block(st.then)
        self.emit('}')
        for cond, body in st.elifs:
            c2 = self.gen_cond(cond)
            self.emit(f'else if ({c2}) {{')
            self.gen_block(body)
            self.emit('}')
        if st.els is not None:
            self.emit('else {')
            self.gen_block(st.els)
            self.emit('}')
        if self.uses_error:
            self.emit('}')
        if s:
            self.emit(f'{s}n:;')

    # ----- FOR -----
    def st_for(self, st):
        var = self.gen_ref(st.var, as_lvalue=True)
        t = var.t
        if not is_num(t):
            self.err("Type mismatch", st)
        lim = self.newtmp('lim')
        stp = self.newtmp('stp')
        exitl = self.newlbl('FX')
        contl = self.newlbl('FC')
        ct = CT[t]
        self.stmt_tmp = False
        self.copy_strings = False
        start = self.conv(self.num(self.gen_expr(st.start)), t)
        end = self.conv(self.num(self.gen_expr(st.end)), t)
        step = self.conv(self.num(self.gen_expr(st.step)), t) if st.step is not None else ('1' if t in ('i', 'l') else '1.0')
        self.emit(f'{{ {ct} {lim}, {stp};')
        if self.stmt_tmp:
            self.emit(f'{{ qb_i32 __m = qb_mark(); {var.code} = {start}; {lim} = {end}; {stp} = {step}; qb_release(__m); }}')
        else:
            self.emit(f'{var.code} = {start}; {lim} = {end}; {stp} = {step};')
        self.err_check()
        self.emit(f'for (;;) {{')
        self.emit(f'if ({stp} >= 0 ? {var.code} > {lim} : {var.code} < {lim}) break;')
        self.loops.append(('FOR', exitl, contl))
        self.gen_block(st.body)
        self.loops.pop()
        self.emit(f'{contl}:;')
        if t == 'i':
            self.emit(f'{var.code} = qb_ci16((qb_i32){var.code} + {stp});')
        elif t == 'l':
            self.emit(f'{var.code} = qb_ci32((qb_i64){var.code} + {stp});')
        else:
            self.emit(f'{var.code} = {var.code} + {stp};')
        self.emit('}')
        self.emit(f'{exitl}:; }}')

    # ----- DO / WHILE -----
    def st_do(self, st):
        exitl = self.newlbl('DX')
        contl = self.newlbl('DC')
        self.emit('for (;;) {')
        if st.pre:
            kw, cond = st.pre
            c = self.gen_cond(cond)
            if kw == 'WHILE':
                self.emit(f'if (!{c}) break;')
            else:
                self.emit(f'if ({c}) break;')
            self.err_check()
        self.loops.append(('DO', exitl, contl))
        self.gen_block(st.body)
        self.loops.pop()
        self.emit(f'{contl}:;')
        if st.post:
            kw, cond = st.post
            c = self.gen_cond(cond)
            if kw == 'WHILE':
                self.emit(f'if (!{c}) break;')
            else:
                self.emit(f'if ({c}) break;')
            self.err_check()
        self.emit('}')
        self.emit(f'{exitl}:;')

    # ----- SELECT CASE -----
    def st_select(self, st):
        self.stmt_tmp = False
        self.copy_strings = True
        ex = self.gen_expr(st.expr)
        sv = self.newtmp('sel')
        isstr = is_str(ex.t)
        self.emit('{')
        if isstr:
            self.emit(f'qbs {sv} = {{0, 0, 0}};')
            self.emit(f'{{ qb_i32 __m = qb_mark(); qb_sset(&{sv}, {self.sval(ex).code}); qb_release(__m); }}')
            st_t = '$'
        else:
            st_t = ex.t
            if self.stmt_tmp:
                self.emit(f'{CT[st_t]} {sv}; {{ qb_i32 __m = qb_mark(); {sv} = {ex.code}; qb_release(__m); }}')
            else:
                self.emit(f'{CT[st_t]} {sv} = {ex.code};')
        self.err_check()
        selE = E(sv, st_t)
        first = True
        for tests, body in st.cases:
            conds = []
            self.stmt_tmp = False
            for tst in tests:
                if tst[0] == 'eq':
                    conds.append(self.case_cmp(selE, '=', tst[1], st))
                elif tst[0] == 'is':
                    conds.append(self.case_cmp(selE, tst[1], tst[2], st))
                else:
                    conds.append('(' + self.case_cmp(selE, '>=', tst[1], st) + ' && ' + self.case_cmp(selE, '<=', tst[2], st) + ')')
            c = ' || '.join(conds)
            if self.stmt_tmp:
                tv = self.newtmp('cs')
                c = f'({{ qb_i32 __m_ = qb_mark(); int {tv} = {c}; qb_release(__m_); {tv}; }})'
            self.emit(('if' if first else 'else if') + f' ({c}) {{')
            first = False
            self.gen_block(body)
            self.emit('}')
        if st.els is not None:
            if first:
                self.emit('{')
            else:
                self.emit('else {')
            self.gen_block(st.els)
            self.emit('}')
        if isstr:
            self.emit(f'qb_sfree(&{sv});')
        self.emit('}')

    def case_cmp(self, selE, op, expr, node):
        b = self.gen_expr(expr)
        cop = {'=': '==', '<>': '!='}.get(op, op)
        if is_str(selE.t):
            if not is_str(b.t):
                self.err("Type mismatch", node)
            return f'(qb_scmp({selE.code}, {self.sval(b).code}) {cop} 0)'
        if not is_num(b.t):
            self.err("Type mismatch", node)
        t = self.promote(selE.t, b.t)
        return f'(({self.conv(selE, t)}) {cop} ({self.conv(b, t)}))'

    # ----- jumps -----
    def st_goto(self, st):
        self.check_label(st.target, st)
        self.emit(f'goto {self.label_c(st.target)};')

    def st_gosub(self, st):
        self.check_label(st.target, st)
        self.scope.uses_gosub = True
        r = self.newlbl('R')
        self.emit(f'if (__gsp >= 512) qb_error(7); else {{ __gs[__gsp++] = &&{r}; goto {self.label_c(st.target)}; }} {r}:;')

    def st_return(self, st):
        self.scope.uses_gosub = True
        ev = ''
        if self.uses_events and self.scope.kind == 'module':
            ev = 'if (__entry >= 2000) return 4; '
        if st.target:
            self.check_label(st.target, st)
            self.emit(f'if (__gsp <= 0) {{ {ev}qb_error(3); }} else {{ __gsp--; goto {self.label_c(st.target)}; }}')
        else:
            self.emit(f'if (__gsp <= 0) {{ {ev}qb_error(3); }} else {{ __gsp--; goto *__gs[__gsp]; }}')

    def check_label(self, name, node):
        self.pending_labels.append((name, node, self.scope))

    def st_ongoto(self, st):
        ex = self.conv(self.num(self.gen_expr(st.expr)), 'l')
        v = self.newtmp('on')
        self.emit(f'{{ qb_i32 {v} = {ex};')
        self.emit(f'if ({v} < 0 || {v} > 255) qb_error(5);')
        if st.gosub:
            self.scope.uses_gosub = True
            r = self.newlbl('R')
            self.emit(f'else if ({v} >= 1 && {v} <= {len(st.targets)}) {{ if (__gsp >= 512) qb_error(7); __gs[__gsp++] = &&{r};')
            self.emit(f'switch ({v}) {{')
            for i, tg in enumerate(st.targets):
                self.check_label(tg, st)
                self.emit(f'case {i + 1}: goto {self.label_c(tg)};')
            self.emit('} }')
            self.emit(f'}} {r}:;')
        else:
            self.emit(f'switch ({v}) {{')
            for i, tg in enumerate(st.targets):
                self.check_label(tg, st)
                self.emit(f'case {i + 1}: goto {self.label_c(tg)};')
            self.emit('} }')

    def st_onerror(self, st):
        if st.target is None:
            self.emit('qb_handler_on = 0; qb__handler = 0; if (qb_in_handler) { qb_in_handler = 0; qb_error(qb_err); }')
            return
        hid = self.handler_ids.setdefault(st.target, len(self.handler_ids) + 1)
        self.module_label_refs.append((st.target, st))
        self.emit(f'qb__handler = {hid}; qb_handler_on = 1;')

    def st_resume(self, st):
        if self.scope.kind != 'module':
            self.err("RESUME not allowed in procedure (error handlers must be in module-level code)", st)
        chk = 'if (!qb_in_handler || __entry < 1000 || __entry >= 2000) qb_error(20); else '
        if st.mode == 'next':
            self.emit(chk + '{ qb_in_handler = 0; qb_err = 0; return 2; }')
        elif st.mode == 'retry':
            self.emit(chk + '{ qb_in_handler = 0; qb_err = 0; return 1; }')
        else:
            self.check_label(st.target, st)
            rid = self.resume_ids.setdefault(st.target.upper(), len(self.resume_ids) + 1)
            self.emit(chk + f'{{ qb_in_handler = 0; qb_err = 0; qb__resume_label = {rid}; return 3; }}')

    def st_error(self, st):
        self.emit(f'qb_error_stmt({self.conv(self.num(self.gen_expr(st.expr)), "d")});')

    def st_end(self, st):
        self.emit('qb_end();')

    def st_stop(self, st):
        self.emit('qb_stop();')

    def st_system(self, st):
        self.emit('qb_system();')

    def st_exit(self, st):
        w = st.what
        if w in ('SUB', 'FUNCTION'):
            if self.scope.kind != 'proc' or self.scope.proc.what != w:
                self.err(f"EXIT {w} not within {w}", st)
            self.emit('goto __exit;')
            return
        if w == 'DEF':
            if self.scope.kind != 'deffn':
                self.err("EXIT DEF not within DEF FN", st)
            self.emit('goto __exit;')
            return
        for kind, ex, ct in reversed(self.loops):
            if kind == w:
                self.emit(f'goto {ex};')
                return
        self.err(f"EXIT {w} not within {w}...", st)

    # ----- declarations -----
    def dims_code(self, dims, node):
        out = []
        for lo, hi in dims:
            lo_c = self.conv(self.num(self.gen_expr(lo)), 'l') if lo is not None else str(self.prog.option_base)
            hi_c = self.conv(self.num(self.gen_expr(hi)), 'l')
            out.append(f'{lo_c}, {hi_c}')
        return out

    def dim_type(self, dv):
        if dv.astype is not None:
            return self.resolve_type(dv.astype), True
        if dv.suffix:
            return SUFFIX_TYPE[dv.suffix], False
        return dv.deftype, False

    def arr_kind(self, t):
        return 1 if t == '$' else 0

    def esz(self, t):
        if is_fs(t):
            return str(t[1])
        return f'(qb_i32)sizeof({self.ctype(t)})'

    def st_dim(self, st, redim=False):
        for dv in st.vars:
            t, asd = self.dim_type(dv)
            name = dv.name.upper()
            scope = self.scope
            if dv.dims is not None:
                v = None
                if redim:
                    # REDIM without AS/suffix names the default-typed array (QB semantics)
                    v = self.find_var(name, SUFFIX_TYPE[dv.suffix] if dv.suffix else t, dv.deftype, arrays=True)
                    if v is not None and not asd and not dv.suffix and v.t != t:
                        v = None
                    if v and self.scope.kind == 'proc' and v.kind == 'global' and not v.shared:
                        v = None
                if v is None:
                    k = (name, tkey(t))
                    if k in scope.arrays and not redim:
                        v = scope.arrays[k]
                        if v.dimmed and not v.implicit:
                            pass
                    elif (asd and name in scope.asarrays):
                        v = scope.asarrays[name]
                    else:
                        v = self.new_var(name, t, scope, isarr=True, shared=st.shared, asdecl=asd, ndims=len(dv.dims))
                if st.shared:
                    v.shared = True
                v.dimmed = True
                dc = self.dims_code(dv.dims, st)
                kind = self.arr_kind(v.t)
                if redim or st.dynamic or self.scope.kind != 'module' or not all(self.const_value(x) is not None for d in dv.dims for x in d if x is not None):
                    dyn = 1
                else:
                    dyn = 0
                if redim:
                    self.emit(f'qb_aredim({v.aptr}, {self.esz(v.t)}, {kind}, {len(dc)}, {", ".join(dc)});')
                elif v.static and self.scope.kind == 'proc':
                    self.emit(f'if (!{v.cname}.data) qb_adim({v.aptr}, {self.esz(v.t)}, {kind}, {dyn}, {len(dc)}, {", ".join(dc)});')
                else:
                    if v.kind == 'local':
                        self.emit(f'qb_afree({v.aptr});')
                    self.emit(f'qb_adim({v.aptr}, {self.esz(v.t)}, {kind}, {dyn}, {len(dc)}, {", ".join(dc)});')
            else:
                k = (name, tkey(t))
                if asd:
                    if name in scope.asvars:
                        v = scope.asvars[name]
                    else:
                        v = self.new_var(name, t, scope, shared=st.shared, asdecl=True)
                else:
                    v = scope.vars.get(k) or self.new_var(name, t, scope, shared=st.shared)
                if st.shared:
                    v.shared = True

    def st_redim(self, st):
        self.st_dim(st, redim=True)

    def st_static(self, st):
        if self.scope.kind != 'proc':
            return
        for dv in st.vars:
            t, asd = self.dim_type(dv)
            name = dv.name.upper()
            if dv.isarr:
                v = self.new_var(name, t, self.scope, isarr=True, static=True, asdecl=asd)
                if dv.dims:
                    dc = self.dims_code(dv.dims, st)
                    self.emit(f'if (!{v.cname}.data) qb_adim({v.aptr}, {self.esz(v.t)}, {self.arr_kind(v.t)}, 1, {len(dc)}, {", ".join(dc)});')
            else:
                self.new_var(name, t, self.scope, static=True, asdecl=asd)

    def st_shared(self, st):
        if self.scope.kind != 'proc':
            self.err("SHARED only allowed in procedures", st)
        for dv in st.vars:
            t, asd = self.dim_type(dv)
            name = dv.name.upper()
            texp = t if (asd or dv.suffix) else None
            g = self.module
            if dv.isarr:
                v = None
                if name in g.asarrays and (texp is None or self.same_base(g.asarrays[name].t, t)):
                    v = g.asarrays[name]
                else:
                    v = g.arrays.get((name, tkey(t)))
                if v is None:
                    saved = self.scope
                    self.scope = g
                    v = self.new_var(name, t, g, isarr=True, asdecl=asd)
                    self.scope = saved
                self.scope.arrays[(name, tkey(v.t))] = v
                if asd or (name in g.asarrays and g.asarrays[name] is v):
                    self.scope.asarrays[name] = v
            else:
                v = None
                if name in g.asvars and (texp is None or self.same_base(g.asvars[name].t, t)):
                    v = g.asvars[name]
                else:
                    v = g.vars.get((name, tkey(t)))
                if v is None:
                    saved = self.scope
                    self.scope = g
                    v = self.new_var(name, t, g, asdecl=asd)
                    self.scope = saved
                self.scope.vars[(name, tkey(v.t))] = v
                if asd or (name in g.asvars and g.asvars[name] is v):
                    self.scope.asvars[name] = v

    def st_common(self, st):
        for dv in st.vars:
            t, asd = self.dim_type(dv)
            name = dv.name.upper()
            if dv.isarr:
                v = self.find_var(name, t if (asd or dv.suffix) else None, dv.deftype, arrays=True) or \
                    self.new_var(name, t, self.module, isarr=True, asdecl=asd)
            else:
                v = self.find_var(name, t if (asd or dv.suffix) else None, dv.deftype) or self.new_var(name, t, self.module, asdecl=asd)
            if st.shared:
                v.shared = True
            self.common_vars.append(v)

    def st_const(self, st):
        for name, suffix, e in st.items:
            ex = self.gen_expr(e)
            val = self.const_value(e)
            t = SUFFIX_TYPE[suffix] if suffix else ex.t
            if is_fs(t):
                t = '$'
            if is_str(t):
                if e.kind == 'str':
                    code = ex.code
                else:
                    self.err("Invalid constant", st)
                self.scope.consts[name.upper()] = (code, '$', None)
                continue
            if val is None:
                self.err("Invalid constant", st)
            if t in ('i', 'l'):
                code = str(int(round(val)))
            elif t == 's':
                code = repr(float(val)) + 'f'
            else:
                code = repr(float(val))
            if t in ('i', 'l') and not suffix and ex.t in ('s', 'd'):
                t = ex.t
                code = repr(float(val)) + ('f' if t == 's' else '')
            self.scope.consts[name.upper()] = (f'(({CT[t]}){code})', t, val)

    # ----- DATA -----
    def st_read(self, st):
        for v in st.vars:
            lv = self.gen_ref(v, as_lvalue=True)
            if is_fs(lv.t):
                self.stmt_tmp = True
                self.emit(f'qb_fsset({lv.fsbuf}, {lv.fslen}, qb_read_s());')
            elif lv.t == '$':
                self.stmt_tmp = True
                self.emit(f'qb_sset({lv.addr}, qb_read_s());')
            elif is_num(lv.t):
                self.emit(f'{lv.code} = {self.conv(E("qb_read_d()", "d"), lv.t)};')
            else:
                self.err("Type mismatch", st)

    def st_restore(self, st):
        if st.target is None:
            self.emit('qb_restore(0);')
        else:
            idx = self.data_labels.get(st.target.upper())
            if idx is None:
                self.err(f"Label not defined: {st.target}", st)
            self.emit(f'qb_restore({idx});')

    def st_swap(self, st):
        a = self.gen_ref(st.a, as_lvalue=True)
        b = self.gen_ref(st.b, as_lvalue=True)
        if is_fs(a.t) or is_fs(b.t):
            if not (is_fs(a.t) and is_fs(b.t) and a.t == b.t):
                if is_str(a.t) and is_str(b.t):
                    self.stmt_tmp = True
                    ta = self.newtmp()
                    self.emit(f'{{ qbs {ta} = qb_scopy({self.sval(a).code}); ')
                    self.assign(a, b, st)
                    self.assign(b, E(ta, '$'), st)
                    self.emit('}')
                    return
                self.err("Type mismatch", st)
            n = a.t[1]
            self.emit(f'{{ char __sw[{n}]; memcpy(__sw, {a.fsbuf}, {n}); memcpy({a.fsbuf}, {b.fsbuf}, {n}); memcpy({b.fsbuf}, __sw, {n}); }}')
            return
        if a.t != b.t:
            self.err("Type mismatch", st)
        ct = self.ctype(a.t)
        self.emit(f'{{ {ct} __sw = {a.code}; {a.code} = {b.code}; {b.code} = __sw; }}')

    def st_erase(self, st):
        for name, suffix, deft in st.names:
            arr = self.get_array(name, suffix, deft, None, create=False)
            if arr is None:
                self.err(f"Array not defined: {name}", st)
            self.emit(f'qb_aerase({arr.aptr});')

    def st_midstmt(self, st):
        lv = self.gen_ref(st.var, as_lvalue=True)
        start = self.conv(self.num(self.gen_expr(st.start)), 'l')
        ln = self.conv(self.num(self.gen_expr(st.len)), 'l') if st.len is not None else 'QB_NA'
        ex = self.sval(self.gen_expr(st.expr), st)
        if is_fs(lv.t):
            self.emit(f'qb_mid_stmt_fs({lv.fsbuf}, {lv.fslen}, {start}, {ln}, {ex.code});')
        elif lv.t == '$':
            self.emit(f'qb_mid_stmt({lv.addr}, {start}, {ln}, {ex.code});')
        else:
            self.err("Type mismatch", st)

    def st_lset(self, st):
        lv = self.gen_ref(st.var, as_lvalue=True)
        ex = self.gen_expr(st.expr)
        if is_udt(lv.t):
            # LSET record = record
            self.emit(f'memcpy({lv.addr}, {ex.addr}, sizeof({self.ctype(lv.t)}) < sizeof({self.ctype(ex.t)}) ? sizeof({self.ctype(lv.t)}) : sizeof({self.ctype(ex.t)}));')
            return
        s = self.sval(ex, st).code
        fn = 'rset' if st.right else 'lset'
        if is_fs(lv.t):
            self.emit(f'qb_{fn}_fs({lv.fsbuf}, {lv.fslen}, {s});')
        elif lv.t == '$':
            self.emit(f'qb_{fn}({lv.addr}, {s});')
        else:
            self.err("Type mismatch", st)

    # ----- simple statements -----
    def opt(self, args, i, t='l'):
        if i < len(args) and args[i] is not None:
            ex = self.gen_expr(args[i])
            if t == 's':
                return self.sval(ex).code
            return self.conv(self.num(ex), t)
        return 'QB_NA' if t == 'l' else ('QB_NAD' if t == 'd' else 'qb_slit("", 0)')

    def st_simple(self, st):
        w = st.what
        a = st.args
        o = lambda i, t='l': self.opt(a, i, t)
        has = lambda i: i < len(a) and a[i] is not None
        if w == 'CLS':
            self.emit(f'qb_cls({o(0)});')
        elif w == 'LOCATE':
            self.emit(f'qb_locate({o(0)}, {o(1)}, {o(2)}, {o(3)}, {o(4)});')
        elif w == 'COLOR':
            self.emit(f'qb_color({o(0)}, {o(1)}, {o(2)});')
        elif w == 'SCREEN':
            self.emit(f'qb_screen({o(0)}, {o(1)}, {o(2)}, {o(3)});')
        elif w == 'WIDTH':
            self.emit(f'qb_width({o(0)}, {o(1)});')
        elif w == 'WIDTHFILE':
            self.emit(f'qb_width_file({o(0)}, {o(1)});')
        elif w in ('WIDTHLPRINT',):
            pass
        elif w == 'WIDTHDEV':
            self.stmt_tmp = True
            self.emit(f'qb_width_dev({o(0, "s")}, {o(1)});')
        elif w == 'BEEP':
            self.emit('qb_beep();')
        elif w == 'SOUND':
            self.emit(f'qb_sound({o(0, "d")}, {o(1, "d")});')
        elif w == 'PLAY':
            self.stmt_tmp = True
            self.emit(f'qb_play({o(0, "s")});')
        elif w == 'RANDOMIZE':
            if has(0):
                self.emit(f'qb_randomize({o(0, "d")});')
            else:
                self.emit('qb_randomize_ask();')
                self.stmt_tmp = True
        elif w == 'SLEEP':
            self.emit(f'qb_sleep({o(0)});')
        elif w == 'POKE':
            self.emit(f'qb_poke({o(0)}, {o(1)});')
        elif w == 'OUT':
            self.emit(f'qb_out({o(0)}, {o(1)});')
        elif w == 'WAIT':
            self.emit(f'qb_wait({o(0)}, {o(1)}, {o(2)});')
        elif w == 'PCOPY':
            self.emit(f'qb_pcopy({o(0)}, {o(1)});')
        elif w == 'DRAW':
            self.stmt_tmp = True
            self.emit(f'qb_draw({o(0, "s")});')
        elif w in ('KILL', 'MKDIR', 'RMDIR', 'CHDIR', 'CHAIN', 'ENVIRON'):
            self.stmt_tmp = True
            fn = {'KILL': 'qb_kill', 'MKDIR': 'qb_mkdir', 'RMDIR': 'qb_rmdir', 'CHDIR': 'qb_chdir', 'CHAIN': 'qb_chain', 'ENVIRON': 'qb_environ_set'}[w]
            self.emit(f'{fn}({o(0, "s")});')
        elif w == 'FILES':
            self.stmt_tmp = True
            self.emit(f'qb_files({o(0, "s")}, {1 if has(0) else 0});')
        elif w == 'SHELL':
            self.stmt_tmp = True
            self.emit(f'qb_shell({o(0, "s")}, {1 if has(0) else 0});')
        elif w == 'RUN':
            if has(0):
                ex = self.gen_expr(a[0])
                if is_str(ex.t):
                    self.stmt_tmp = True
                    self.emit(f'qb_run_file({self.sval(ex).code});')
                else:
                    self.err("RUN with a line number is not supported", st)
            else:
                self.emit('qb_close_all(); goto __restart;')
                self.module_restart = True
        elif w == 'BLOAD':
            self.stmt_tmp = True
            self.emit(f'qb_bload({o(0, "s")}, {o(1)}, {1 if has(1) else 0});')
        elif w == 'BSAVE':
            self.stmt_tmp = True
            self.emit(f'qb_bsave({o(0, "s")}, {o(1)}, {o(2)});')
        elif w == 'RESET':
            self.emit('qb_close_all();')
        elif w == 'CLEAR':
            self.emit('qb_clear();')
        elif w in ('TRON', 'TROFF'):
            pass
        elif w == 'IOCTL':
            pass
        elif w == 'PALETTE':
            if not a:
                self.emit('qb_palette_reset();')
            else:
                self.emit(f'qb_palette({o(0)}, {o(1)});')
        elif w in ('DATESET', 'TIMESET'):
            self.stmt_tmp = True
            self.emit(f'qb_{"date" if w == "DATESET" else "time"}_set({o(0, "s")});')
        else:
            self.err(f"Statement not supported: {w}", st)

    def st_keystmt(self, st):
        if st.what == 'ON':
            self.emit('qb_key_onoff(1);')
        elif st.what == 'OFF':
            self.emit('qb_key_onoff(0);')
        elif st.what == 'LIST':
            self.emit('qb_key_list();')
        else:
            self.stmt_tmp = True
            self.emit(f'qb_key_set({self.opt(st.args, 0)}, {self.opt(st.args, 1, "s")});')

    EVENTS = {'KEY': 0, 'TIMER': 32, 'PLAY': 33, 'STRIG': 34, 'PEN': 40, 'COM': 41, 'UEVENT': 47}

    def event_index_code(self, ev, arg):
        base = self.EVENTS[ev]
        if ev == 'KEY':
            if arg is None:
                return '0'
            return self.conv(self.num(self.gen_expr(arg)), 'l')
        if ev == 'STRIG' and arg is not None:
            return f'(34 + ({self.conv(self.num(self.gen_expr(arg)), "l")}) / 2)'
        return str(base)

    def st_evstate(self, st):
        state = {'OFF': 0, 'ON': 1, 'STOP': 2}[st.state]
        self.emit(f'qb_ev_set({self.event_index_code(st.event, st.arg)}, {state});')

    def st_onevent(self, st):
        ev = st.event
        if self.scope.kind != 'module':
            self.warnings.append((st.line, "event handlers are dispatched from module-level code only"))
        lid = self.event_ids.setdefault(st.target, len(self.event_ids) + 1)
        self.module_label_refs.append((st.target, st))
        if ev == 'TIMER':
            secs = self.conv(self.num(self.gen_expr(st.arg)), 'd') if st.arg is not None else '1.0'
            self.emit(f'qb_ev_timer({secs}); qb__evh[32] = {lid}; qb_ev_handler(32, 1);')
            return
        if ev == 'PLAY':
            n = self.conv(self.num(self.gen_expr(st.arg)), 'l') if st.arg is not None else '1'
            self.emit(f'qb_ev_play({n}); qb__evh[33] = {lid}; qb_ev_handler(33, 1);')
            return
        idx = self.event_index_code(ev, st.arg)
        v = self.newtmp('ev')
        if ev == 'KEY' and st.arg is not None:
            self.emit(f'{{ qb_i32 {v} = {idx}; if ({v} >= 0 && {v} < 32) {{ qb__evh[{v}] = {lid}; qb_ev_handler({v}, 1); }} }}')
        else:
            self.emit(f'{{ qb_i32 {v} = {idx}; qb__evh[{v}] = {lid}; qb_ev_handler({v}, 1); }}')

    def st_viewprint(self, st):
        if st.top is None:
            self.emit('qb_view_print(QB_NA, QB_NA);')
        else:
            self.emit(f'qb_view_print({self.conv(self.num(self.gen_expr(st.top)), "l")}, {self.conv(self.num(self.gen_expr(st.bottom)), "l")});')

    def pt(self, p):
        return self.conv(self.num(self.gen_expr(p[0])), 'd'), self.conv(self.num(self.gen_expr(p[1])), 'd')

    def st_view(self, st):
        if st.p1 is None:
            self.emit('qb_view(0, 0, 0, 0, 0, QB_NA, QB_NA, 1);')
            return
        x1, y1 = self.pt(st.p1)
        x2, y2 = self.pt(st.p2)
        fill = self.opt([st.fill], 0)
        border = self.opt([st.border], 0)
        self.emit(f'qb_view({1 if st.screen else 0}, {x1}, {y1}, {x2}, {y2}, {fill}, {border}, 0);')

    def st_window(self, st):
        if st.p1 is None:
            self.emit('qb_window(0, 0, 0, 0, 0, 1);')
            return
        x1, y1 = self.pt(st.p1)
        x2, y2 = self.pt(st.p2)
        self.emit(f'qb_window({1 if st.screen else 0}, {x1}, {y1}, {x2}, {y2}, 0);')

    def st_pset(self, st):
        x, y = self.pt(st.p)
        c = self.opt([st.color], 0)
        self.emit(f'qb_pset({1 if st.step else 0}, {x}, {y}, {c}, {1 if st.preset else 0});')

    def st_gline(self, st):
        flags = 0
        if st.p1 is None:
            flags |= 4
            x1 = y1 = '0'
        else:
            x1, y1 = self.pt(st.p1)
        if st.step1:
            flags |= 1
        if st.step2:
            flags |= 2
        x2, y2 = self.pt(st.p2)
        c = self.opt([st.color], 0)
        box = {'B': 1, 'BF': 2}.get(st.box, 0)
        style = self.opt([st.style], 0)
        self.emit(f'qb_line({flags}, {x1}, {y1}, {x2}, {y2}, {c}, {box}, {style});')

    def st_circle(self, st):
        x, y = self.pt(st.p)
        r = self.conv(self.num(self.gen_expr(st.r)), 'd')
        c = self.opt([st.color], 0)
        s = self.opt([st.start], 0, 'd')
        e = self.opt([st.end], 0, 'd')
        asp = self.opt([st.aspect], 0, 'd')
        self.emit(f'qb_circle({1 if st.step else 0}, {x}, {y}, {r}, {c}, {s}, {e}, {asp});')

    def st_paint(self, st):
        x, y = self.pt(st.p)
        color = 'QB_NA'
        tile = 'qb_slit("", 0)'
        has_tile = 0
        if st.paint is not None:
            ex = self.gen_expr(st.paint)
            if is_str(ex.t):
                tile = self.sval(ex).code
                has_tile = 1
                self.stmt_tmp = True
            else:
                color = self.conv(ex, 'l')
        border = self.opt([st.border], 0)
        bg = 'qb_slit("", 0)'
        has_bg = 0
        if st.bg is not None:
            bg = self.sval(self.gen_expr(st.bg)).code
            has_bg = 1
        self.emit(f'qb_paint({1 if st.step else 0}, {x}, {y}, {color}, {tile}, {has_tile}, {border}, {bg}, {has_bg});')

    def st_paletteusing(self, st):
        ref = st.arr
        arr = self.get_array(ref.name, ref.suffix, ref.deftype, None, node=st)
        ap = f'({arr.aptr})'
        if ref.args:
            off = self.conv(self.num(self.gen_expr(ref.args[0])), 'l')
            self.emit(f'{{ qb_i32 __o = qb_aoff1({ap}, {off}); qb_palette_using({ap}->data + __o * {ap}->esz, {ap}->esz, {ap}->n - __o); }}')
        else:
            self.emit(f'qb_palette_using({ap}->data, {ap}->esz, {ap}->n);')

    def arr_and_off(self, ref, st):
        arr = self.get_array(ref.name, ref.suffix, ref.deftype, None, node=st)
        if ref.args:
            idx = [self.conv(self.num(self.gen_expr(x)), 'l') for x in ref.args]
            if len(idx) == 1:
                off = f'qb_aoff1({arr.aptr}, {idx[0]})'
            else:
                off = f'qb_aoff({arr.aptr}, {len(idx)}, {", ".join(idx)})'
        else:
            off = '0'
        return arr, off

    def st_gget(self, st):
        flags = (1 if st.step1 else 0) | (2 if st.step2 else 0)
        x1, y1 = self.pt(st.p1)
        x2, y2 = self.pt(st.p2)
        arr, off = self.arr_and_off(st.arr, st)
        self.emit(f'qb_gget({flags}, {x1}, {y1}, {x2}, {y2}, {arr.aptr}, {off});')

    def st_gput(self, st):
        x, y = self.pt(st.p)
        arr, off = self.arr_and_off(st.arr, st)
        act = {'PSET': 1, 'PRESET': 2, 'AND': 3, 'OR': 4, 'XOR': 5, None: 5}.get(st.action)
        if act is None:
            self.err("Illegal function call: bad PUT action", st)
        self.emit(f'qb_gput({1 if st.step else 0}, {x}, {y}, {arr.aptr}, {off}, {act});')

    # ----- files -----
    def st_open(self, st):
        mode = {'INPUT': 'QB_M_INPUT', 'OUTPUT': 'QB_M_OUTPUT', 'APPEND': 'QB_M_APPEND', 'RANDOM': 'QB_M_RANDOM', 'BINARY': 'QB_M_BINARY', None: 'QB_M_RANDOM'}[st.mode]
        access = {'READ': 1, 'WRITE': 2, 'READWRITE': 3, None: 'QB_NA'}.get(st.access, 'QB_NA')
        name = self.sval(self.gen_expr(st.name), st).code
        fn = self.conv(self.num(self.gen_expr(st.fileno)), 'l')
        rl = self.opt([st.reclen], 0)
        self.emit(f'qb_open({name}, {mode}, {access}, QB_NA, {fn}, {rl});')

    def st_openold(self, st):
        m = self.sval(self.gen_expr(st.mode), st).code
        fn = self.conv(self.num(self.gen_expr(st.fileno)), 'l')
        name = self.sval(self.gen_expr(st.name), st).code
        rl = self.opt([st.reclen], 0)
        self.emit(f'qb_open_old({m}, {fn}, {name}, {rl});')

    def st_close(self, st):
        if not st.files:
            self.emit('qb_close_all();')
        for f in st.files:
            self.emit(f'qb_close({self.conv(self.num(self.gen_expr(f)), "l")});')

    def st_field(self, st):
        fn = self.newtmp('fn')
        self.emit(f'{{ qb_i32 {fn} = {self.conv(self.num(self.gen_expr(st.fileno)), "l")}, __off = 0;')
        for w, v in st.fields:
            lv = self.gen_ref(v, as_lvalue=True)
            if lv.t != '$':
                self.err("FIELD requires variable-length string variables", st)
            wc = self.conv(self.num(self.gen_expr(w)), 'l')
            self.emit(f'{{ qb_i32 __w = {wc}; qb_field({fn}, __off, __w, {lv.addr}); __off += __w; }}')
        self.emit('}')

    def st_seek(self, st):
        self.emit(f'qb_seek({self.conv(self.num(self.gen_expr(st.fileno)), "l")}, {self.conv(self.num(self.gen_expr(st.pos)), "l")});')

    def st_name(self, st):
        a = self.sval(self.gen_expr(st.a), st).code
        b = self.sval(self.gen_expr(st.b), st).code
        self.emit(f'qb_name({a}, {b});')

    def st_fgetput(self, st):
        fn = self.conv(self.num(self.gen_expr(st.fileno)), 'l')
        rec = self.opt([st.rec], 0)
        f = 'qb_get' if st.what == 'GET' else 'qb_put'
        if st.var is None:
            self.emit(f'{f}({fn}, {rec}, 0, 0, 0);')
            return
        lv = self.gen_ref(st.var, as_lvalue=True)
        if lv.t == '$':
            self.emit(f'{f}({fn}, {rec}, {lv.addr}, 0, 1);')
        elif is_fs(lv.t):
            self.emit(f'{f}({fn}, {rec}, {lv.fsbuf}, {lv.fslen}, 0);')
        else:
            self.emit(f'{f}({fn}, {rec}, {lv.addr}, {self.tsize(lv.t)}, 0);')

    def st_defseg(self, st):
        if st.expr is None:
            self.emit('qb_defseg(QB_NA);')
        else:
            self.emit(f'qb_defseg({self.conv(self.num(self.gen_expr(st.expr)), "l")});')

    # ----- CALL -----
    def st_call(self, st):
        name = st.name
        if name in self.procs:
            p = self.procs[name]
            cargs = self.gen_args(p, st.args, st)
            if p.what == 'FUNCTION':
                self.emit(f'(void)F_{cident(name)}({", ".join(cargs)});')
            else:
                self.emit(f'S_{cident(name)}({", ".join(cargs)});')
            return
        if name in ('INTERRUPT', 'INTERRUPTX'):
            if len(st.args) != 3:
                self.err("Argument-count mismatch", st)
            n = self.conv(self.num(self.gen_expr(st.args[0])), 'l')
            a = self.gen_expr(st.args[1])
            b = self.gen_expr(st.args[2])
            if not (a.lv and b.lv):
                self.err("Parameter type mismatch", st)
            self.emit(f'qb_interrupt({n}, (void *){a.addr}, (void *){b.addr}, {1 if name == "INTERRUPTX" else 0});')
            return
        if name == 'ABSOLUTE':
            self.emit('qb_absolute();')
            return
        self.err(f"Subprogram not defined: {name}", st)

    # ---- procedures ----------------------------------------------------------------
    def proc_signature(self, p):
        ptypes = self.param_types(p)
        cps = []
        for prm, t in ptypes:
            pn = 'p_' + cident(prm.name) + '_' + (TCHAR.get(t, 'U') if not isinstance(t, tuple) else 'U')
            if prm.isarr:
                cps.append(f'qbarr *{pn}')
            elif t == 'any':
                cps.append(f'void *{pn}')
            elif is_udt(t):
                cps.append(f'{self.ctype(t)} *{pn}')
            elif is_fs(t):
                cps.append(f'qbs *{pn}')
            else:
                cps.append(f'{CT[t]} *{pn}')
        params = ', '.join(cps) if cps else 'void'
        if p.what == 'SUB':
            return f'static void S_{cident(p.name)}({params})'
        rt = self.proc_rtype(p)
        return f'static {CT[rt]} F_{cident(p.name)}({params})'

    def gen_proc(self, p):
        sc = Scope('proc', p.name, self.module, proc=p)
        sc.static_all = p.static
        self.scope = sc
        self.loops = []
        ptypes = self.param_types(p)
        for prm, t in ptypes:
            pn = 'p_' + cident(prm.name) + '_' + (TCHAR.get(t, 'U') if not isinstance(t, tuple) else 'U')
            name = prm.name.upper()
            v = Var(name, t if not is_fs(t) else '$', pn, isarr=prm.isarr, ptr=True, kind='param')
            if prm.isarr:
                sc.arrays[(name, tkey(v.t))] = v
                if prm.astype is not None:
                    sc.asarrays[name] = v
            else:
                sc.vars[(name, tkey(v.t))] = v
                if prm.astype is not None:
                    sc.asvars[name] = v
        saved = self.out
        self.out = []
        self.pending_labels = []
        self.gen_block(p.body)
        body = self.out
        self.out = saved
        self.resolve_labels(sc, p.body)
        rt = self.proc_rtype(p) if p.what == 'FUNCTION' else None
        lines = [self.proc_signature(p) + ' {']
        if rt == '$':
            lines.append('qbs __ret = {0, 0, 0};')
        elif rt:
            lines.append(f'{CT[rt]} __ret = 0;')
        if sc.uses_gosub:
            lines.append('void *__gs[512]; int __gsp = 0;')
        if self.uses_error:
            lines.append('void *__rs = 0, *__rn = 0;')
        lines.extend(sc.locals_decl)
        for v, nd in sc.implicit_arrays:
            dims = ', '.join([f'{self.prog.option_base}, 10'] * nd)
            lines.append(f'if (!({v.aptr})->data) qb_adim({v.aptr}, {self.esz(v.t)}, {self.arr_kind(v.t)}, 0, {nd}, {dims});')
        lines.extend(body)
        lines.append('goto __exit;')
        lines.append('__exit:;')
        lines.extend(sc.cleanup)
        if rt == '$':
            lines.append('{ qbs __r = qb_scopy(__ret); qb_sfree(&__ret); return __r; }')
        elif rt:
            lines.append('return __ret;')
        lines.append('}')
        self.funcs.append('\n'.join(lines))
        self.scope = self.module

    def gen_deffn(self, fn):
        sc = Scope('deffn', fn.name, self.module)
        rt = SUFFIX_TYPE[fn.suffix] if fn.suffix else fn.deftype
        sc.rtype = rt
        self.scope = sc
        cps = []
        for prm in fn.params:
            t = self.resolve_type(prm.astype) if prm.astype else (SUFFIX_TYPE[prm.suffix] if prm.suffix else prm.deftype)
            pn = 'p_' + cident(prm.name) + '_' + TCHAR.get(t, 'U')
            v = Var(prm.name.upper(), t, pn, kind='param')
            sc.vars[(prm.name.upper(), tkey(t))] = v
            if prm.astype is not None:
                sc.asvars[prm.name.upper()] = v
            cps.append(f'{CT[t]} {pn}')
        saved = self.out
        self.out = []
        self.pending_labels = []
        if fn.expr is not None:
            self.stmt_tmp = False
            ex = self.gen_expr(fn.expr)
            if rt == '$':
                self.emit(f'qb_sset(&__ret, {self.sval(ex).code});')
            else:
                self.emit(f'__ret = {self.conv(ex, rt)};')
        else:
            self.gen_block(fn.body)
        body = self.out
        self.out = saved
        self.resolve_labels(sc, fn.body or [])
        lines = [f'static {CT[rt]} FN_{cident(fn.name)}({", ".join(cps) if cps else "void"}) {{']
        lines.append('qbs __ret = {0, 0, 0};' if rt == '$' else f'{CT[rt]} __ret = 0;')
        if sc.uses_gosub:
            lines.append('void *__gs[512]; int __gsp = 0;')
        if self.uses_error:
            lines.append('void *__rs = 0, *__rn = 0;')
        lines.extend(sc.locals_decl)
        lines.extend(body)
        lines.append('goto __exit;')
        lines.append('__exit:;')
        if rt == '$':
            lines.append('{ qbs __r = qb_scopy(__ret); qb_sfree(&__ret); return __r; }')
        else:
            lines.append('return __ret;')
        lines.append('}')
        self.protos.append(f'static {CT[rt]} FN_{cident(fn.name)}({", ".join(cps) if cps else "void"});')
        self.funcs.append('\n'.join(lines))
        self.scope = self.module

    def collect_labels(self, stmts, out):
        for st in stmts:
            if st.kind == 'label':
                out.add(st.name.upper())
            for attr in ('then', 'els', 'body'):
                b = getattr(st, attr, None)
                if isinstance(b, list):
                    self.collect_labels(b, out)
            if st.kind == 'if':
                for c, b in st.elifs:
                    self.collect_labels(b, out)
            if st.kind == 'select':
                for t, b in st.cases:
                    self.collect_labels(b, out)

    def resolve_labels(self, scope, stmts):
        labels = set()
        self.collect_labels(stmts, labels)
        for name, node, sc in self.pending_labels:
            if name.upper() not in labels:
                self.err(f"Label not defined: {name}", node)

    def data_label_index(self, stmts, pos=[0]):
        """Map labels to DATA item index (first DATA at or after the label)."""
        seq = []

        def walk(lst):
            for st in lst:
                seq.append(st)
                for attr in ('then', 'els', 'body'):
                    b = getattr(st, attr, None)
                    if isinstance(b, list):
                        walk(b)
                if st.kind == 'if':
                    for c, b in st.elifs:
                        walk(b)
                if st.kind == 'select':
                    for t, b in st.cases:
                        walk(b)
        walk(stmts)
        pending = []
        for st in seq:
            if st.kind == 'label':
                pending.append(st.name.upper())
            elif st.kind == 'data':
                for l in pending:
                    self.data_labels[l] = st.index
                pending = []
        for l in pending:
            self.data_labels[l] = len(self.prog.data)

    # ---- program -----------------------------------------------------------------------
    def generate(self):
        prog = self.prog
        self.module_restart = False
        for p in prog.procs:
            if p.name in self.procs:
                self.err(f"Duplicate definition: {p.name}", p)
            self.procs[p.name] = p
        for fn in prog.deffns:
            self.deffns[fn.name] = fn
        for name, d in prog.declares.items():
            if name not in self.procs and name not in ('INTERRUPT', 'INTERRUPTX', 'ABSOLUTE'):
                self.warnings.append((d.line, f"DECLARE {d.what} {name}: no procedure body in this module"))
        self.gen_types()
        self.data_label_index(prog.main + [s for p in prog.procs for s in p.body])
        self.module_label_refs = []
        # procedures signatures
        for p in prog.procs:
            self.protos.append(self.proc_signature(p) + ';')
        # module body first (defines globals)
        self.scope = self.module
        self.pending_labels = []
        saved = self.out
        self.out = []
        # module CONSTs and DEF FN definitions are lexically ordered; DEF FN bodies generated after module code
        self.gen_block(prog.main)
        main_body = self.out
        self.out = saved
        module_pending = list(self.pending_labels)
        labels = set()
        self.collect_labels(prog.main, labels)
        for name, node, sc in module_pending + [(n, nd, None) for n, nd in self.module_label_refs]:
            if name.upper() not in labels:
                self.err(f"Label not defined: {name}", node)
        for fn in prog.deffns:
            self.gen_deffn(fn)
        for p in prog.procs:
            self.module_label_refs_before = len(self.module_label_refs)
            self.gen_proc(p)
            for n, nd in self.module_label_refs[self.module_label_refs_before:]:
                if n.upper() not in labels:
                    self.err(f"Label not defined: {n}", nd)
        # assemble
        out = []
        out.append('/* generated by LinBASIC lbc - QB 4.5 compatible BASIC compiler */')
        out.append('#include "qbrt.h"')
        out.extend(self.types_c)
        out.append('static qb_i32 qb__handler; static qb_i32 qb__evh[64]; static int qb__unwinding, qb__resume_label; static qb_i32 qb__lnum;')
        out.append('static int qb__module(int __entry); static int qb__handle(void); static void qb__event(void);')
        out.extend(self.globals)
        # DATA
        if prog.data:
            items = ', '.join(c_string_literal(d) for d in prog.data)
            out.append(f'static const char *const qb__data[] = {{ {items} }};')
        out.extend(self.protos)
        out.extend(self.funcs)
        out.append('static int qb__module(int __entry) {')
        if self.module.uses_gosub or self.uses_events:
            out.append('void *__gs[512]; int __gsp = 0;')
        if self.uses_error:
            out.append('void *__rs = 0, *__rn = 0;')
        if self.handler_ids or self.event_ids:
            out.append('switch (__entry) {')
            for name, hid in self.handler_ids.items():
                out.append(f'case {1000 + hid}: goto L_{cident(name)};')
            for name, lid in self.event_ids.items():
                out.append(f'case {2000 + lid}: goto L_{cident(name)};')
            out.append('}')
        out.append('__restart:;')
        for v, nd in self.module.implicit_arrays:
            dims = ', '.join([f'{self.prog.option_base}, 10'] * nd)
            out.append(f'if (!({v.aptr})->data) qb_adim({v.aptr}, {self.esz(v.t)}, {self.arr_kind(v.t)}, 0, {nd}, {dims});')
        if self.common_vars:
            out.append('if (qb_chained()) {')
            for i, v in enumerate(self.common_vars):
                ty = 2 if v.isarr else (1 if v.t == '$' else 0)
                size = '0' if ty else self.esz(v.t)
                out.append(f'qb_common_load({i}, {ty}, (void *)&{v.cname}, {size});')
            out.append('}')
        out.extend(main_body)
        out.append('qb_end();')
        if self.uses_error:
            out.append('__unwind:')
            out.append('qb__unwinding = 0;')
            out.append('switch (qb__resume_label) {')
            for name, rid in self.resume_ids.items():
                out.append(f'case {rid}: goto L_{cident(name)};')
            out.append('}')
            out.append('qb_end();')
        out.append('return 0;')
        out.append('}')
        if self.uses_error:
            out.append('static int qb__handle(void) {')
            out.append('qb_errpend = 0;')
            out.append('if (!qb_handler_on || qb_in_handler || !qb__handler) { qb_handler_on = 0; qb_in_handler = 0; qb_error(qb_err); }')
            out.append('qb_in_handler = 1; qb_erl = qb__lnum;')
            out.append('int r = qb__module(1000 + qb__handler);')
            out.append('qb_in_handler = 0;')
            out.append('if (r == 0) qb_end();')
            out.append('if (r == 3) qb__unwinding = 1;')
            out.append('return r;')
            out.append('}')
        if self.uses_events:
            out.append('static void qb__event(void) {')
            out.append('int ev = qb_ev_take(); if (!ev) return;')
            out.append('if (!qb__evh[ev - 1]) return;')
            out.append('qb_ev_enter(ev - 1); qb__module(2000 + qb__evh[ev - 1]); qb_ev_leave(ev - 1);')
            out.append('}')
        # CHAIN: save COMMON
        if self.common_vars:
            out.append('static void qb__common_save(void) {')
            for i, v in enumerate(self.common_vars):
                ty = 2 if v.isarr else (1 if v.t == '$' else 0)
                size = '0' if ty else self.esz(v.t)
                out.append(f'qb_common_save({i}, {ty}, (void *)&{v.cname}, {size});')
            out.append('}')
        flags = 0
        if self.opts.get('crlf'):
            flags |= 1
        if self.opts.get('ctrlbreak', True):
            flags |= 2
        if self.opts.get('console'):
            flags |= 4
        out.append('int main(int argc, char **argv) {')
        out.append(f'qb_init(argc, argv, {c_string_literal(self.modname)}, {flags});')
        if prog.data:
            out.append(f'qb_data_init(qb__data, {len(prog.data)});')
        if self.common_vars:
            out.append('extern void qb_set_common_saver(void (*)(void)); qb_set_common_saver(qb__common_save);')
        out.append('qb__module(0);')
        out.append('qb_end();')
        out.append('return 0;')
        out.append('}')
        return '\n'.join(out) + '\n'
