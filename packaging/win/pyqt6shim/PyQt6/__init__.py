"""PyQt6 compatibility layer on top of PyQt5 (Qt 5.15).

Used only by the Windows 7 builds of LinBASIC: Qt 6 needs Windows 10, so there the
IDE runs on PyQt5 and imports this package under the name PyQt6.
Copyright (C) 2026 Demosthenes Koptsis. GPL-3.0-or-later."""
from . import _compat  # noqa: F401  (patches PyQt5 once)
