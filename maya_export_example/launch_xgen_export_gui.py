import os
import sys
d = os.path.dirname(os.path.abspath(__file__))
if d not in sys.path:
    sys.path.insert(0, d)

sys.modules.pop('xgen_export_gui')
sys.modules.pop('export_xgen_strands_and_guides')

import xgen_export_gui
xgen_export_gui.show()
