"""Language database: Notepad++'s langs.xml + the lexer wiring Notepad++ does in
ScintillaEditView::defineDocType / setXxxLexer, reproduced for the Scintilla
engine embedded in QScintilla."""
import os
import re
import xml.etree.ElementTree as ET

from . import paths

# Notepad++ language menu command id -> langs.xml name (LangType order)
MENU_LANG = {
    46016: "normal", 46028: "actionscript", 46042: "ada", 46064: "asn1", 46009: "asp",
    46033: "asm", 46044: "autoit", 46065: "avs", 46059: "baanc", 46022: "batch",
    46066: "blitzbasic", 46002: "c", 46023: "cs", 46003: "cpp", 46040: "caml",
    46048: "cmake", 46050: "cobol", 46069: "csound", 46056: "coffeescript", 46010: "css",
    46051: "d", 46034: "diff", 46070: "erlang", 46093: "errorlist", 46071: "escript",
    46072: "forth", 46026: "fortran", 46058: "fortran77", 46068: "freebasic",
    46087: "gdscript", 46089: "go", 46052: "gui4cli", 46046: "haskell", 46088: "hollywood",
    46005: "html", 46019: "ini", 46047: "inno", 46061: "ihex", 46004: "java",
    46007: "javascript.js", 46057: "json", 46085: "json5", 46055: "jsp", 46041: "kix",
    46031: "lisp", 46073: "latex", 46024: "lua", 46018: "makefile", 46045: "matlab",
    46086: "mssql", 46074: "mmixal", 46015: "nfo", 46075: "nim", 46076: "nncrontab",
    46029: "nsis", 46014: "objc", 46077: "oscript", 46011: "pascal", 46013: "perl",
    46008: "php", 46036: "postscript", 46053: "powershell", 46035: "props",
    46067: "purebasic", 46012: "python", 46054: "r", 46090: "raku", 46078: "rebol",
    46079: "registry", 46017: "rc", 46037: "ruby", 46080: "rust", 46092: "sas",
    46027: "bash", 46032: "scheme", 46038: "smalltalk", 46081: "spice", 46020: "sql",
    46063: "swift", 46060: "srec", 46030: "tcl", 46062: "tehex", 46025: "tex",
    46091: "toml", 46082: "txt2tags", 46084: "typescript", 46043: "verilog",
    46039: "vhdl", 46021: "vb", 46083: "visualprolog", 46006: "xml", 46049: "yaml",
    46181: "markdown",
}
LANG_MENU = {v: k for k, v in MENU_LANG.items()}

