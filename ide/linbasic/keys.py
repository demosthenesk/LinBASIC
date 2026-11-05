"""Shortcut handling. Default bindings come from the WinMenuKeyDefinition table
recovered from notepad++.exe (npp_tables.DEFAULT_KEYS); user overrides are kept
in shortcuts.xml using Notepad++'s own format (Windows virtual-key codes)."""
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt, QKeyCombination
from PyQt6.QtGui import QKeySequence

from . import paths
from .npp_tables import DEFAULT_KEYS

K = Qt.Key
VK_TO_QT = {
    0x08: K.Key_Backspace, 0x09: K.Key_Tab, 0x0D: K.Key_Return, 0x1B: K.Key_Escape,
    0x20: K.Key_Space, 0x21: K.Key_PageUp, 0x22: K.Key_PageDown, 0x23: K.Key_End,
    0x24: K.Key_Home, 0x25: K.Key_Left, 0x26: K.Key_Up, 0x27: K.Key_Right, 0x28: K.Key_Down,
    0x2D: K.Key_Insert, 0x2E: K.Key_Delete, 0xBA: K.Key_Semicolon, 0xBB: K.Key_Equal,
    0xBC: K.Key_Comma, 0xBD: K.Key_Minus, 0xBE: K.Key_Period, 0xBF: K.Key_Slash,
    0xC0: K.Key_QuoteLeft, 0xDB: K.Key_BracketLeft, 0xDC: K.Key_Backslash,
    0xDD: K.Key_BracketRight, 0xDE: K.Key_Apostrophe,
    0x6A: K.Key_Asterisk, 0x6B: K.Key_Plus, 0x6D: K.Key_Minus, 0x6E: K.Key_Period, 0x6F: K.Key_Slash,
}
KEYPAD_VK = {0x6A, 0x6B, 0x6D, 0x6E, 0x6F} | set(range(0x60, 0x6A))
for _i in range(10):
    VK_TO_QT[0x30 + _i] = K(K.Key_0.value + _i)
    VK_TO_QT[0x60 + _i] = K(K.Key_0.value + _i)
for _i in range(26):
    VK_TO_QT[0x41 + _i] = K(K.Key_A.value + _i)
for _i in range(24):
    VK_TO_QT[0x70 + _i] = K(K.Key_F1.value + _i)
QT_TO_VK = {}
for vk, qk in VK_TO_QT.items():
    if vk in KEYPAD_VK:
        QT_TO_VK.setdefault(("kp", qk), vk)
    else:
        QT_TO_VK.setdefault(qk, vk)

NAME_TO_QT = {
    "Del": "Del", "Enter": "Return", "Esc": "Esc", "PgUp": "PgUp", "PgDown": "PgDown",
    "Backspace": "Backspace",
}


def seq_from_string(s):
    """'Ctrl+Shift+Num1' / 'Alt+F4' / 'Ctrl+Alt+Enter' -> QKeySequence."""
    if not s:
        return QKeySequence()
    parts = s.split("+")
    key = parts[-1]
    mods = parts[:-1]
    if key == "" and len(parts) >= 2:      # e.g. "Ctrl++"
        key = "+"
        mods = parts[:-2]
    m = Qt.KeyboardModifier.NoModifier
    for p in mods:
        m |= {"Ctrl": Qt.KeyboardModifier.ControlModifier, "Alt": Qt.KeyboardModifier.AltModifier,
              "Shift": Qt.KeyboardModifier.ShiftModifier}.get(p, Qt.KeyboardModifier.NoModifier)
    if key.startswith("Num") and len(key) > 3:
        rest = key[3:]
        qk = {"+": K.Key_Plus, "-": K.Key_Minus, "*": K.Key_Asterisk, "/": K.Key_Slash,
              ".": K.Key_Period}.get(rest)
        if qk is None and rest.isdigit():
            qk = K(K.Key_0.value + int(rest))
        if qk is None:
            return QKeySequence()
        return QKeySequence(QKeyCombination(m | Qt.KeyboardModifier.KeypadModifier, qk))
    name = NAME_TO_QT.get(key, key)
    ks = QKeySequence(name)
    if ks.isEmpty():
        return QKeySequence()
    return QKeySequence(QKeyCombination(m, ks[0].key()))


def seq_from_vk(ctrl, alt, shift, vk):
    qk = VK_TO_QT.get(vk)
    if qk is None:
        return QKeySequence()
    m = Qt.KeyboardModifier.NoModifier
    if ctrl:
        m |= Qt.KeyboardModifier.ControlModifier
    if alt:
        m |= Qt.KeyboardModifier.AltModifier
    if shift:
        m |= Qt.KeyboardModifier.ShiftModifier
    if vk in KEYPAD_VK:
        m |= Qt.KeyboardModifier.KeypadModifier
    return QKeySequence(QKeyCombination(m, qk))


def vk_from_seq(seq):
    """QKeySequence -> (ctrl, alt, shift, vk) for shortcuts.xml."""
    if seq.isEmpty():
        return (False, False, False, 0)
    kc = seq[0]
    m = kc.keyboardModifiers()
    key = kc.key()
    if m & Qt.KeyboardModifier.KeypadModifier:
        vk = QT_TO_VK.get(("kp", key), QT_TO_VK.get(key, 0))
        if K.Key_0.value <= key.value <= K.Key_9.value:
            vk = 0x60 + key.value - K.Key_0.value
    else:
        vk = QT_TO_VK.get(key, 0)
    return (bool(m & Qt.KeyboardModifier.ControlModifier), bool(m & Qt.KeyboardModifier.AltModifier),
            bool(m & Qt.KeyboardModifier.ShiftModifier), vk)


