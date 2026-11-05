"""BASIC language support for LinBASIC.

Adds the QB 4.5 workflow on top of the Linpad++ editor:
  * Run > Start (F5 / Shift+F5): compile with lbc and run the program
  * Make EXE File..., Check syntax, Modify COMMAND$...
  * compiler / run-time error list with jump-to-line and in-editor annotations
  * QB 4.5 help (F1 on a keyword) read from the original QB45*.HLP files
  * SUBs list (F2), New SUB / New FUNCTION
  * opening QB "fast load" (binary) .BAS files as text
"""
import os
import re
import shlex
import shutil
import sys

from PyQt6.QtCore import Qt, QProcess, QProcessEnvironment, QUrl, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QTextCursor, QFont, QColor, QTextCharFormat
from PyQt6.QtWidgets import (QDockWidget, QPlainTextEdit, QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser,
                             QLineEdit, QListWidget, QListWidgetItem, QPushButton, QDialog, QLabel,
                             QCheckBox, QDialogButtonBox, QFileDialog, QMessageBox, QInputDialog, QSplitter,
                             QFormLayout, QMenu, QComboBox)
from PyQt6.Qsci import QsciScintilla as S

from . import settings

QB_EXT = (".bas", ".bi", ".bm")
ERR_RE = re.compile(r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+): (?P<kind>error|warning): (?P<msg>.*)$")
RT_RE = re.compile(r"^qbrt: runtime error (?P<code>\d+): (?P<msg>.*?) in line (?P<line>\d+) of module (?P<mod>\S+)")


def linbasic_home():
    h = os.environ.get("LINBASIC_HOME")
    if h:
        return h
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.dirname(os.path.dirname(here)), os.path.dirname(here)):
        if os.path.exists(os.path.join(cand, "compiler", "lbc.py")):
            return cand
    return os.path.dirname(os.path.dirname(here))


WINDOWS = os.name == "nt"
CREATE_NEW_CONSOLE = 0x00000010


def cache_dir():
    if WINDOWS:
        from . import paths
        pd = paths.portable_dir()
        d = os.path.join(pd, "cache") if pd else \
            os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "LinBASIC", "cache")
        os.makedirs(d, exist_ok=True)
        return d
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    d = os.path.join(base, "linbasic")
    os.makedirs(d, exist_ok=True)
    return d


def is_qb_file(path):
    return bool(path) and path.lower().endswith(QB_EXT)


def host_env():
    """Environment for programs we start: undo the AppImage's library paths."""
    env = QProcessEnvironment.systemEnvironment()
    if "LD_LIBRARY_PATH_ORIG" in os.environ:
        if os.environ["LD_LIBRARY_PATH_ORIG"]:
            env.insert("LD_LIBRARY_PATH", os.environ["LD_LIBRARY_PATH_ORIG"])
        else:
            env.remove("LD_LIBRARY_PATH")
    if os.environ.get("QT_PLUGIN_PATH_ORIG"):
        env.insert("QT_PLUGIN_PATH", os.environ["QT_PLUGIN_PATH_ORIG"])
    else:
        env.remove("QT_PLUGIN_PATH")
    for k in ("PYTHONHOME", "PYTHONPATH"):
        env.remove(k)
    return env


