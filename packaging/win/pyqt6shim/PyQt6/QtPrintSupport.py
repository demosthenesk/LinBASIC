from . import _compat
from PyQt5.QtPrintSupport import *  # noqa: F401,F403
from PyQt5 import QtPrintSupport as _m
_compat.patch_module(_m)