def seq_text(seq):
    if seq.isEmpty():
        return ""
    kc = seq[0]
    m = kc.keyboardModifiers()
    parts = []
    if m & Qt.KeyboardModifier.ControlModifier:
        parts.append("Ctrl")
    if m & Qt.KeyboardModifier.AltModifier:
        parts.append("Alt")
    if m & Qt.KeyboardModifier.ShiftModifier:
        parts.append("Shift")
    kname = QKeySequence(kc.key().value).toString()
    if m & Qt.KeyboardModifier.KeypadModifier:
        kname = "Numpad " + kname
    parts.append(kname)
    return "+".join(parts)


class ShortcutsFile:
    """shortcuts.xml: InternalCommands overrides, Macros, UserDefinedCommands."""

    def __init__(self):
        self.path = paths.cfg("shortcuts.xml")
        self.internal = {}      # id -> [QKeySequence, ...] (empty list = removed)
        self.macros = []        # dicts: name, seq, folder, actions[(type,msg,w,l,s)]
        self.commands = []      # dicts: name, seq, folder, cmd
        self.scintilla = {}     # SCI id -> [seq]
        self.load()

    def load(self):
        try:
            root = ET.parse(self.path).getroot()
        except (ET.ParseError, OSError):
            return
        ic = root.find("InternalCommands")
        if ic is not None:
            for sc in ic.findall("Shortcut"):
                try:
                    cid = int(sc.get("id"))
                    vk = int(sc.get("Key", "0"))
                except (TypeError, ValueError):
                    continue
                seq = seq_from_vk(sc.get("Ctrl") == "yes", sc.get("Alt") == "yes", sc.get("Shift") == "yes", vk)
                self.internal[cid] = [seq] if vk else []
        mac = root.find("Macros")
        if mac is not None:
            for m in mac.findall("Macro"):
                acts = []
                for a in m.findall("Action"):
                    try:
                        acts.append((int(a.get("type", "1")), int(a.get("message", "0")),
                                     int(a.get("wParam", "0")), int(a.get("lParam", "0")), a.get("sParam", "")))
                    except ValueError:
                        pass
                self.macros.append({"name": m.get("name", "macro"), "folder": m.get("FolderName", ""),
                                    "seq": self._seq(m), "actions": acts})
        udc = root.find("UserDefinedCommands")
        if udc is not None:
            for c in udc.findall("Command"):
                self.commands.append({"name": c.get("name", "command"), "folder": c.get("FolderName", ""),
                                      "seq": self._seq(c), "cmd": (c.text or "").strip()})
        sk = root.find("ScintillaKeys")
        if sk is not None:
            for k in sk.findall("ScintKey"):
                try:
                    sid = int(k.get("ScintID"))
                except (TypeError, ValueError):
                    continue
                self.scintilla[sid] = [self._seq(k)]

    @staticmethod
    def _seq(el):
        try:
            vk = int(el.get("Key", "0"))
        except ValueError:
            vk = 0
        return seq_from_vk(el.get("Ctrl") == "yes", el.get("Alt") == "yes", el.get("Shift") == "yes", vk)

    @staticmethod
    def _set_key(el, seq):
        c, a, s, vk = vk_from_seq(seq)
        el.set("Ctrl", "yes" if c else "no")
        el.set("Alt", "yes" if a else "no")
        el.set("Shift", "yes" if s else "no")
        el.set("Key", str(vk))

    def save(self):
        root = ET.Element("NotepadPlus")
        ic = ET.SubElement(root, "InternalCommands")
        for cid, seqs in sorted(self.internal.items()):
            el = ET.SubElement(ic, "Shortcut", id=str(cid))
            self._set_key(el, seqs[0] if seqs else QKeySequence())
        mac = ET.SubElement(root, "Macros")
        for m in self.macros:
            el = ET.SubElement(mac, "Macro", name=m["name"])
            self._set_key(el, m["seq"])
            if m.get("folder"):
                el.set("FolderName", m["folder"])
            for t, msg, w, l, s in m["actions"]:
                ET.SubElement(el, "Action", type=str(t), message=str(msg), wParam=str(w),
                              lParam=str(l), sParam=s)
        udc = ET.SubElement(root, "UserDefinedCommands")
        for c in self.commands:
            el = ET.SubElement(udc, "Command", name=c["name"])
            self._set_key(el, c["seq"])
            if c.get("folder"):
                el.set("FolderName", c["folder"])
            el.text = c["cmd"]
        ET.SubElement(root, "PluginCommands")
        sk = ET.SubElement(root, "ScintillaKeys")
        for sid, seqs in sorted(self.scintilla.items()):
            el = ET.SubElement(sk, "ScintKey", ScintID=str(sid), menuCmdID="0")
            self._set_key(el, seqs[0] if seqs else QKeySequence())
        try:
            ET.indent(root, space="    ")
        except AttributeError:
            pass
        ET.ElementTree(root).write(self.path, encoding="UTF-8", xml_declaration=True)


def default_seqs(cid):
    return [seq_from_string(s) for s in DEFAULT_KEYS.get(cid, [])]
