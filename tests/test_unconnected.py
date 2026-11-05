# Batch test (KLayout -z -nc -rx -r): terminals that connect to no wiring. 50_ghz_mpa_core.gds: the base and
# collector straps are cut (gaps of the old in-plane-port model), so B and C of the npn13G2 float, E is wired.
# 1_St_Core_v1_forEM.gds (cascode): every terminal is wired. Needs the PDK, run like test_devices.py.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, TESTS_DIR, layout_file

import pya
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(HERE, "..", "python"))   # not via salt here
from pdk_env import load_pdk
from klayout_em_export.connectivity import check_ground
from klayout_em_export.devices import find_devices, unconnected_terminals
from klayout_em_export.stackup import Stackup

load_pdk()
st = Stackup(STACKUP)
for path, prefix in ((layout_file("50_ghz_mpa_core.gds"), ""),
                     (layout_file("1_St_Core_v1_forEM.gds"), "Cascode")):
    ly = pya.Layout(); ly.technology_name = "sg13g2"
    ly.read(path)
    cell = next(c for c in ly.top_cells() if not c.name.startswith("$$$") and c.name.startswith(prefix))
    devices = find_devices(ly, cell, st)[0]
    loose = unconnected_terminals(ly, devices, check_ground(ly, cell, st))
    print(os.path.basename(path), "| devices:", len(devices), "| not connected:",
          [f"{t} of {d.pcell}@{d.id.split('@')[1]}" for d, t in loose] or "none")
