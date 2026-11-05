# LinBASIC compiler - command line driver
# Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later.
import os
import re
import sys
import shutil
import subprocess
import tempfile

from .lexer import tokenize, QBError
from .parser import Parser
from .codegen import CodeGen
from . import qb45bin

VERSION = "1.0.4"

USAGE = """LinBASIC lbc %s - QB 4.5 compatible BASIC compiler for Linux

usage: lbc [options] FILE.BAS
  -o FILE        output executable (default: FILE without .BAS, FILE.exe for Windows)
  --target linux|windows
                 build a Linux program (default) or a Windows .exe
  --windows      same as --target windows
  -c             only generate C source (FILE.c)
  -C             keep the generated C source next to the program
  -O             optimise with the system gcc instead of the bundled tcc
  --console      program runs in the terminal (Linux) or cmd console (Windows)
                 instead of its own DOS window
  --crlf         write text files with CR+LF line ends (DOS style; default for Windows)
  --run          run the program after compiling it
  --check        syntax/semantic check only
  -I DIR         add a directory to the $INCLUDE search path
  --convert IN OUT   convert a QB binary (fast load) .BAS to text
  -v, --version  show version
""" % VERSION


def home_dir():
    env = os.environ.get('LINBASIC_HOME')
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    # <home>/compiler/lbc/driver.py  or  <home>/lib/lbc/driver.py
    return os.path.dirname(os.path.dirname(here))


def find_runtime():
    h = home_dir()
    for cand in (os.path.join(h, 'runtime'), os.path.join(h, 'lib', 'runtime')):
        if os.path.exists(os.path.join(cand, 'qbrt.h')):
            return cand
    raise QBError("runtime library (qbrt.h / libqbrt.a) not found; set LINBASIC_HOME")


def decode_source(data):
    """Return source text with one char per CP437 byte (chars 0..255)."""
    if qb45bin.is_qb_binary(data):
        text = qb45bin.decode_qb45_binary(data)
        # the decoder yields Unicode (CP437 decoded); back to one char per CP437 byte
        text = text.encode('cp437', errors='replace').decode('latin-1')
        return text, 'binary'
    # UTF-8 with non-ASCII characters -> convert to CP437
    try:
        u = data.decode('utf-8')
        if any(ord(c) > 127 for c in u):
            b = u.encode('cp437', errors='replace')
            return b.decode('latin-1'), 'utf-8'
    except UnicodeDecodeError:
        pass
    return data.decode('latin-1'), 'cp437'


INCLUDE_RE = re.compile(r"""(?:'|\bREM\b).*?\$INCLUDE\s*:\s*'([^']+)'""", re.I)


def preprocess(path, text, incdirs, line_map, depth=0, seen=None):
    """Expand $INCLUDE metacommands. line_map collects (file, line) per output line."""
    out = []
    if depth > 16:
        raise QBError("$INCLUDE nesting too deep", 0, 0, path)
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
    for i, line in enumerate(lines):
        m = INCLUDE_RE.search(line)
        if m and line.count('"', 0, m.start()) % 2 == 0:
            name = m.group(1).strip()
            ipath = find_include(name, os.path.dirname(path), incdirs)
            if not ipath:
                raise QBError(f"File not found: {name}", i + 1, 1, path)
            with open(ipath, 'rb') as f:
                itext, _ = decode_source(f.read())
            out.append(line[:m.start()] if not line.lstrip().startswith(("'", "REM", "rem")) else '')
            line_map.append((path, i + 1))
            sub = preprocess(ipath, itext, incdirs, line_map, depth + 1)
            out.extend(sub)
            continue
        out.append(line)
        line_map.append((path, i + 1))
    return out


def find_include(name, basedir, incdirs):
    name = name.replace('\\', '/')
    if re.match(r'^[A-Za-z]:', name):
        name = name[2:]
    cands = []
    for d in [basedir] + list(incdirs):
        cands.append(os.path.join(d, name))
        cands.append(os.path.join(d, os.path.basename(name)))
    for c in cands:
        if os.path.exists(c):
            return c
        d, b = os.path.split(c)
        if os.path.isdir(d or '.'):
            for e in os.listdir(d or '.'):
                if e.lower() == b.lower():
                    return os.path.join(d, e)
    return None


SUB_RE = re.compile(r'^\s*(?:\d+\s+)?(?:DECLARE\s+)?SUB\s+([A-Za-z][A-Za-z0-9.]*)', re.I | re.M)


