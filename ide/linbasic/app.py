"""Entry point: Notepad++-compatible command line, single instance, startup."""
import glob
import json
import os
import signal
import sys
from types import SimpleNamespace

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from . import APP_NAME, VERSION, paths, settings

LANG_CODES = {
    "en": "english.xml", "el": "greek.xml", "fr": "french.xml", "de": "german.xml", "es": "spanish.xml",
    "it": "italian.xml", "pt": "portuguese.xml", "pt-br": "brazilian_portuguese.xml", "ru": "russian.xml",
    "uk": "ukrainian.xml", "pl": "polish.xml", "cs": "czech.xml", "sk": "slovak.xml", "hu": "hungarian.xml",
    "ro": "romanian.xml", "bg": "bulgarian.xml", "tr": "turkish.xml", "nl": "dutch.xml", "sv": "swedish.xml",
    "da": "danish.xml", "fi": "finnish.xml", "nb": "norwegian.xml", "nn": "nynorsk.xml", "ja": "japanese.xml",
    "ko": "korean.xml", "zh-cn": "chineseSimplified.xml", "zh-tw": "taiwaneseMandarin.xml",
    "zh-hk": "hongKongCantonese.xml", "he": "hebrew.xml", "ar": "arabic.xml", "fa": "farsi.xml",
    "hr": "croatian.xml", "sr": "serbian.xml", "sl": "slovenian.xml", "lt": "lithuanian.xml",
    "lv": "latvian.xml", "et": "estonian.xml", "ca": "catalan.xml", "eu": "basque.xml", "gl": "galician.xml",
    "vi": "vietnamese.xml", "id": "indonesian.xml", "th": "thai.xml", "hi": "hindi.xml",
}


def parse_args(argv):
    o = SimpleNamespace(multi=False, nosession=False, notabbar=False, ro=False, full_ro=False, line=None,
                        col=None, pos=None, lang=None, loc=None, x=None, y=None, on_top=False,
                        open_session=False, recursive=False, title_add=None, settings_dir=None,
                        folders_ws=False, monitor=False, systray=False, files=[], help=False, version=False)
    for a in argv:
        low = a.lower()
        if a in ("--help", "-h", "-?"):
            o.help = True
        elif a in ("--version", "-v"):
            o.version = True
        elif low == "-multiinst":
            o.multi = True
        elif low == "-nosession":
            o.nosession = True
        elif low == "-notabbar":
            o.notabbar = True
        elif low == "-ro":
            o.ro = True
        elif low == "-fullreadonly":
            o.full_ro = True
        elif low == "-alwaysontop":
            o.on_top = True
        elif low == "-opensession":
            o.open_session = True
        elif a == "-r":
            o.recursive = True
        elif low == "-systemtray":
            o.systray = True
        elif low == "-openfoldersasworkspace":
            o.folders_ws = True
        elif low == "-monitor":
            o.monitor = True
        elif low in ("-noplugin", "-loadingtime", "-quickprint"):
            pass
        elif low.startswith("-titleadd="):
            o.title_add = a.split("=", 1)[1].strip('"')
        elif low.startswith("-settingsdir="):
            o.settings_dir = a.split("=", 1)[1].strip('"')
        elif a.startswith("-n") and a[2:].lstrip("-").isdigit():
            o.line = int(a[2:])
        elif a.startswith("-c") and a[2:].isdigit():
            o.col = int(a[2:])
        elif a.startswith("-p") and a[2:].isdigit():
            o.pos = int(a[2:])
        elif a.startswith("-x") and a[2:].lstrip("-").isdigit():
            o.x = int(a[2:])
        elif a.startswith("-y") and a[2:].lstrip("-").isdigit():
            o.y = int(a[2:])
        elif a.startswith("-L") and len(a) > 2:
            o.loc = a[2:].lower()
        elif a.startswith("-l") and len(a) > 2:
            o.lang = a[2:].lower()
        elif a.startswith("-") and not os.path.exists(a):
            pass
        else:
            o.files.append(a)
    files = []
    for f in o.files:
        f = os.path.expanduser(f)
        if any(ch in f for ch in "*?["):
            files += sorted(glob.glob(f, recursive=o.recursive) if not o.recursive else
                            glob.glob(os.path.join(os.path.dirname(f) or ".", "**", os.path.basename(f)), recursive=True))
        else:
            files.append(os.path.abspath(f))
    o.files = files
    return o


