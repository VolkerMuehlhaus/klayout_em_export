# Export the user's cascode 1_St_Core_v1_forEM.gds for a Palace test run: the saved replacement (made before the REF
# patches followed the pins) is undone and redone with the resistors included. Ports numbered without gaps: pads,
# transistors, resistors. Output folder: environment OUT. Needs the PDK (klayout_em_export_tests/pdk_env.py), run
# like test_devices.py. Adds a port at the Cas_Bias pin.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, TESTS_DIR, palace_testcases
import json
import pya
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from pdk_env import load_pdk
from klayout_em_export.devices import device_shapes, find_devices, mark_replaced, replace, touching_patches, unreplace
from klayout_em_export.export import export_flat
from klayout_em_export.ports import collect_ports, export_numbering, port_map, port_problems, simcfg_ports
from klayout_em_export.simcfg import write_simcfg
from klayout_em_export.stackup import Stackup

OUT = os.environ["OUT"]
os.makedirs(OUT, exist_ok=True)
load_pdk()
st = Stackup(STACKUP)
ly = pya.Layout(); ly.technology_name = "sg13g2"
ly.read(palace_testcases("klayout_export", "1_St_Core_v1_forEM.gds"))
cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))


class NoUndo:
    def transaction(self, text): pass
    def commit(self): pass
    def add_missing_layers(self): pass


print("undo the saved replacement:", unreplace(NoUndo(), cell), "shape(s)")
print("replace:", replace(NoUndo(), cell, st, find_devices(ly, cell, st)[0], include_resistors=True))
devices = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
print("touching patches:", touching_patches(ly, cell, st))
# a port at the Cas_Bias pin (Metal2 stub at the left cell edge, under the Metal5 ground plane), so the circuit can
# be biased: via port along the stub's edge, Metal2 -> Metal5
from klayout_em_export.locate import next_port_layer
from klayout_em_export.ports import PROP_KEY, PortSettings
bias_layer = next_port_layer(ly, cell)
cell.shapes(ly.layer(bias_layer, 0)).insert(pya.DBox(-29.205, 8.34, -29.205, 10.97).to_itype(ly.dbu),
                                            ly.properties_id([[PROP_KEY, PortSettings("Z", "Metal2", "Metal5").encode()]]))
print("Cas_Bias port on layer", bias_layer)
ports = collect_ports(ly, cell, stackup=st)
problems = {p.number: port_problems(p, st) for p in ports.values() if port_problems(p, st)}
print("port problems:", problems)
numbering = export_numbering(ports)
gds = os.path.join(OUT, "cascode_em.gds")
export_flat(ly, cell, st, gds, port_layers=numbering, remove=device_shapes(ly, devices, st))
if os.path.exists(gds.replace(".gds", ".simcfg")):
    os.remove(gds.replace(".gds", ".simcfg"))
from klayout_em_export.connectivity import check_ground, port_nets
from klayout_em_export.ports import export_directions
nets = port_nets(ports, check_ground(ly, cell, st, ports=ports))
directions = export_directions(ports, nets, st)
write_simcfg(gds.replace(".gds", ".simcfg"), gds, st.path, cell.name, ports=simcfg_ports(ports, numbering, directions))
pm = port_map(ports, numbering, devices, nets, directions)
json.dump(pm, open(gds.replace(".gds", "_portmap.json"), "w"), indent=2)
for row in pm["ports"]:
    print(row["port"], "<- layout", row["layout_port"], row.get("device", "").split("@")[0], row.get("terminal", ""),
          "" if row["in_simcfg"] else "(shape only)", row["settings"], "exported", row.get("direction"),
          "signal", row.get("signal_layer"))