def compile_source(path, text, opts):
    incdirs = list(opts.get('incdirs', []))
    rt = None
    try:
        rt = find_runtime()
        incdirs.append(os.path.join(rt, 'include'))
    except QBError:
        pass
    line_map = []
    lines = preprocess(path, text, incdirs, line_map)
    full = '\n'.join(lines)
    Parser.known_subs = set(m.group(1).upper() for m in SUB_RE.finditer(full))
    modname = os.path.splitext(os.path.basename(path))[0].upper()
    try:
        toks = tokenize(full, path)
        prog = Parser(toks, path).parse_program()
        cg = CodeGen(prog, modname, opts)
        csrc = cg.generate()
    except QBError as e:
        if 1 <= e.line <= len(line_map):
            e.file, e.line = line_map[e.line - 1]
        else:
            e.file = path
        raise
    warnings = []
    for ln, msg in cg.warnings:
        if 1 <= ln <= len(line_map):
            f, l = line_map[ln - 1]
        else:
            f, l = path, ln
        warnings.append(f"{f}:{l}: warning: {msg}")
    # map C line directives? keep a table for runtime error messages: qb_curline uses merged line numbers
    if any(f != path for f, _ in line_map):
        # rewrite qb_curline numbers to the original file lines of the main file when possible
        def fix(m):
            n = int(m.group(1))
            if 1 <= n <= len(line_map):
                return f'qb_curline = {line_map[n - 1][1]};'
            return m.group(0)
        csrc = re.sub(r'qb_curline = (\d+);', fix, csrc)
    return csrc, warnings


def find_tcc_kit(rt):
    """Locate the bundled tcc + crt files; fall back to system ones."""
    h = home_dir()
    kit = os.path.join(h, 'tcc')
    tcc = os.path.join(kit, 'tcc')
    if os.path.exists(tcc):
        return {
            'tcc': tcc,
            'crt': [os.path.join(kit, 'crt1.o'), os.path.join(kit, 'crti.o')],
            'crtn': os.path.join(kit, 'crtn.o'),
            'libs': [os.path.join(kit, 'libc_nonshared.a'), os.path.join(kit, 'libtcc1.a')],
        }
    sys_tcc = shutil.which('tcc')
    if sys_tcc:
        libdir = '/usr/lib/x86_64-linux-gnu'
        return {
            'tcc': sys_tcc,
            'crt': [os.path.join(libdir, 'crt1.o'), os.path.join(libdir, 'crti.o')],
            'crtn': os.path.join(libdir, 'crtn.o'),
            'libs': [os.path.join(libdir, 'libc_nonshared.a'), os.path.join(libdir, 'tcc', 'libtcc1.a')],
        }
    return None


def find_libc():
    for d in ('/lib/x86_64-linux-gnu', '/usr/lib/x86_64-linux-gnu', '/lib64', '/usr/lib64', '/lib', '/usr/lib'):
        c = os.path.join(d, 'libc.so.6')
        m = os.path.join(d, 'libm.so.6')
        if os.path.exists(c) and os.path.exists(m):
            return c, m
    return None, None


def find_tccwin_kit():
    """Locate the x86_64-win32-tcc cross compiler used for Windows programs."""
    for kit in (os.environ.get('LINBASIC_TCCWIN'), os.path.join(home_dir(), 'tccwin')):
        if kit and os.path.exists(os.path.join(kit, 'x86_64-win32-tcc')):
            return kit
    return None


def build_exe_windows(csrc_path, out_path, opts):
    rt = find_runtime()
    lib = os.path.join(rt, 'win', 'libqbrt.a')
    if not os.path.exists(lib):
        raise QBError("the Windows runtime (runtime/win/libqbrt.a) is not installed")
    kit = find_tccwin_kit()
    if not kit:
        raise QBError("the Windows C back end (tccwin/x86_64-win32-tcc) is not installed")
    cmd = [os.path.join(kit, 'x86_64-win32-tcc'), '-B' + kit, '-w', '-I', rt, '-o', out_path, csrc_path, lib,
           '-luser32', '-lgdi32', '-lwinmm']
    if not opts.get('console'):
        cmd.append('-Wl,-subsystem=windows')      # a window program: no console window
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise QBError("C back end failed:\n" + (r.stderr or r.stdout))
    return out_path


