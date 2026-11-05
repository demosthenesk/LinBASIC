from . import _compat
from PyQt5.QtGui import *  # noqa: F401,F403
from PyQt5 import QtGui as _m
_compat.patch_module(_m)
from PyQt5.QtWidgets import QAction, QActionGroup, QShortcut, QUndoStack, QUndoCommand, QFileSystemModel  # noqa: F401
