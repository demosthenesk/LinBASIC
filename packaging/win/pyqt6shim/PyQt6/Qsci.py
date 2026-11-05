from . import _compat
from PyQt5.Qsci import *  # noqa: F401,F403
from PyQt5 import Qsci as _m
_compat.patch_module(_m)
QsciScintilla = _compat.qsci_class()