def build_exe(csrc_path, out_path, opts):
    if opts.get('target') == 'windows':
        return build_exe_windows(csrc_path, out_path, opts)
    rt = find_runtime()
    lib = os.path.join(rt, 'libqbrt.a')
    if opts.get('gcc'):
        cc = shutil.which('gcc') or shutil.which('cc')
        if not cc:
            raise QBError("gcc not found (install build-essential or omit -O)")
        cmd = [cc, '-O2', '-w', '-fno-strict-aliasing', '-I', rt, '-o', out_path, csrc_path, lib, '-lm', '-lpthread', '-ldl']
    else:
        kit = find_tcc_kit(rt)
        if not kit:
            raise QBError("no C back end found (bundled tcc missing)")
        libc, libm = find_libc()
        if not libc:
            raise QBError("libc.so.6 not found")
        cmd = [kit['tcc'], '-nostdlib', '-nostdinc', '-w', '-I', rt, '-o', out_path] + kit['crt'] + \
              [csrc_path, lib, libc, libm] + kit['libs'] + [kit['crtn']]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise QBError("C back end failed:\n" + (r.stderr or r.stdout))
    return out_path


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    opts = {'incdirs': []}
    src = None
    out = None
    only_c = keep_c = run = check = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ('-h', '--help'):
            print(USAGE)
            return 0
        if a in ('-v', '--version'):
            print(f"LinBASIC lbc {VERSION}")
            return 0
        if a == '-o':
            out = argv[i + 1]; i += 2; continue
        if a == '-c':
            only_c = True
        elif a == '-C':
            keep_c = True
        elif a == '-O':
            opts['gcc'] = True
        elif a == '--console':
            opts['console'] = True
        elif a in ('--windows', '-W'):
            opts['target'] = 'windows'
        elif a == '--target' or a.startswith('--target='):
            t = a.split('=', 1)[1] if '=' in a else (argv[i + 1] if i + 1 < len(argv) else '')
            if '=' not in a:
                i += 1
            t = t.lower()
            if t in ('win', 'win64', 'windows'):
                opts['target'] = 'windows'
            elif t in ('linux', 'lin'):
                opts['target'] = 'linux'
            else:
                print(f"lbc: unknown target {t!r} (use linux or windows)", file=sys.stderr)
                return 2
        elif a == '--crlf':
            opts['crlf'] = True
        elif a == '--run':
            run = True
        elif a == '--check':
            check = True
        elif a == '-I':
            opts['incdirs'].append(argv[i + 1]); i += 2; continue
        elif a == '--convert':
            with open(argv[i + 1], 'rb') as f:
                data = f.read()
            text, kind = decode_source(data)
            with open(argv[i + 2], 'wb') as f:
                f.write(text.replace('\n', '\r\n').encode('latin-1'))
            print(f"converted ({kind})")
            return 0
        elif a.startswith('-') and len(a) > 1:
            print(f"lbc: unknown option {a}", file=sys.stderr)
            return 2
        else:
            src = a
        i += 1
    if not src:
        print(USAGE)
        return 2
    if opts.get('target') == 'windows':
        if opts.get('gcc'):
            print("lbc: -O (gcc) is only available for Linux programs", file=sys.stderr)
            return 2
        opts['crlf'] = True                 # DOS/Windows text files
    try:
        with open(src, 'rb') as f:
            data = f.read()
    except OSError as e:
        print(f"lbc: {e}", file=sys.stderr)
        return 1
    text, kind = decode_source(data)
    try:
        csrc, warnings = compile_source(src, text, opts)
    except QBError as e:
        print(f"{e.file}:{e.line}:{e.col}: error: {e.msg}", file=sys.stderr)
        return 1
    except RecursionError:
        print(f"{src}:0:0: error: program too complex", file=sys.stderr)
        return 1
    for w in warnings:
        print(w, file=sys.stderr)
    if check:
        print(f"{src}: OK")
        return 0
    base = os.path.splitext(src)[0]
    if only_c:
        with open(out or base + '.c', 'w', encoding='latin-1') as f:
            f.write(csrc)
        return 0
    exe = out or (base + '.exe' if opts.get('target') == 'windows' else base)
    if os.path.abspath(exe) == os.path.abspath(src):
        exe = base + '.out'
    if keep_c:
        cpath = base + '.c'
        with open(cpath, 'w', encoding='latin-1') as f:
            f.write(csrc)
        tmpdir = None
    else:
        tmpdir = tempfile.mkdtemp(prefix='lbc-')
        cpath = os.path.join(tmpdir, os.path.basename(base) + '.c')
        with open(cpath, 'w', encoding='latin-1') as f:
            f.write(csrc)
    try:
        build_exe(cpath, exe, opts)
    except QBError as e:
        print(f"lbc: error: {e.msg}", file=sys.stderr)
        return 1
    finally:
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)
    if run:
        prog = [os.path.abspath(exe)]
        if opts.get('target') == 'windows':
            wine = shutil.which('wine') or shutil.which('wine64')
            if not wine:
                print(f"lbc: {exe} is a Windows program; copy it to Windows to run it (or install wine)", file=sys.stderr)
                return 0
            prog = [wine] + prog
        p = subprocess.run(prog)
        return p.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
