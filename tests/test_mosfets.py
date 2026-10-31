# Batch test (KLayout -z -nc -rx -r): nmos/pmos replacement on the feasibility test layout t1_test.gds
# (klayout_em_export_tests/work, built by its run_all.sh): A nmos ng=1, B nmos ng=4, C nmos R90, D nmos mirrored,
# E pmos ng=2, F rfnmos ng=2, each with a gate contact pad and Metal2 straps (as in T1). Needs the PDK
# (klayout_em_export_tests/pdk_env.py); run with KLAYOUT_PATH/KLAYOUT_HOME pointing to an empty folder.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, TESTS_DIR, tests_data, out_dir

import pya
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(HERE, "..", "python"))   # not via salt here
from pdk_env import load_pdk
from klayout_em_export.devices import device_shapes, find_devices, mark_replaced, port_lines, replace
from klayout_em_export.ports import collect_ports
from klayout_em_export.stackup import Stackup

load_pdk()
st = Stackup(STACKUP)
ly = pya.Layout(); ly.technology_name = "sg13g2"
ly.read(tests_data("work", "t1_test.gds"))
cell = ly.cell("TOP")
dbu = ly.dbu
devices, unknown = find_devices(ly, cell, st)
print("unknown:", unknown)
for d in sorted(devices, key=lambda d: (d.trans.disp.y, d.trans.disp.x)):
    print(f"{d.pcell:7s} {d.id:28s} {d.params} problems {d.problems}")
    for t, (layer, boxes) in sorted(d.terminals.items()):
        print(f"   {t:3s} layer {layer}: {len(boxes)} pin(s) -> lines {[str(l.to_dtype(dbu)) for l in port_lines(d, t)]}")
    if d.gate_trace:
        print("   gate trace:", {l: r.count() for l, r in d.gate_trace.items()})


class NoUndo:
    def transaction(self, text): pass
    def commit(self): pass
    def add_missing_layers(self): pass


print("replace:", replace(NoUndo(), cell, st, devices))
again = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
ports = collect_ports(ly, cell, stackup=st)
for layer, port in sorted(ports.items()):
    print(f"port {port.number}: {port.settings} | {port.shapes} element(s) | metals {sorted(port.available or [])}")
removed = device_shapes(ly, again, st)
print("removed at export:", {l: r.count() for l, r in sorted(removed.items())})
print("REF patches:", [str(s.dbbox()) for s in cell.shapes(ly.find_layer(300, 0)).each()])

# export (ports numbered without gaps) for a gds2palace check of the multielement ports
import json
from klayout_em_export.export import export_flat
from klayout_em_export.ports import export_numbering, port_map, simcfg_ports
from klayout_em_export.simcfg import write_simcfg
OUT = out_dir("mos")
os.makedirs(OUT, exist_ok=True)
gds = os.path.join(OUT, "t1_mos_em.gds")
numbering = export_numbering(ports)
export_flat(ly, cell, st, gds, port_layers=numbering, remove=removed)
if os.path.exists(gds.replace(".gds", ".simcfg")):
    os.remove(gds.replace(".gds", ".simcfg"))
write_simcfg(gds.replace(".gds", ".simcfg"), gds, st.path, cell.name, ports=simcfg_ports(ports, numbering))
json.dump(port_map(ports, numbering), open(gds.replace(".gds", "_portmap.json"), "w"), indent=2)
print("exported", gds)
