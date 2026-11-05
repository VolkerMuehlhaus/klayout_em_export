# Batch test (KLayout -z -nc -rx -r): optional resistor replacement on the user's 1_St_Core_v1.gds (cascode: two
# npn13G2 pcells, two cmim pcells (never replaced), one rhigh as a static Cadence cell rhigh_CDNS_...). Needs the
# PDK (tests/pdk_env.py); run with KLAYOUT_PATH/KLAYOUT_HOME pointing to an empty folder.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, TESTS_DIR, layout_file

import pya
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(HERE, "..", "python"))   # not via salt here
from pdk_env import load_pdk
from klayout_em_export.devices import device_shapes, find_devices, mark_replaced, port_lines, replace
from klayout_em_export.pipeline import NoUndo   # a standalone layout in batch mode has no undo manager
from klayout_em_export.ports import collect_ports, device_of
from klayout_em_export.stackup import Stackup

load_pdk()
st = Stackup(STACKUP)
ly = pya.Layout(); ly.technology_name = "sg13g2"
ly.read(layout_file("1_St_Core_v1.gds"))
cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))
dbu = ly.dbu


devices, unknown = find_devices(ly, cell, st)
print("unknown:", unknown)
for d in devices:
    print(f"{d.pcell:8s} resistor={d.is_resistor} {d.id} {d.params} problems {d.problems}")
    for t, (layer, boxes) in sorted(d.terminals.items()):
        print(f"   {t:6s}: lines {[str(l.to_dtype(dbu)) for l in port_lines(d, t)]}")
print("Replace All without resistors:", replace(NoUndo(), cell, st, devices))
devices = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
print("Replace All with resistors:", replace(NoUndo(), cell, st, devices, include_resistors=True))
devices = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
print("replaced:", [(d.pcell, d.replaced, d.ports) for d in devices])
res = next(d for d in devices if d.is_resistor)
for layer, port in sorted(collect_ports(ly, cell, stackup=st).items()):
    if device_of(port) and device_of(port)[0] == res.id:
        print(f"   port {port.number}: {port.settings} {device_of(port)[1]}, metals at it {sorted(port.available or [])}")
removed = device_shapes(ly, [res], st)
print("rhigh shapes removed at export:", {l: r.count() for l, r in sorted(removed.items())})
print("REF patch of the rhigh:", [str(s.dbbox()) for s in cell.shapes(ly.find_layer(300, 0)).each()
                                   if s.property(202) == f"device:{res.id}"])