def server_name():
    if os.name == "nt":
        import re as _re
        return "linbasic-" + _re.sub(r"[^A-Za-z0-9_-]", "_", os.environ.get("USERNAME", "user"))
    return "linbasic-%d" % os.getuid()


def send_to_running(o):
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(400):
        return False
    payload = json.dumps({"files": o.files, "line": o.line, "col": o.col, "pos": o.pos, "lang": o.lang,
                          "ro": o.ro, "monitor": o.monitor, "folders_ws": o.folders_ws,
                          "open_session": o.open_session}).encode()
    sock.write(payload)
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def open_requested(win, req):
    lang = req.get("lang")
    if lang and lang not in win.langdb.langs:
        lang = None
    for f in req.get("files", []):
        if req.get("open_session"):
            from . import session
            session.load_session(win, f)
            continue
        if os.path.isdir(f):
            win.open_folder_as_workspace(f)
            continue
        b = win.open_file(f, readonly=req.get("ro", False), line=req.get("line"), col=req.get("col"),
                          pos=req.get("pos"), lang=lang)
        if b is not None and req.get("monitor"):
            win.toggle_monitoring()
    if win.isMinimized() or not win.isVisible():
        win.showNormal()
    win.raise_()
    win.activateWindow()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    o = parse_args(argv)
    if o.help:
        from .cmd_misc import CMDLINE_HELP
        print(CMDLINE_HELP)
        return 0
    if o.version:
        print("%s %s" % (APP_NAME, VERSION))
        return 0
    if o.settings_dir:
        paths.set_config_dir(o.settings_dir)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([sys.argv[0]] + [a for a in argv if a.startswith("-style") or a.startswith("-platform")])
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("LinBASIC")
    app.setDesktopFileName("linbasic")
    # Linpad++ paints its own light/dark palettes (like Notepad++'s dark mode),
    # so use Fusion everywhere instead of the host theme engine
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(paths.icon("linbasic.svg")))
    S = settings.init()
    if o.loc:
        f = LANG_CODES.get(o.loc) or LANG_CODES.get(o.loc.split("-")[0])
        if f:
            S["localization"] = f
    if not o.multi and S["multi_instance"] == "mono":
        if send_to_running(o):
            return 0
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    from .mainwindow import MainWindow
    win = MainWindow(o)
    if o.on_top:
        S["always_on_top"] = True
        win.apply_ui_settings()
    if o.notabbar:
        for v in win.views:
            v.tabs.hide()
    if o.x is not None or o.y is not None:
        win.move(o.x if o.x is not None else win.x(), o.y if o.y is not None else win.y())
    server = None
    if not o.multi:
        QLocalServer.removeServer(server_name())
        server = QLocalServer()
        server.listen(server_name())

        def on_conn():
            s = server.nextPendingConnection()

            def read():
                data = bytes(s.readAll())
                try:
                    req = json.loads(data.decode())
                except ValueError:
                    return
                open_requested(win, req)
            s.readyRead.connect(read)
        server.newConnection.connect(on_conn)
    if S["remember_session"] and not o.nosession:
        from . import session
        session.load_session(win, paths.cfg("session.xml"))
    if o.full_ro:
        S_ro = True
    if o.files:
        if o.folders_ws:
            for f in o.files:
                win.open_folder_as_workspace(f if os.path.isdir(f) else os.path.dirname(f))
        else:
            open_requested(win, {"files": o.files, "line": o.line, "col": o.col, "pos": o.pos, "lang": o.lang,
                                 "ro": o.ro or o.full_ro, "monitor": o.monitor, "open_session": o.open_session})
    if not win.views[0].buffers:
        win.new_document(win.views[0], lang=o.lang if o.lang in win.langdb.langs else None)
    if o.full_ro:
        win.readonly_all(True)
    win.restore_panels()
    if o.systray:
        win.ensure_tray()
        win.hide()
    else:
        win.show()
    win.editor().setFocus()
    win.update_title()
    win.update_status()
    win.sync_check_states()
    win._server = server
    rc = app.exec()
    return rc