# --------------------------------------------------------------------------
# a short built-in reference, used when the QB 4.5 help files are not found
BUILTIN_HELP = {
    "PRINT": "PRINT [#filenumber,] [USING format$;] [expressionlist] [{;|,}]\nOutputs data to the screen or a file. ';' keeps the cursor after the item, ',' moves to the next 14-column zone.",
    "INPUT": "INPUT [;] [\"prompt\"{;|,}] variablelist\nINPUT #filenumber, variablelist\nReads values from the keyboard or a sequential file.",
    "LINE INPUT": "LINE INPUT [;] [\"prompt\";] stringvariable\nLINE INPUT #filenumber, stringvariable\nReads a whole line.",
    "IF": "IF condition THEN statements [ELSE statements]\nIF condition THEN ... [ELSEIF condition THEN ...] [ELSE ...] END IF",
    "FOR": "FOR counter = start TO end [STEP increment] ... NEXT [counter [,counter]...]",
    "DO": "DO [{WHILE|UNTIL} condition] ... LOOP\nDO ... LOOP [{WHILE|UNTIL} condition]",
    "WHILE": "WHILE condition ... WEND",
    "SELECT": "SELECT CASE expression\n  CASE expressionlist\n  CASE IS relop expression\n  CASE a TO b\n  CASE ELSE\nEND SELECT",
    "SUB": "SUB name [(parameterlist)] [STATIC] ... END SUB\nParameters are passed by reference; use CALL name(args) or name args.",
    "FUNCTION": "FUNCTION name [(parameterlist)] [STATIC] ... name = result ... END FUNCTION",
    "DIM": "DIM [SHARED] variable[(subscripts)] [AS type] [, ...]\nsubscripts: [lower TO] upper [, ...]; types: INTEGER LONG SINGLE DOUBLE STRING STRING * n user TYPE",
    "REDIM": "REDIM [SHARED] array(subscripts) [AS type]  - reallocates a dynamic array (contents are cleared)",
    "TYPE": "TYPE name\n  element AS type\n  ...\nEND TYPE",
    "CONST": "CONST name = expression [, ...]",
    "GOSUB": "GOSUB label ... RETURN [label]",
    "GOTO": "GOTO {linelabel | linenumber}",
    "ON": "ON expression {GOTO|GOSUB} labellist\nON ERROR GOTO label | ON ERROR GOTO 0\nON {KEY(n)|TIMER(n)|PLAY(n)} GOSUB label",
    "RESUME": "RESUME [0] | RESUME NEXT | RESUME label   - leaves an error handler",
    "OPEN": "OPEN file$ [FOR {INPUT|OUTPUT|APPEND|RANDOM|BINARY}] [ACCESS ...] [lock] AS [#]n [LEN=reclen]\nOPEN mode$, [#]n, file$ [, reclen]",
    "CLOSE": "CLOSE [[#]n [, [#]n]...]",
    "GET": "GET [#]n [, [record] [, variable]]   (files)\nGET [STEP](x1,y1)-[STEP](x2,y2), array[(index)]   (graphics)",
    "PUT": "PUT [#]n [, [record] [, variable]]   (files)\nPUT [STEP](x,y), array[(index)] [, {PSET|PRESET|AND|OR|XOR}]   (graphics)",
    "SCREEN": "SCREEN mode [, [colorswitch] [, [apage] [, vpage]]]\nmodes: 0 text, 1 320x200x4, 2 640x200x2, 7 320x200x16, 8 640x200x16, 9 640x350x16, 10, 11 640x480x2, 12 640x480x16, 13 320x200x256\nSCREEN(row, column [, colorflag]) returns the character or attribute.",
    "COLOR": "COLOR [foreground] [, [background] [, border]]   (meaning depends on the SCREEN mode)",
    "LOCATE": "LOCATE [row] [, [column] [, [cursor] [, [start] [, stop]]]]",
    "CLS": "CLS [{0|1|2}]",
    "LINE": "LINE [[STEP](x1,y1)]-[STEP](x2,y2) [, [color] [, [B|BF] [, style]]]",
    "CIRCLE": "CIRCLE [STEP](x,y), radius [, [color] [, [start] [, [end] [, aspect]]]]",
    "PSET": "PSET [STEP](x,y) [, color]",
    "PAINT": "PAINT [STEP](x,y) [, [{color|tile$}] [, [bordercolor] [, background$]]]",
    "DRAW": "DRAW commandstring$  (U D L R E F G H M B N A TA C S P X)",
    "VIEW": "VIEW [[SCREEN] (x1,y1)-(x2,y2) [, [color] [, border]]]\nVIEW PRINT [top TO bottom]",
    "WINDOW": "WINDOW [[SCREEN] (x1,y1)-(x2,y2)]",
    "PALETTE": "PALETTE [attribute, color] | PALETTE USING array[(index)]",
    "SOUND": "SOUND frequency, duration   (duration in clock ticks, 18.2 per second)",
    "PLAY": "PLAY commandstring$   (A-G, O, <, >, L, T, P, N, MN/ML/MS, MF/MB, X)",
    "BEEP": "BEEP",
    "DATA": "DATA constant [, constant]...   READ variablelist   RESTORE [label]",
    "READ": "READ variablelist",
    "INKEY$": "INKEY$ - returns the key pressed (\"\" if none; CHR$(0)+scancode for extended keys)",
    "MID$": "MID$(string$, start [, length])\nMID$(stringvariable$, start [, length]) = string$",
    "LEFT$": "LEFT$(string$, n)", "RIGHT$": "RIGHT$(string$, n)", "LEN": "LEN(string$ | variable)",
    "INSTR": "INSTR([start,] string$, search$)", "STR$": "STR$(number)", "VAL": "VAL(string$)",
    "CHR$": "CHR$(code)", "ASC": "ASC(string$)", "UCASE$": "UCASE$(string$)", "LCASE$": "LCASE$(string$)",
    "LTRIM$": "LTRIM$(string$)", "RTRIM$": "RTRIM$(string$)", "SPACE$": "SPACE$(n)", "STRING$": "STRING$(n, {code|string$})",
    "RND": "RND[(n)]  - random number 0 <= x < 1;  RANDOMIZE [seed] (RANDOMIZE TIMER)",
    "RANDOMIZE": "RANDOMIZE [seed]", "TIMER": "TIMER - seconds since midnight; ON TIMER(n) GOSUB label; TIMER ON|OFF|STOP",
    "INT": "INT(x) - largest integer <= x", "FIX": "FIX(x) - truncates", "CINT": "CINT(x) - rounds to INTEGER",
    "CLNG": "CLNG(x)", "SQR": "SQR(x)", "ABS": "ABS(x)", "SGN": "SGN(x)", "EOF": "EOF(filenumber)",
    "LOF": "LOF(filenumber)", "FREEFILE": "FREEFILE", "SWAP": "SWAP variable1, variable2", "END": "END [IF|SELECT|SUB|FUNCTION|TYPE|DEF]",
    "SLEEP": "SLEEP [seconds]", "SHELL": "SHELL [command$]", "CHAIN": "CHAIN file$", "KILL": "KILL filespec$",
    "WIDTH": "WIDTH [columns] [, rows] | WIDTH #n, width", "DECLARE": "DECLARE {SUB|FUNCTION} name [(parameterlist)]",
    "DEF": "DEF FNname[(parameters)] = expression | DEF FNname ... END DEF\nDEF SEG [= segment]",
    "PEEK": "PEEK(address) / POKE address, byte  (after DEF SEG; B800 text memory and A000 in SCREEN 13 are emulated)",
}