# langs.xml name -> (Scintilla lexer, keyword wiring, style sources, display name)
#   keyword wiring: "generic" = SCI_SETKEYWORDS(i) <- LANG_INDEX i
#                   "cpp" = 0<-instre1, 1<-type1, 3<-type2+instre2  (setCppLexer)
#                   "html" = the hypertext lexer's six embedded keyword sets
_C = "cpp"
LEXERS = {
    "normal": ("null", None, [], "Normal text file"),
    "nfo": ("null", None, [], "MSDOS Style/ASCII Art"),
    "actionscript": ("cpp", _C, ["actionscript"], "Flash ActionScript file"),
    "ada": ("ada", "generic", ["ada"], "Ada file"),
    "asm": ("asm", "generic", ["asm"], "Assembly language source file"),
    "asn1": ("asn1", "generic", ["asn1"], "Abstract Syntax Notation One file"),
    "asp": ("hypertext", "html", ["html", "javascript", "asp"], "Active Server Pages script file"),
    "autoit": ("au3", "generic", ["autoit"], "AutoIt"),
    "avs": ("avs", "generic", ["avs"], "AviSynth scripts files"),
    "baanc": ("baan", "generic", ["baanc"], "BaanC File"),
    "bash": ("bash", "generic", ["bash"], "Unix script file"),
    "batch": ("batch", "generic", ["batch"], "Batch file"),
    "blitzbasic": ("blitzbasic", "generic", ["blitzbasic"], "BlitzBasic file"),
    "c": ("cpp", _C, ["c"], "C source file"),
    "caml": ("caml", "generic", ["caml"], "Categorical Abstract Machine Language"),
    "cmake": ("cmake", "generic", ["cmake"], "CMake file"),
    "cobol": ("COBOL", "generic", ["cobol"], "COmmon Business Oriented Language"),
    "csound": ("csound", "generic", ["csound"], "Csound file"),
    "coffeescript": ("coffeescript", "generic", ["coffeescript"], "CoffeeScript file"),
    "cpp": ("cpp", _C, ["cpp"], "C++ source file"),
    "cs": ("cpp", _C, ["cs"], "C# source file"),
    "css": ("css", "generic", ["css"], "Cascade Style Sheets File"),
    "d": ("d", "generic", ["d"], "D programming language"),
    "diff": ("diff", "generic", ["diff"], "Diff file"),
    "erlang": ("erlang", "generic", ["erlang"], "Erlang file"),
    "errorlist": ("errorlist", "generic", ["errorlist"], "ErrorList"),
    "escript": ("escript", "generic", ["escript"], "ESCRIPT file"),
    "forth": ("forth", "generic", ["forth"], "Forth file"),
    "fortran": ("fortran", "generic", ["fortran"], "Fortran free form source file"),
    "fortran77": ("f77", "generic", ["fortran77"], "Fortran fixed form source file"),
    "freebasic": ("freebasic", "generic", ["freebasic"], "BASIC source file (QB 4.5)"),
    "gdscript": ("python", "generic", ["python"], "GDScript file"),
    "go": ("cpp", _C, ["go"], "Go source file"),
    "gui4cli": ("gui4cli", "generic", ["gui4cli"], "GUI4CLI file"),
    "haskell": ("haskell", "generic", ["haskell"], "Haskell"),
    "hollywood": ("null", None, [], "Hollywood script"),
    "html": ("hypertext", "html", ["html", "javascript", "php", "asp"], "Hyper Text Markup Language file"),
    "ini": ("props", "generic", ["ini"], "MS ini file"),
    "inno": ("inno", "generic", ["inno"], "Inno Setup script"),
    "ihex": ("ihex", "generic", ["ihex"], "Intel HEX binary data"),
    "java": ("cpp", _C, ["java"], "Java source file"),
    "javascript.js": ("cpp", _C, ["javascript.js"], "JavaScript file"),
    "json": ("json", "generic", ["json"], "JSON file"),
    "json5": ("json", "generic", ["json"], "JSON5 file"),
    "jsp": ("hypertext", "html", ["html", "javascript"], "JavaServer Pages script file"),
    "kix": ("kix", "generic", ["kix"], "KiXtart file"),
    "lisp": ("lisp", "generic", ["lisp"], "List Processing language file"),
    "latex": ("latex", "generic", ["latex"], "LaTeX file"),
    "lua": ("lua", "generic", ["lua"], "Lua source File"),
    "makefile": ("makefile", "generic", ["makefile"], "Makefile"),
    "matlab": ("matlab", "generic", ["matlab"], "MATrix LABoratory"),
    "mssql": ("mssql", "generic", ["mssql"], "Microsoft Transact-SQL (SQL Server) file"),
    "mmixal": ("mmixal", "generic", ["mmixal"], "MMIXAL file"),
    "nim": ("nimrod", "generic", ["python"], "Nim file"),
    "nncrontab": ("nncrontab", "generic", ["nncrontab"], "extended crontab file"),
    "nsis": ("nsis", "generic", ["nsis"], "Nullsoft Scriptable Install System script file"),
    "objc": ("cpp", _C, ["objc"], "Objective-C source file"),
    "oscript": ("oscript", "generic", ["oscript"], "OScript source file"),
    "pascal": ("pascal", "generic", ["pascal"], "Pascal source file"),
    "perl": ("perl", "generic", ["perl"], "Perl source file"),
    "php": ("hypertext", "html", ["html", "javascript", "php"], "PHP Hypertext Preprocessor file"),
    "postscript": ("ps", "generic", ["postscript"], "PostScript file"),
    "powershell": ("powershell", "generic", ["powershell"], "Windows PowerShell"),
    "props": ("props", "generic", ["props"], "Properties file"),
    "purebasic": ("purebasic", "generic", ["purebasic"], "PureBasic file"),
    "python": ("python", "generic", ["python"], "Python file"),
    "r": ("r", "generic", ["r"], "R programming language"),
    "raku": ("perl", "generic", ["perl"], "Raku source file"),
    "rebol": ("rebol", "generic", ["rebol"], "REBOL file"),
    "registry": ("registry", "generic", ["registry"], "registry file"),
    "rc": ("cpp", _C, ["rc"], "Windows Resource file"),
    "ruby": ("ruby", "generic", ["ruby"], "Ruby file"),
    "rust": ("rust", "generic", ["rust"], "Rust file"),
    "sas": ("sas", "generic", ["sas"], "SAS file"),
    "scheme": ("lisp", "generic", ["lisp"], "Scheme file"),
    "smalltalk": ("smalltalk", "generic", ["smalltalk"], "Smalltalk file"),
    "spice": ("spice", "generic", ["spice"], "spice file"),
    "sql": ("sql", "generic", ["sql"], "Structured Query Language file"),
    "srec": ("srec", "generic", ["srec"], "Motorola S-Record binary data"),
    "swift": ("cpp", _C, ["swift"], "Swift file"),
    "tcl": ("tcl", "generic", ["tcl"], "Tool Command Language file"),
    "tehex": ("tehex", "generic", ["tehex"], "Tektronix extended HEX binary data"),
    "tex": ("tex", "generic", ["tex"], "TeX file"),
    "toml": ("props", "generic", ["props"], "Tom's Obvious Minimal Language file"),
    "txt2tags": ("txt2tags", "generic", ["txt2tags"], "txt2tags file"),
    "typescript": ("cpp", _C, ["typescript"], "TypeScript file"),
    "vb": ("vb", "generic", ["vb"], "Visual Basic file"),
    "verilog": ("verilog", "generic", ["verilog"], "Verilog file"),
    "vhdl": ("vhdl", "generic", ["vhdl"], "VHSIC Hardware Description Language file"),
    "visualprolog": ("visualprolog", "generic", ["visualprolog"], "Visual Prolog file"),
    "xml": ("xml", "generic", ["xml"], "eXtensible Markup Language file"),
    "yaml": ("yaml", "generic", ["yaml"], "YAML Ain't Markup Language"),
    "markdown": ("markdown", None, ["markdown"], "Markdown file"),
}

