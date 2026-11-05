from . import _compat
from PyQt5.QtNetwork import *  # noqa: F401,F403
from PyQt5 import QtNetwork as _m
_compat.patch_module(_m)