class OutputPanel(QPlainTextEdit):
    """Compiler / run-time output with clickable error lines."""

    def __init__(self, qb):
        super().__init__()
        self.qb = qb
        self.setReadOnly(True)
        f = QFont("Consolas" if WINDOWS else "Monospace")
        f.setStyleHint(QFont.StyleHint.TypeWriter)
        self.setFont(f)
        self.setMaximumBlockCount(5000)

    def add(self, text, color=None):
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        if color:
            fmt.setForeground(QColor(color))
        cur.insertText(text + "\n", fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def mouseDoubleClickEvent(self, e):
        line = self.cursorForPosition(e.pos()).block().text()
        self.qb.jump_to_message(line)


class HelpPanel(QWidget):
    def __init__(self, qb):
        super().__init__()
        self.qb = qb
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        bar = QHBoxLayout()
        self.back = QPushButton("◄ Back")
        self.fwd = QPushButton("Forward ►")
        self.contents = QPushButton("Contents")
        self.index = QPushButton("Index")
        self.folder = QPushButton("Help Files...")
        self.folder.setToolTip("Folder with the QB 4.5 help files (QB45ADVR.HLP, QB45QCK.HLP, QB45ENER.HLP)")
        self.search = QLineEdit()
        self.search.setPlaceholderText("keyword (Enter)")
        for w in (self.back, self.fwd, self.contents, self.index, self.folder):
            bar.addWidget(w)
        bar.addWidget(self.search, 1)
        lay.addLayout(bar)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self.on_link)
        f = QFont("Consolas" if WINDOWS else "Monospace")
        f.setStyleHint(QFont.StyleHint.TypeWriter)
        self.view.setFont(f)
        lay.addWidget(self.view)
        self.history = []
        self.pos = -1
        self.back.clicked.connect(lambda: self.go(-1))
        self.fwd.clicked.connect(lambda: self.go(1))
        self.contents.clicked.connect(lambda: self.qb.help_special("contents"))
        self.index.clicked.connect(lambda: self.qb.help_special("index"))
        self.folder.clicked.connect(lambda: self.qb.choose_help_dir())
        self.search.returnPressed.connect(lambda: self.qb.help_keyword(self.search.text()))

    def show_html(self, html, key, push=True):
        self.view.setHtml(html)
        if push:
            self.history = self.history[:self.pos + 1] + [key]
            self.pos = len(self.history) - 1

    def go(self, d):
        p = self.pos + d
        if 0 <= p < len(self.history):
            self.pos = p
            self.qb.show_help_key(self.history[p], push=False)

    def on_link(self, url):
        s = url.toString()
        if s.startswith("qbhelp:"):
            self.qb.show_help_key(s, push=True)
        elif s == "linbasic:sethelp":
            self.qb.choose_help_dir()


EXE_TARGETS = [
    ("linux-window", "Linux \u2013 DOS window"),
    ("linux-term", "Linux \u2013 terminal"),
    ("win-window", "Windows \u2013 DOS window (.exe)"),
    ("win-cmd", "Windows \u2013 cmd console (.exe)"),
]
if WINDOWS:                         # LinBASIC for Windows makes Windows programs only
    EXE_TARGETS = EXE_TARGETS[2:]