# Display names used by the Language menu / status bar short names
MENU_NAMES = {}

KW_INDEX = {"instre1": 0, "instre2": 1, "type1": 2, "type2": 3, "type3": 4,
            "type4": 5, "type5": 6, "type6": 7, "type7": 8}

SGML_KEYWORDS = ("ELEMENT DOCTYPE ATTLIST ENTITY PCDATA CDATA EMPTY SHORTREF USEMAP "
                 "NOTATION IMPLIED NDATA SYSTEM PUBLIC REQUIRED FIXED")

# Scintilla lexer properties Notepad++ sets (ScintillaEditView.cpp)
COMMON_PROPS = {
    "fold": "1", "fold.compact": "0", "fold.comment": "1", "fold.preprocessor": "1",
    "fold.html": "1", "fold.hypertext.comment": "1", "fold.hypertext.heredoc": "1",
    "fold.html.preprocessor": "1", "fold.quotes.python": "1", "fold.at.else": "1",
    "lexer.cpp.allow.dollars": "1", "fold.cpp.comment.explicit": "0",
    "lexer.json.escape.sequence": "1", "lexer.json.allow.comments": "1",
    "lexer.props.allow.initial.spaces": "0", "fold.sql.only.begin": "1",
}
LANG_PROPS = {
    "go": {"lexer.cpp.backquoted.strings": "1"},
    "javascript.js": {"lexer.cpp.backquoted.strings": "1"},
    "typescript": {"lexer.cpp.backquoted.strings": "1"},
    "xml": {"lexer.xml.allow.scripts": "0"},
    "php": {"lexer.html.mako": "0"},
}


class Lang:
    __slots__ = ("name", "ext", "comment_line", "comment_start", "comment_end",
                 "keywords", "tab_settings", "lexer", "wiring", "style_sources", "desc")

    def __init__(self, name):
        self.name = name
        self.ext = []
        self.comment_line = ""
        self.comment_start = ""
        self.comment_end = ""
        self.keywords = {}
        self.tab_settings = None
        lx = LEXERS.get(name, ("null", None, [], name))
        self.lexer, self.wiring, self.style_sources, self.desc = lx


