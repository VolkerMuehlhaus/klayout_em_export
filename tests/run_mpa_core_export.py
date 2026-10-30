# Export 50_ghz_mpa_core.gds for a Palace comparison with gds2palace's core_transistor_3port_bce example: pad ports
# 1-2 (Metal3 -> TopMetal2, as in the example), the npn13G2 replaced by ports (B, C, E). Stackup and settings as the
# example. Output folder: environment OUT. Needs the PDK (klayout_em_export_tests/pdk_env.py), run like test_devices.py.
import json
import os
import sys
import pya
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "klayout_em_export_tests"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from pdk_env import load_pdk
from klayout_em_export.devices import device_shapes, find_devices, mark_replaced, replace
from klayout_em_export.export import export_flat
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports, export_numbering, port_map, simcfg_ports
from klayout_em_export.simcfg import write_simcfg
from klayout_em_export.stackup import Stackup

EX = r"D:\github-claude\gds2palace_ihp_sg13g2\more_examples\core_transistor_3port_bce"
OUT = os.environ["OUT"]
os.makedirs(OUT, exist_ok=True)
load_pdk()
st = Stackup(os.path.join(EX, "SG13G2_100um_bce_ports.xml"))
ly = pya.Layout(); ly.technology_name = "sg13g2"
ly.read(r"D:\github-claude\klayout_em_export_tests\testcases\50_ghz_mpa_core.gds")
cell = next(c for c in ly.top_cells() if not c.name.startswith("$$$"))
for layer in (201, 202):        # pad ports as in the example
    for shape in cell.shapes(ly.find_layer(layer, 0)).each():
        shape.set_property(PROP_KEY, PortSettings("Z", "Metal3", "TopMetal2").encode())


class NoUndo:
    def transaction(self, text): pass
    def commit(self): pass
    def add_missing_layers(self): pass


replace(NoUndo(), cell, st, find_devices(ly, cell, st)[0])
devices = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
ports = collect_ports(ly, cell, stackup=st)
numbering = export_numbering(ports)
gds = os.path.join(OUT, "mpa_core_npn_em.gds")
export_flat(ly, cell, st, gds, port_layers=numbering, remove=device_shapes(ly, devices, st))
write_simcfg(gds.replace(".gds", ".simcfg"), gds, st.path, cell.name, ports=simcfg_ports(ports, numbering))
pm = port_map(ports, numbering)
json.dump(pm, open(gds.replace(".gds", "_portmap.json"), "w"), indent=2)
for row in pm["ports"]:
    print(row["port"], "<- layout", row["layout_port"], row.get("terminal", ""), "simulated" if row["in_simcfg"] else "shape only",
          row["settings"])
