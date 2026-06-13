"""PySide2 / PySide6 compatibility shim.

Maya 2022-2025 ship PySide2 + shiboken2; Maya 2026 ships PySide6 + shiboken6.
Importing through this module lets the rest of the GUI code stay agnostic.

Usage:
    from xgentoue.gui.qtcompat import QtWidgets, QtCore, QtGui, wrapInstance
"""

try:
    from PySide2 import QtWidgets, QtCore, QtGui
    from shiboken2 import wrapInstance, isValid as _isValid
    QT_BINDING = 'PySide2'
except ImportError:  # pragma: no cover - exercised on Maya 2026+
    from PySide6 import QtWidgets, QtCore, QtGui
    from shiboken6 import wrapInstance, isValid as _isValid
    QT_BINDING = 'PySide6'


def isValid(obj):
    """Return True iff ``obj`` is a wrapper around a live C++ object.

    Wraps shiboken's ``isValid`` so callers don't have to know which
    binding is in use. Returns False (rather than raising) for None
    or non-PySide objects so it can be used as a guard in any code
    path that hands references around between event-loop ticks.
    """
    if obj is None:
        return False
    try:
        return bool(_isValid(obj))
    except Exception:
        return False


__all__ = [
    'QtWidgets', 'QtCore', 'QtGui',
    'wrapInstance', 'isValid', 'QT_BINDING',
]