class LangDB:
    def __init__(self):
        self.langs = {}
        self.ext_map = {}
        self.load()

    def load(self):
        path = paths.user_or_model("langs.xml", "langs.model.xml")
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            root = ET.parse(paths.data("langs.model.xml")).getroot()
        for el in root.iter("Language"):
            name = el.get("name")
            lg = Lang(name)
            lg.ext = [e.lower() for e in (el.get("ext") or "").split()]
            lg.comment_line = el.get("commentLine") or ""
            lg.comment_start = el.get("commentStart") or ""
            lg.comment_end = el.get("commentEnd") or ""
            ts = el.get("tabSettings")
            if ts and ts.lstrip("-").isdigit():
                v = int(ts)
                if v >= 0:
                    lg.tab_settings = (v & 0x7F, bool(v & 0x80))
            for kw in el.findall("Keywords"):
                lg.keywords[kw.get("name")] = " ".join((kw.text or "").split())
            self.langs[name] = lg
        md = Lang("markdown")
        md.ext = ["md", "markdown", "mkd", "mdown"]
        md.comment_start, md.comment_end = "<!--", "-->"
        self.langs["markdown"] = md
        self.ext_map = {}
        for lg in self.langs.values():
            if lg.name in ("javascript", "searchResult"):
                continue
            for e in lg.ext:
                self.ext_map.setdefault(e, lg.name)

    def get(self, name):
        return self.langs.get(name) or self.langs["normal"]

    def menu_langs(self):
        return [n for n in MENU_LANG.values() if n in self.langs]

    def detect(self, path, head=b""):
        """Pick a language from file name, then from the first line (shebang,
        <?xml, <?php, <!DOCTYPE html) — the order Notepad++ uses."""
        base = os.path.basename(path or "")
        low = base.lower()
        special = {"makefile": "makefile", "gnumakefile": "makefile", "cmakelists.txt": "cmake",
                   "sconstruct": "python", "sconscript": "python", "rakefile": "ruby",
                   "gemfile": "ruby", ".bashrc": "bash", ".bash_profile": "bash",
                   ".profile": "bash", ".zshrc": "bash", "pkgbuild": "bash",
                   "dockerfile": "bash", ".gitconfig": "props", ".editorconfig": "props"}
        if low in special:
            return special[low]
        if "." in low:
            ext = low.rsplit(".", 1)[1]
            if ext in self.ext_map:
                return self.ext_map[ext]
        first = head.split(b"\n", 1)[0].strip().lower() if head else b""
        if first.startswith(b"\xef\xbb\xbf"):
            first = first[3:]
        if first.startswith(b"#!"):
            for key, lang in ((b"python", "python"), (b"bash", "bash"), (b"/sh", "bash"),
                              (b"zsh", "bash"), (b"perl", "perl"), (b"ruby", "ruby"),
                              (b"node", "javascript.js"), (b"php", "php"), (b"lua", "lua"),
                              (b"tcl", "tcl"), (b"raku", "raku"), (b"pwsh", "powershell")):
                if key in first:
                    return lang
        if first.startswith(b"<?xml"):
            return "xml"
        if first.startswith(b"<?php"):
            return "php"
        if first.startswith(b"<!doctype html") or first.startswith(b"<html"):
            return "html"
        return None

    # ------------------------------------------------------------------ lexer
    def keyword_lists(self, lang, styles=None):
        """Return {index: words} for SCI_SETKEYWORDS, merging the user keywords
        stored in the stylers' WordsStyle text like getCompleteKeywordList()."""
        lg = self.get(lang)
        out = {}

        def merged(lname, kwclass):
            words = self.get(lname).keywords.get(kwclass, "")
            if styles is not None:
                extra = styles.user_keywords(lname, kwclass)
                if extra:
                    words = (words + " " + extra).strip()
            return words

        if lg.wiring == "cpp":
            out[0] = merged(lang, "instre1")
            out[1] = merged(lang, "type1")
            out[3] = (merged(lang, "type2") + " " + merged(lang, "instre2")).strip()
        elif lg.wiring == "html":
            out[0] = merged("html", "instre1")
            out[1] = merged("javascript", "instre1")
            out[2] = merged("vb", "instre1")
            out[3] = merged("python", "instre1")
            out[4] = merged("php", "instre1")
            out[5] = SGML_KEYWORDS
        elif lg.wiring == "generic":
            src = lang
            for cls, idx in KW_INDEX.items():
                w = merged(src, cls)
                if w:
                    out[idx] = w
        return out

    def props(self, lang):
        p = dict(COMMON_PROPS)
        p.update(LANG_PROPS.get(lang, {}))
        return p
