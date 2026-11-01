# Export 50_ghz_mpa_core.gds for a Palace comparison with gds2palace's core_transistor_3port_bce example: pad ports
# 1-2 (Metal3 -> TopMetal2, as in the example), the npn13G2 replaced by ports (B, C, E). Stackup and settings as the
# example. Output folder: environment OUT. Needs the PDK (klayout_em_export_tests/pdk_env.py), run like test_devices.py.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import EXAMPLE_BCE, TESTS_DIR, tests_data
import json
import pya
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from pdk_env import load_pdk
from klayout_em_export import tech
from klayout_em_export.devices import find_devices, mark_replaced, replace
from klayout_em_export.pipeline import NoUndo, export_em
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports
from klayout_em_export.stackup import Stackup

EX = EXAMPLE_BCE
OUT = os.environ["OUT"]
os.makedirs(OUT, exist_ok=True)
load_pdk()
st = Stackup(os.path.join(EX, "SG13G2_100um_bce_ports.xml"))
ly = pya.Layout(); ly.technology_name = "sg13g2"
ly.read(tests_data("testcases", "50_ghz_mpa_core.gds"))
cell = next(c for c in ly.top_cells() if not c.name.startswith("$$$"))
for layer in (201, 202):        # pad ports as in the example
    for shape in cell.shapes(ly.find_layer(layer, 0)).each():
        shape.set_property(PROP_KEY, PortSettings("Z", "Metal3", "TopMetal2").encode())


replace(NoUndo(), cell, st, find_devices(ly, cell, st)[0])
devices = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
ports = collect_ports(ly, cell, stackup=st)
gds = os.path.join(OUT, "mpa_core_npn_em.gds")
pm = json.load(open(export_em(ly, cell, st, gds, tech.for_layout(ly)[0])["portmap"]))     # as the GUI's export
for row in pm["ports"]:
    print(row["port"], "<- layout", row["layout_port"], row.get("terminal", ""), "simulated" if row["in_simcfg"] else "shape only",
          row["settings"])
