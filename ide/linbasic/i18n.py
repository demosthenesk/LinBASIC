"""Notepad++ localization files (localization/*.xml) applied by command ID."""
import os
import xml.etree.ElementTree as ET

from . import paths


class Localization:
    def __init__(self, filename="english.xml"):
        self.filename = filename
        self.commands = {}
        self.menus = {}
        self.submenus = {}
        self.find = {}
        self.rtl = False
        self.name = "English"
        self.load(filename)

    def load(self, filename):
        self.commands.clear()
        self.menus.clear()
        self.submenus.clear()
        self.find.clear()
        path = paths.data("localization", filename)
        if filename == "english.xml" or not os.path.exists(path):
            path = paths.data("localization", "english.xml")
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            return
        nl = root.find("Native-Langue")
        if nl is None:
            return
        self.name = nl.get("name", "")
        self.rtl = nl.get("RTL", "no") == "yes"
        menu = nl.find("Menu")
        if menu is not None:
            main = menu.find("Main")
            if main is not None:
                for it in main.iter("Item"):
                    if it.get("menuId"):
                        self.menus[it.get("menuId")] = it.get("name")
                    elif it.get("subMenuId"):
                        self.submenus[it.get("subMenuId")] = it.get("name")
                    elif it.get("id"):
                        try:
                            self.commands[int(it.get("id"))] = it.get("name")
                        except ValueError:
                            pass
        dlg = nl.find("Dialog")
        if dlg is not None:
            fd = dlg.find("Find")
            if fd is not None:
                for k in ("titleFind", "titleReplace", "titleFindInFiles", "titleFindInProjects", "titleMark"):
                    if fd.get(k):
                        self.find[k] = fd.get(k)
                for it in fd.iter("Item"):
                    if it.get("id") and it.get("name"):
                        self.find[it.get("id")] = it.get("name")

    def cmd(self, cid, default):
        t = self.commands.get(cid, default)
        return _brand(t) if cid in SELF_CMDS else t

    def menu(self, mid, default):
        return self.menus.get(mid, default)

    def sub(self, sid, default):
        t = self.submenus.get(sid, default) if sid else default
        return _brand(t) if sid in SELF_SUBS else t


# menu entries that name the editor itself ("About Notepad++", "Read-Only in
# Notepad++"); links to the Notepad++ website keep their upstream names
SELF_CMDS = {47000, 47006}
SELF_SUBS = {"edit-readonlyInNotepad++"}


def _brand(text):
    from . import APP_NAME
    return text.replace("Notepad++", APP_NAME) if text else text


def available():
    """[(display name, filename)] sorted by name."""
    out = []
    d = paths.data("localization")
    for f in os.listdir(d):
        if not f.endswith(".xml"):
            continue
        try:
            for ev, el in ET.iterparse(os.path.join(d, f), events=("start",)):
                if el.tag == "Native-Langue":
                    out.append((el.get("name") or f[:-4], f))
                    break
        except ET.ParseError:
            out.append((f[:-4], f))
    out.sort(key=lambda x: x[0].lower())
    return out
