from . import _compat
from PyQt5.QtCore import *  # noqa: F401,F403
from PyQt5 import QtCore as _m
_compat.patch_module(_m)
QKeyCombination = _compat.QKeyCombination
