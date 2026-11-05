"""Patches that give PyQt5 the parts of the PyQt6 API the IDE uses."""
import PyQt5
from PyQt5 import QtCore, QtGui, QtWidgets

try:
    from PyQt5 import sip
except ImportError:  # pragma: no cover
    import sip

_ENUMTYPE = type(QtCore.Qt.Key)          # sip.enumtype
_value = property(lambda self: int(self))


def _patch_enums(owner, seen):
    for name in dir(owner):
        if name.startswith('__'):
            continue
        try:
            obj = getattr(owner, name)
        except Exception:
            continue
        if not isinstance(obj, type) or obj in seen:
            continue
        seen.add(obj)
        if type(obj) is _ENUMTYPE:
            try:
                obj.value = _value
            except Exception:
                pass
        elif obj.__module__.startswith('PyQt5') and hasattr(obj, '__int__') and name[:1].isupper() \
                and not hasattr(obj, 'value') and obj.__name__ != obj.__qualname__:
            try:                                   # QFlags types (e.g. Qt.KeyboardModifiers)
                obj.value = _value
            except Exception:
                pass
        if obj.__module__.startswith('PyQt5'):
            _patch_enums(obj, seen)


def patch_module(mod, seen=set()):
    _patch_enums(mod, seen)


# ---- QKeyCombination -------------------------------------------------------
_MODMASK = int(QtCore.Qt.KeyboardModifierMask)


class QKeyCombination(int):
    """Qt 6 QKeyCombination as an int (what Qt 5 uses for a key + modifiers)."""
    def __new__(cls, a=0, b=None):
        if b is None:
            return int.__new__(cls, int(a))
        return int.__new__(cls, int(a) | int(b))

    def toCombined(self):
        return int(self)

    def key(self):
        return QtCore.Qt.Key(int(self) & ~_MODMASK)

    def keyboardModifiers(self):
        return QtCore.Qt.KeyboardModifiers(int(self) & _MODMASK)

    @staticmethod
    def fromCombined(v):
        return QKeyCombination(v)


QtCore.QKeyCombination = QKeyCombination

_ks_getitem = QtGui.QKeySequence.__getitem__
QtGui.QKeySequence.__getitem__ = lambda self, i: QKeyCombination(_ks_getitem(self, i))

_qkeyevent_key = QtGui.QKeyEvent.key
QtGui.QKeyEvent.keyCombination = lambda self: QKeyCombination(int(self.modifiers()), self.key())

# ---- events: Qt 6 position() / globalPosition() ---------------------------
for _cls in (QtGui.QMouseEvent, QtGui.QWheelEvent, QtGui.QDropEvent, QtGui.QHoverEvent):
    if hasattr(_cls, 'posF'):
        _cls.position = lambda self: self.posF()
    elif hasattr(_cls, 'localPos'):
        _cls.position = lambda self: self.localPos()
    if hasattr(_cls, 'globalPosF'):
        _cls.globalPosition = lambda self: self.globalPosF()
    elif hasattr(_cls, 'screenPos'):
        _cls.globalPosition = lambda self: self.screenPos()
QtGui.QMouseEvent.position = lambda self: self.localPos()
QtGui.QMouseEvent.globalPosition = lambda self: self.screenPos()
QtGui.QDropEvent.position = lambda self: QtCore.QPointF(self.pos())
QtGui.QWheelEvent.position = lambda self: self.posF()
QtGui.QWheelEvent.globalPosition = lambda self: self.globalPosF()
QtGui.QEnterEvent.position = lambda self: self.localPos()

# ---- QFontDatabase: static in Qt 6 ----------------------------------------
_fdb = None


def _fontdb():
    global _fdb
    if _fdb is None:
        _fdb = QtGui.QFontDatabase()
    return _fdb


class _FDBMeta(type(QtGui.QFontDatabase)):
    pass


for _n in ('families', 'styles', 'isFixedPitch', 'pointSizes', 'smoothSizes', 'writingSystems',
           'isScalable', 'isSmoothlyScalable', 'isBitmapScalable', 'weight', 'bold', 'italic', 'font'):
    _orig = getattr(QtGui.QFontDatabase, _n, None)
    if _orig is None:
        continue

    def _mk(orig):
        def f(*a):
            if a and isinstance(a[0], QtGui.QFontDatabase):
                return orig(*a)
            return orig(_fontdb(), *a)
        return staticmethod(f)
    setattr(QtGui.QFontDatabase, _n, _mk(_orig))

# ---- classes that moved from QtWidgets to QtGui in Qt 6 --------------------
for _n in ('QAction', 'QActionGroup', 'QShortcut', 'QUndoStack', 'QUndoCommand',
           'QFileSystemModel'):
    if hasattr(QtWidgets, _n):
        setattr(QtGui, _n, getattr(QtWidgets, _n))

# ---- misc ------------------------------------------------------------------
if not hasattr(QtWidgets.QApplication, 'exec'):
    QtWidgets.QApplication.exec = QtWidgets.QApplication.exec_
QtCore.pyqtSignal = QtCore.pyqtSignal
QtCore.QT_VERSION_STR = QtCore.QT_VERSION_STR

_seen = set()
for _m in (QtCore, QtGui, QtWidgets):
    _patch_enums(_m, _seen)


# ---- QScintilla: document pointers ------------------------------------------
# SendScintilla() passes and returns C "long", which is 32 bits on 64-bit Windows: Scintilla
# document pointers would be cut in half there. PyQt6.Qsci.QsciScintilla is therefore a subclass
# that sends those messages through Scintilla's direct function (see Qsci.py).
def qsci_class():
    import ctypes
    import sys
    from PyQt5 import Qsci
    base = Qsci.QsciScintilla
    if sys.platform != "win32" or sys.maxsize <= 2 ** 32:
        return base
    B = Qsci.QsciScintillaBase
    PTR_MSGS = {B.SCI_GETDOCPOINTER, B.SCI_CREATEDOCUMENT, B.SCI_SETDOCPOINTER,
                B.SCI_ADDREFDOCUMENT, B.SCI_RELEASEDOCUMENT}
    FN = ctypes.CFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)

    class QsciScintilla(base):
        _direct = None

        def SendScintilla(self, msg, *args):
            if msg in PTR_MSGS and all(isinstance(a, int) for a in args):
                if self._direct is None:
                    self._direct = (FN(int(self.SendScintillaPtrResult(B.SCI_GETDIRECTFUNCTION))),
                                    int(self.SendScintillaPtrResult(B.SCI_GETDIRECTPOINTER)))
                fn, ptr = self._direct
                return fn(ptr, msg, args[0] if args else 0, args[1] if len(args) > 1 else 0)
            return super().SendScintilla(msg, *args)
    return QsciScintilla
