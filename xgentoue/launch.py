#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""XgenToUE launcher.

Single public entry point :func:`load` opens the XgenToUE tool window.
The shelf button installed by ``install.py`` calls this function.
"""


def load():
    try:
        from xgentoue.gui.main_window import show
        show()
    except Exception:
        import traceback
        msg = traceback.format_exc()
        print(msg)
        try:
            from xgentoue.gui.qtcompat import QtWidgets
            QtWidgets.QMessageBox.critical(None, 'XgenToUE', msg)
        except Exception:
            pass
