"""Where Linpad++ keeps its read-only data and the user's settings."""
import os
import shutil

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
RES_DIR = os.path.join(APP_DIR, "res")
ICON_DIR = os.path.join(RES_DIR, "icons")

_config_override = None


def set_config_dir(path):
    global _config_override
    _config_override = os.path.abspath(os.path.expanduser(path))


def config_dir():
    if _config_override:
        d = _config_override
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        d = os.path.join(base, "linbasic")
        old = os.path.join(base, "linqb")          # settings of the first release (named LinQB)
        if not os.path.exists(d) and os.path.isdir(old):
            try:
                shutil.copytree(old, d)
            except OSError:
                pass
    os.makedirs(d, exist_ok=True)
    return d


def cfg(*parts):
    return os.path.join(config_dir(), *parts)


def data(*parts):
    return os.path.join(DATA_DIR, *parts)


def icon(name):
    return os.path.join(ICON_DIR, name)


def ensure_user_files():
    """First-run copy of the editable config files, mirroring Notepad++'s
    %APPDATA%\\Notepad++ layout (stylers.xml, langs.xml, contextMenu.xml,
    shortcuts.xml, themes/, userDefineLangs/, backup/)."""
    d = config_dir()
    pairs = [("stylers.model.xml", "stylers.xml"), ("langs.model.xml", "langs.xml"),
             ("contextMenu.xml", "contextMenu.xml"), ("shortcuts.xml", "shortcuts.xml")]
    for src, dst in pairs:
        target = os.path.join(d, dst)
        if not os.path.exists(target):
            try:
                shutil.copyfile(data(src), target)
            except OSError:
                pass
    for sub in ("themes", "userDefineLangs", "backup", "plugins", "plugins/Config"):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
    return d


def user_or_model(user_name, model_name):
    p = cfg(user_name)
    return p if os.path.exists(p) else data(model_name)


def theme_dirs():
    return [data("themes"), cfg("themes")]


def list_themes():
    """Return [(display_name, path)] with the default stylers first."""
    out = [("Default (stylers.xml)", user_or_model("stylers.xml", "stylers.model.xml"))]
    seen = set()
    for d in theme_dirs():
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d), key=str.lower):
            if f.lower().endswith(".xml") and f not in seen:
                seen.add(f)
                out.append((f[:-4], os.path.join(d, f)))
    # a user copy overrides the bundled one with the same name
    final = {}
    for name, path in out:
        final[name] = path
    return list(final.items())
