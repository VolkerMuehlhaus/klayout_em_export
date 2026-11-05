# The IHP PDK for the batch tests: the sg13g2 technology and the SG13_dev device library. PDK folder: testpaths.PDK_ROOT.
import os
import sys

import pya

from testpaths import PDK_ROOT

PDK = os.path.join(PDK_ROOT, "ihp-sg13g2", "libs.tech", "klayout")
PYDIR = os.path.join(PDK, "python")
LYT = os.path.join(PDK, "tech", "sg13g2.lyt")


def load_pdk():
    """Register technology and the SG13_dev pcell library (Tcl callbacks bypassed)."""
    if not os.path.isfile(LYT):
        raise FileNotFoundError(f"No such file: {LYT} (run tests/setup_pdk.sh or set IHP_PDK_ROOT)")
    if PYDIR not in sys.path:
        sys.path.insert(0, PYDIR)
        sys.path.insert(0, os.path.join(PYDIR, "pycell4klayout-api", "source", "python"))
    if not pya.Technology.has_technology("sg13g2"):
        pya.Technology.create_technology("sg13g2").load(LYT)
    import cni.dlo
    cni.dlo.PCellWrapper.coerce_parameters = lambda self, layout, v: v
    import sg13g2_pycell_lib  # noqa: F401  registers SG13_dev
    return pya.Library.library_by_name("SG13_dev", "sg13g2")