class MakeExeDialog(QDialog):
    def __init__(self, parent, exe, opts):
        super().__init__(parent)
        self.setWindowTitle("Make EXE File")
        lay = QFormLayout(self)
        row = QHBoxLayout()
        self.name = QLineEdit(exe)
        b = QPushButton("...")
        b.clicked.connect(self.browse)
        row.addWidget(self.name, 1)
        row.addWidget(b)
        lay.addRow("EXE File Name:", row)
        self.target = QComboBox()
        for key, label in EXE_TARGETS:
            self.target.addItem(label, key)
        cur = opts.get("target") or ("linux-term" if opts.get("console") else "linux-window")
        if WINDOWS and not cur.startswith("win"):
            cur = "win-cmd" if opts.get("console") else "win-window"
        idx = max(0, [k for k, _ in EXE_TARGETS].index(cur) if cur in [k for k, _ in EXE_TARGETS] else 0)
        self.target.setCurrentIndex(idx)
        lay.addRow("Executable type:", self.target)
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #555;")
        lay.addRow(self.hint)
        self.gcc = QCheckBox("Optimise with the system gcc (Linux; needs build-essential)")
        self.gcc.setVisible(not WINDOWS)
        self.gcc.setChecked(opts.get("gcc", False))
        self.crlf = QCheckBox("Write text files with DOS line ends (CR+LF)")
        self.crlf.setChecked(opts.get("crlf", False))
        self._crlf_linux = opts.get("crlf", False)
        self.keepc = QCheckBox("Keep the generated C source")
        for w in (self.gcc, self.crlf, self.keepc):
            lay.addRow(w)
        bb = QDialogButtonBox()
        self.make = bb.addButton("Make EXE", QDialogButtonBox.ButtonRole.AcceptRole)
        self.make_run = bb.addButton("Make EXE and Run", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.run_after = False
        self.make_run.clicked.connect(lambda: setattr(self, "run_after", True))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addRow(bb)
        self.target.currentIndexChanged.connect(self.target_changed)
        self.target_changed()

    def key(self):
        return self.target.currentData()

    def is_windows(self):
        return self.key().startswith("win")

    def is_console(self):
        return self.key() in ("linux-term", "win-cmd")

    def target_changed(self, *_):
        win = self.is_windows()
        name = self.name.text().strip()
        if name:
            root, ext = os.path.splitext(name)
            if win and ext.lower() != ".exe":
                self.name.setText(name + ".exe")
            elif not win and ext.lower() == ".exe":
                self.name.setText(root)
        self.gcc.setEnabled(not win)
        if win:
            self.gcc.setChecked(False)
            self._crlf_linux = self.crlf.isChecked() if self.crlf.isEnabled() else self._crlf_linux
            self.crlf.setChecked(True)
            self.crlf.setEnabled(False)
        else:
            if not self.crlf.isEnabled():
                self.crlf.setChecked(self._crlf_linux)
            self.crlf.setEnabled(True)
        hints = {
            "linux-window": "A Linux program that opens its own DOS screen window (all SCREEN modes).",
            "linux-term": "A Linux program for the terminal (text modes; output can be redirected).",
            "win-window": "A Windows .exe that opens its own DOS screen window (all SCREEN modes). "
                          "Copy it to Windows 7 or later and double-click it.",
            "win-cmd": "A Windows .exe for the cmd.exe console (text modes; graphics modes open a window). "
                       "Copy it to Windows 7 or later and start it from cmd.",
        }
        if WINDOWS:
            bits = "32-bit" if sys.maxsize < 2 ** 32 else "64-bit"
            hints["win-window"] = ("A %s Windows .exe that opens its own DOS screen window (all SCREEN modes). "
                                   "Double-click it to run it." % bits)
            hints["win-cmd"] = ("A %s Windows .exe for the cmd.exe console (text modes; graphics modes "
                                "open a window). Start it from cmd." % bits)
        self.hint.setText(hints[self.key()])

    def browse(self):
        flt = "Windows programs (*.exe);;All files (*)" if self.is_windows() else "All files (*)"
        f, _ = QFileDialog.getSaveFileName(self, "EXE File Name", self.name.text(), flt)
        if f:
            if self.is_windows() and not f.lower().endswith(".exe"):
                f += ".exe"
            self.name.setText(f)


class QBSupport:
    def __init__(self, win):
        self.win = win
        self.S = win.S
        self.proc = None
        self.run_proc = None
        self.helplib = None
        self.help_tried = False
        self.last_exe = None
        self.output = OutputPanel(self)
        self.out_dock = QDockWidget("LinBASIC Output", win)
        self.out_dock.setObjectName("dock_qb_output")
        self.out_dock.setWidget(self.output)
        win.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.out_dock)
        self.out_dock.hide()
        self.help = HelpPanel(self)
        self.help_dock = QDockWidget("LinBASIC Help", win)
        self.help_dock.setObjectName("dock_qb_help")
        self.help_dock.setWidget(self.help)
        win.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.help_dock)
        win.tabifyDockWidget(self.out_dock, self.help_dock)
        self.help_dock.hide()
        self.build_menu()
        self.patch_window()

    # ------------------------------------------------------------- menu
    def act(self, menu, text, fn, key=None):
        a = QAction(text, self.win)
        if key:
            seqs = [QKeySequence(k) for k in (key if isinstance(key, (list, tuple)) else [key])]
            a.setShortcuts(seqs)
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.take_keys(seqs)
        a.triggered.connect(lambda checked=False: fn())
        menu.addAction(a)
        return a

    def take_keys(self, seqs):
        """Remove the keys from Linpad++ actions so the LinBASIC ones win (F1, F2, F5 ...)."""
        combos = {s[0].toCombined() for s in seqs if not s.isEmpty()}
        for a in self.win.actions.values():
            keep = [s for s in a.shortcuts() if s.isEmpty() or s[0].toCombined() not in combos]
            if len(keep) != len(a.shortcuts()):
                a.setShortcuts(keep)
        for v in self.win.views:
            for cmd in v.editor.standardCommands().commands():
                if cmd.key() in combos:
                    cmd.setKey(0)
                if cmd.alternateKey() in combos:
                    cmd.setAlternateKey(0)

    def build_menu(self):
        win = self.win
        mb = win.menuBar()
        m = QMenu("Lin&BASIC", win)
        self.menu = m
        self.act(m, "&Start\tShift+F5", self.start, ["F5", "Shift+F5"])
        self.act(m, "Check S&yntax", self.check, "Ctrl+F5")
        self.act(m, "Modify &COMMAND$...", self.modify_command)
        m.addSeparator()
        self.act(m, "&Make EXE File...", self.make_exe, "Ctrl+Shift+F5")
        self.act(m, "Run Last &EXE", self.run_last)
        self.act(m, "Stop Running Program", self.stop_program, "Ctrl+Break")
        m.addSeparator()
        self.act(m, "New S&UB...", lambda: self.new_proc("SUB"))
        self.act(m, "New &FUNCTION...", lambda: self.new_proc("FUNCTION"))
        self.act(m, "SU&Bs...\tF2", self.subs_dialog, "F2")
        self.act(m, "Next SUB\tShift+F2", self.next_sub, "Shift+F2")
        m.addSeparator()
        hm = m.addMenu("&Help")
        self.act(hm, "&Topic\tF1", self.help_topic, "F1")
        self.act(hm, "&Contents", lambda: self.help_special("contents"))
        self.act(hm, "&Index", lambda: self.help_special("index"))
        hm.addSeparator()
        self.act(hm, "Set Help &Folder...", self.choose_help_dir)
        m.addSeparator()
        self.act(m, "Show &Output Window", lambda: (self.out_dock.show(), self.out_dock.raise_()))
        self.act(m, "Convert QB 4.5 Binary File to Text...", self.convert_binary)
        self.act(m, "About LinBASIC", self.about)
        # insert before the "Window" / "?" menus
        before = None
        for a in mb.actions():
            t = a.text().replace("&", "")
            if t in ("Window", "?", "Settings", "Tools"):
                before = a
                break
        if before is not None:
            mb.insertMenu(before, m)
        else:
            mb.addMenu(m)

    def patch_window(self):
        win = self.win
        orig_read = win.read_file

        def read_file(path, encoding=None):
            if is_qb_file(path) and not encoding:
                with open(path, "rb") as f:
                    data = f.read()
                conv = self.qb45bin()
                if conv and conv.is_qb_binary(data):
                    try:
                        text = conv.decode_qb45_binary(data)
                        QTimer.singleShot(0, lambda: self.output_note(
                            "%s is a QB 4.5 binary (fast load) file; opened as text. "
                            "Saving writes it as a text file." % os.path.basename(path)))
                        return "cp437", text, data
                    except Exception as ex:
                        QTimer.singleShot(0, lambda: self.output_note("Could not decode binary QB file: %s" % ex))
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    return "cp437", data.decode("cp437", errors="replace"), data
            return orig_read(path, encoding)
        win.read_file = read_file
        if hasattr(win, "langdb"):
            pass

    def qb45bin(self):
        try:
            sys.path.insert(0, os.path.join(linbasic_home(), "compiler"))
            from lbc import qb45bin
            return qb45bin
        except Exception:
            return None

    def output_note(self, text, color="#555"):
        self.out_dock.show()
        self.output.add(text, color)

    # ------------------------------------------------------------- compile
    def current_source(self, require_path=False):
        """Save (or write a temp copy of) the current document; returns its path."""
        buf = self.win.buf()
        if buf is None:
            return None
        if buf.path:
            if buf.dirty or getattr(buf, "force_dirty", False):
                if not self.win.save_buffer(buf):
                    return None
            return buf.path
        if require_path:
            if not self.win.save_buffer_as(buf):
                return None
            return buf.path
        ed = self.win.editor()
        path = os.path.join(cache_dir(), "UNTITLED.BAS")
        with open(path, "wb") as f:
            f.write(ed.text().encode("cp437", errors="replace"))
        return path

    def compiler_cmd(self):
        home = linbasic_home()
        lbc = os.path.join(home, "compiler", "lbc.py")
        return [sys.executable, "-I", lbc] if os.path.exists(lbc) else ["lbc"]

    def compile(self, src, exe, extra=None, on_done=None):
        if self.proc is not None and self.proc.state() != QProcess.ProcessState.NotRunning:
            return
        self.clear_marks()
        self.output.clear()
        self.out_dock.show()
        self.output.add("Compiling %s ..." % os.path.basename(src), "#00007f")
        args = self.compiler_cmd()
        args += ["-o", exe] + (extra or []) + [src]
        p = QProcess(self.win)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("LINBASIC_HOME", linbasic_home())
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(os.path.dirname(src))
        p.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.proc = p

        def finished(code, status):
            out = bytes(p.readAll()).decode("utf-8", "replace")
            nerr = 0
            for line in out.splitlines():
                m = ERR_RE.match(line)
                if m:
                    err = m.group("kind") == "error"
                    nerr += err
                    self.output.add(line, "#c00000" if err else "#a06000")
                    self.mark(m.group("file"), int(m.group("line")), m.group("msg"), err)
                elif line.strip():
                    self.output.add(line)
            if code == 0:
                self.output.add("No errors." if exe == os.devnull else "OK: %s" % exe, "#007000")
            else:
                self.output.add("Compilation failed.", "#c00000")
                first = next((l for l in out.splitlines() if ERR_RE.match(l)), None)
                if first:
                    self.jump_to_message(first)
            self.proc = None
            if on_done:
                on_done(code == 0)
        p.finished.connect(finished)
        p.start(args[0], args[1:])

    def exe_for(self, src, temporary=True):
        base = os.path.splitext(os.path.basename(src))[0] + (".exe" if WINDOWS else "")
        if temporary:
            d = os.path.join(cache_dir(), "run")
            os.makedirs(d, exist_ok=True)
            return os.path.join(d, base)
        return os.path.join(os.path.dirname(src), base)

    def opts_args(self, console=None, gcc=None, crlf=None):
        a = []
        if (self.S["qb_console"] if console is None else console):
            a.append("--console")
        if (self.S["qb_gcc"] if gcc is None else gcc):
            a.append("-O")
        if (self.S["qb_crlf"] if crlf is None else crlf):
            a.append("--crlf")
        return a

    def start(self):
        src = self.current_source()
        if not src:
            return
        exe = self.exe_for(src)
        self.compile(src, exe, self.opts_args(), lambda ok: ok and self.run(exe, os.path.dirname(src) if self.win.buf().path else os.path.expanduser("~")))

    def check(self):
        src = self.current_source()
        if not src:
            return
        self.compile(src, os.devnull, ["--check"])

    def make_exe(self):
        src = self.current_source(require_path=True)
        if not src:
            return
        dlg = MakeExeDialog(self.win, self.exe_for(src, temporary=False),
                            {"console": self.S["qb_console"], "gcc": self.S["qb_gcc"], "crlf": self.S["qb_crlf"],
                             "target": self.S["qb_exe_target"]})
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        windows = dlg.is_windows()
        self.S["qb_exe_target"] = dlg.key()
        if WINDOWS:
            self.S["qb_console"] = dlg.is_console()
        if not windows:
            self.S["qb_console"] = dlg.is_console()
            self.S["qb_gcc"] = dlg.gcc.isChecked()
            self.S["qb_crlf"] = dlg.crlf.isChecked()
        exe = dlg.name.text().strip()
        if windows:
            extra = ["--target", "windows"] + (["--console"] if dlg.is_console() else [])
        else:
            extra = self.opts_args()
        extra += ["-C"] if dlg.keepc.isChecked() else []
        run = dlg.run_after
        self.last_exe = exe

        def done(ok):
            if ok:
                self.output.add("Executable created: %s" % exe, "#007000")
                if windows and not WINDOWS:
                    self.output.add("This is a Windows program: copy it to a Windows PC (Windows 7 or later) to run it.", "#00007f")
                if run:
                    self.run(exe, os.path.dirname(exe))
        self.compile(src, exe, extra, done)

    def run_last(self):
        if self.last_exe and os.path.exists(self.last_exe):
            self.run(self.last_exe, os.path.dirname(self.last_exe))
        else:
            self.start()

    def run(self, exe, cwd):
        if self.run_proc is not None and self.run_proc.state() != QProcess.ProcessState.NotRunning:
            self.run_proc.kill()
            self.run_proc.waitForFinished(1000)
        if WINDOWS and self.S["qb_console"]:
            # a console program: its own cmd window, which stays open after the program ends
            import subprocess
            args = shlex.split(self.S["qb_command_args"], posix=False)
            try:
                subprocess.Popen(["cmd.exe", "/k", exe] + args, cwd=cwd, creationflags=CREATE_NEW_CONSOLE)
                self.output.add("Started in a cmd window: %s" % exe, "#007000")
            except OSError as e:
                self.output.add("Could not start %s: %s" % (exe, e), "#c00000")
            return
        if exe.lower().endswith(".exe") and not WINDOWS:
            wine = shutil.which("wine") or shutil.which("wine64")
            if not wine:
                self.output.add("%s is a Windows program. Install Wine to try it here, or copy it to Windows."
                                % os.path.basename(exe), "#a06000")
                return
            args = shlex.split(self.S["qb_command_args"])
            QProcess.startDetached(wine, [exe] + args, cwd)
            self.output.add("Started with Wine: %s" % exe, "#007000")
            return
        p = QProcess(self.win)
        env = host_env()
        if self.S["qb_console"]:
            term = self.find_terminal()
            if term:
                args = shlex.split(self.S["qb_command_args"])
                cmd = term + [exe] + args
                QProcess.startDetached(cmd[0], cmd[1:], cwd)
                self.output.add("Started in terminal: %s" % exe, "#007000")
                return
        p.setProcessEnvironment(env)
        p.setWorkingDirectory(cwd)
        self.run_proc = p
        self.output.add("Running %s" % os.path.basename(exe), "#00007f")

        def finished(code, status):
            try:
                err = bytes(p.readAllStandardError()).decode("utf-8", "replace")
            except RuntimeError:
                return
            for line in err.splitlines():
                m = RT_RE.match(line)
                if m:
                    self.output.add(line, "#c00000")
                    buf = self.win.buf()
                    self.mark(buf.path if buf else None, int(m.group("line")),
                              "Run-time error %s: %s" % (m.group("code"), m.group("msg")), True)
                    self.goto_line(int(m.group("line")))
                elif line.strip():
                    self.output.add(line)
            self.output.add("Program ended (exit code %d)." % code, "#555")
        p.finished.connect(finished)
        p.readyReadStandardOutput.connect(lambda: self.output.add(bytes(p.readAllStandardOutput()).decode("utf-8", "replace").rstrip("\n")))
        args = shlex.split(self.S["qb_command_args"], posix=not WINDOWS)
        p.start(exe, args)

    def find_terminal(self):
        import shutil
        for t, a in (("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]),
                     ("xfce4-terminal", ["-x"]), ("xterm", ["-e"])):
            if shutil.which(t):
                return [t] + a
        return None

    def stop_program(self):
        if self.run_proc is not None and self.run_proc.state() != QProcess.ProcessState.NotRunning:
            self.run_proc.kill()
            self.output.add("Program stopped.", "#c00000")

    def modify_command(self):
        t, ok = QInputDialog.getText(self.win, "Modify COMMAND$", "Command line arguments (COMMAND$):",
                                     text=self.S["qb_command_args"])
        if ok:
            self.S["qb_command_args"] = t

    # ------------------------------------------------------------- errors
    def clear_marks(self):
        for v in self.win.views:
            try:
                v.editor.clearAnnotations()
            except Exception:
                pass

    def mark(self, path, line, msg, is_error):
        buf = self.win.buf()
        if buf is None:
            return
        if path and buf.path and os.path.abspath(path) != os.path.abspath(buf.path) and \
                os.path.basename(path) != "UNTITLED.BAS":
            return
        ed = self.win.editor()
        try:
            ed.annotate(line - 1, ("Error: " if is_error else "Warning: ") + msg, 0)
            ed.setAnnotationDisplay(S.AnnotationDisplay.AnnotationBoxed)
        except Exception:
            pass

    def jump_to_message(self, text):
        m = ERR_RE.match(text.strip())
        if m:
            path = m.group("file")
            if os.path.exists(path) and os.path.basename(path) != "UNTITLED.BAS":
                buf = self.win.buf()
                if not buf or not buf.path or os.path.abspath(buf.path) != os.path.abspath(path):
                    self.win.open_file(path)
            self.goto_line(int(m.group("line")), int(m.group("col")))
            return
        m = RT_RE.match(text.strip())
        if m:
            self.goto_line(int(m.group("line")))

    def goto_line(self, line, col=1):
        ed = self.win.editor()
        ed.setCursorPosition(max(0, line - 1), max(0, col - 1))
        ed.ensureLineVisible(max(0, line - 1))
        ed.setFocus()

    # ------------------------------------------------------------- SUBs
    PROC_RE = re.compile(r"^\s*(?:\d+\s+)?(SUB|FUNCTION)\s+([A-Za-z][\w.]*[$%&!#]?)", re.I | re.M)

    def procs(self):
        text = self.win.editor().text()
        out = []
        for m in self.PROC_RE.finditer(text):
            line = text.count("\n", 0, m.start())
            out.append((m.group(2), m.group(1).upper(), line))
        return out

    def subs_dialog(self):
        d = QDialog(self.win)
        d.setWindowTitle("SUBs")
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel("Choose program item to edit:"))
        lst = QListWidget()
        name = os.path.basename(self.win.buf().path) if self.win.buf() and self.win.buf().path else "Untitled"
        it = QListWidgetItem(name.upper() + "  (module-level code)")
        it.setData(Qt.ItemDataRole.UserRole, 0)
        lst.addItem(it)
        for nm, kind, line in self.procs():
            it = QListWidgetItem("    %s  (%s)" % (nm, kind))
            it.setData(Qt.ItemDataRole.UserRole, line)
            lst.addItem(it)
        lay.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        lay.addWidget(bb)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lst.itemDoubleClicked.connect(lambda *_: d.accept())
        lst.setCurrentRow(0)
        if d.exec() == QDialog.DialogCode.Accepted and lst.currentItem():
            self.goto_line(lst.currentItem().data(Qt.ItemDataRole.UserRole) + 1)

    def next_sub(self):
        ed = self.win.editor()
        cur = ed.getCursorPosition()[0]
        ps = self.procs()
        for nm, kind, line in ps:
            if line > cur:
                self.goto_line(line + 1)
                return
        if ps:
            self.goto_line(ps[0][2] + 1)

    def new_proc(self, kind):
        name, ok = QInputDialog.getText(self.win, "New " + kind, "Name:")
        name = name.strip()
        if not ok or not re.match(r"^[A-Za-z][\w.]*[$%&!#]?$", name):
            return
        ed = self.win.editor()
        text = ed.text()
        eol = "\r\n" if "\r\n" in text else "\n"
        decl = "DECLARE %s %s ()" % (kind, name)
        lines = text.split(eol)
        # put the DECLARE after the last existing DECLARE (or at the top)
        idx = 0
        for i, l in enumerate(lines):
            if re.match(r"^\s*DECLARE\s", l, re.I):
                idx = i + 1
        ed.beginUndoAction()
        ed.insertAt(decl + eol, idx, 0)
        n = ed.lines()
        tail = (eol if not text.endswith(eol) else "") + eol + "%s %s" % (kind, name) + eol + eol + "END %s" % kind + eol
        ed.append(tail)
        ed.endUndoAction()
        self.goto_line(ed.lines() - 2)

    # ------------------------------------------------------------- help
    # The help databases are not part of LinBASIC: the user points LinBASIC at the
    # QB45ADVR.HLP / QB45QCK.HLP / QB45ENER.HLP files of their own QB 4.5 copy.
    def help_dir(self):
        d = self.S["help_path"]
        return d if d and os.path.isdir(d) else None

    @staticmethod
    def open_help_folder(d):
        """Load every QuickHelp database (*.HLP) of folder d; None if there is none."""
        try:
            from . import qbhelp
            names = sorted(f for f in os.listdir(d) if f.upper().endswith(".HLP"))
        except Exception:
            return None
        lib = qbhelp.HelpLibrary()
        for f in names:
            try:
                lib.add_file(os.path.join(d, f))
            except Exception:
                pass
        return lib if lib.databases else None

    def load_help(self):
        if self.helplib is None:
            d = self.help_dir()
            if d:
                self.helplib = self.open_help_folder(d)
        return self.helplib

    def choose_help_dir(self):
        start = self.S["help_path"] or os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(
            self.win, "Folder with the QB 4.5 help files (QB45ADVR.HLP, QB45QCK.HLP, QB45ENER.HLP)", start)
        if not d:
            return
        lib = self.open_help_folder(d)
        if lib is None:
            QMessageBox.warning(self.win, "LinBASIC Help",
                                "No help files were found in\n%s\n\nChoose the folder that contains "
                                "QB45ADVR.HLP, QB45QCK.HLP and QB45ENER.HLP from your QB 4.5 installation." % d)
            return
        self.S["help_path"] = d
        self.helplib = lib
        found = ", ".join(sorted(os.path.basename(db.source or db.name).upper() for db in lib.databases))
        self.output.add("Help files: %s (%s)" % (d, found), "#007000")
        self.help_special("contents")

    def show_help_html(self, html, key, push=True):
        self.help_dock.show()
        self.help_dock.raise_()
        self.help.show_html(html, key, push)

    def show_help_key(self, key, push=True):
        lib = self.load_help()
        if key.startswith("builtin:"):
            self.show_builtin(key[8:], push)
            return
        if lib is None:
            return
        r = lib.parse_href(key)
        if r:
            db, idx = r
            self.show_help_html(lib.topic_html(db, idx), key, push)

    def show_builtin(self, word, push=True):
        import html as _h
        w = word.upper()
        txt = BUILTIN_HELP.get(w) or BUILTIN_HELP.get(w.rstrip("$")) or BUILTIN_HELP.get(w.split(" ")[0])
        if not txt:
            keys = ", ".join(sorted(BUILTIN_HELP))
            txt = "No built-in entry for %s.\n\nBuilt-in entries: %s" % (word, keys)
        body = ("<h3>%s</h3><pre>%s</pre><p><i>Built-in LinBASIC summary.</i> The complete QB 4.5 "
                "reference is shown here once LinBASIC knows where the help files of your own QB 4.5 copy "
                "are (QB45ADVR.HLP, QB45QCK.HLP, QB45ENER.HLP): "
                "<a href='linbasic:sethelp'>Set Help Folder...</a> "
                "(LinBASIC &gt; Help &gt; Set Help Folder).</p>"
                % (_h.escape(word.upper()), _h.escape(txt)))
        self.show_help_html(body, "builtin:" + word, push)

    def help_keyword(self, word, kind=None):
        word = (word or "").strip()
        if not word:
            return
        lib = self.load_help()
        if lib is None:
            self.show_builtin(word)
            return
        r = lib.find_keyword(word, kind)
        if r is None:
            self.show_builtin(word)
            return
        db, idx = r
        key = lib.href(db, idx)
        self.show_help_html(lib.topic_html(db, idx), key)

    def help_special(self, name):
        lib = self.load_help()
        if lib is None:
            self.show_builtin("contents")
            return
        r = lib.contents() if name == "contents" else lib.index()
        if r:
            db, idx = r
            self.show_help_html(lib.topic_html(db, idx), lib.href(db, idx))

    def help_topic(self):
        ed = self.win.editor()
        line, col = ed.getCursorPosition()
        text = ed.text(line)
        lib = self.load_help()
        if lib is not None:
            try:
                r = lib.lookup_at(text, col)
            except Exception:
                r = None
            if r:
                phrase, db, idx = r
                self.show_help_html(lib.topic_html(db, idx), lib.href(db, idx))
                return
        m = None
        for mm in re.finditer(r"[A-Za-z][A-Za-z0-9_.]*[$%&!#]?", text):
            if mm.start() <= col <= mm.end():
                m = mm
        if m:
            self.help_keyword(m.group(0))
        else:
            self.help_special("contents")

    # ------------------------------------------------------------- misc
    def convert_binary(self):
        f, _ = QFileDialog.getOpenFileName(self.win, "QB 4.5 binary .BAS", "", "BASIC (*.bas *.BAS);;All (*)")
        if not f:
            return
        conv = self.qb45bin()
        with open(f, "rb") as fh:
            data = fh.read()
        if not conv or not conv.is_qb_binary(data):
            QMessageBox.information(self.win, "Convert", "This file is not a QB 4.5 binary file.")
            return
        text = conv.decode_qb45_binary(data)
        out, _ = QFileDialog.getSaveFileName(self.win, "Save as text", os.path.splitext(f)[0] + "_TXT.BAS")
        if out:
            with open(out, "wb") as fh:
                fh.write(text.replace("\n", "\r\n").encode("cp437", errors="replace"))
            self.win.open_file(out)

    def about(self):
        from . import VERSION
        QMessageBox.about(self.win, "About LinBASIC",
                          "<b>LinBASIC %s</b> — QB 4.5 compatible BASIC compiler and IDE for Linux and Windows<br><br>"
                          "Compiler: lbc (BASIC → C → native x86-64 via the bundled Tiny C Compiler)<br>"
                          "Runtime: DOS screen emulation (SCREEN 0–13), PC speaker sound, DOS files<br>"
                          "Editor: Linpad++ (Notepad++ for Linux)<br><br>"
                          "© 2026 Demosthenes Koptsis — GPL-3.0-or-later" % VERSION)


def install(win):
    win.qb = QBSupport(win)
    return win.qb
