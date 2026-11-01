# Batch test (KLayout -z -nc -rx -r): replaced devices in three places that once went wrong. Cascode
# (Palace_testcases/klayout_export/guide/cascode.gds, see testpaths.py; made by the guide's capture script),
# its three resistors replaced. Needs the PDK (klayout_em_export_tests/pdk_env.py), run like test_devices.py.
# Environment: OUT.
#  1. "Selected shapes only": the completed selection carries the REF patches of the replaced devices' ports.
#  2. Ground from via ports: device ports alone do not pick a ground net (their only traced end is the terminal).
#  3. A replaced device that is moved leaves its ports and patch behind: reported by orphaned_tags.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, TESTS_DIR, palace_testcases, out_dir

import pya

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from pdk_env import load_pdk
load_pdk()
sys.path.insert(0, os.path.join(HERE, "..", "python"))
from klayout_em_export.connectivity import check_ground
from klayout_em_export.pipeline import NoUndo   # a standalone layout in batch mode has no undo manager
from klayout_em_export.devices import device_shapes, find_devices, mark_replaced, orphaned_tags, replace
from klayout_em_export.export import export_flat
from klayout_em_export.locate import drawn_metals
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports
from klayout_em_export.selection import Selection
from klayout_em_export.stackup import Stackup

OUT = out_dir("replaced_devices")
GDS = palace_testcases("klayout_export", "guide", "cascode.gds")
failed = []


def check(ok, text):
    print(("ok    " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


st = Stackup(STACKUP)
ly = pya.Layout()
ly.read(GDS)
cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))
devices = find_devices(ly, cell, st)[0]
done = replace(NoUndo(), cell, st, devices, include_resistors=True)
check(len(done) == 3, f"three resistors replaced: {sorted(done)}")

# 1. selection export: all metal selected, no patch
sel = Selection(ly, cell)
for name, layer in drawn_metals(st):
    li = ly.find_layer(layer, 0)
    if li is None or name == "REF_FOR_TRANSISTOR":
        continue
    it = cell.begin_shapes_rec(li)
    while not it.at_end():
        if not it.shape().is_text():
            sel.add_shape(it.shape(), li, it.trans())
        it.next()
completed = sel.completed(st)
check(completed.added_patches == 3, f"completed selection adds the 3 REF patches ({completed.added_patches})")
gds = os.path.join(OUT, "replaced_selection_em.gds")
export_flat(ly, cell, st, gds, selection=completed, remove=device_shapes(ly, devices, st))
out = pya.Layout()
out.read(gds)
li = out.find_layer(300, 0)
check(li is not None and out.top_cell().shapes(li).size() == 3, "the export has the 3 REF patches")

# 2. ground: with device ports only, no ground is chosen; with a pad port, its ground end wins
ports = collect_ports(ly, cell, stackup=st)
check(len(ports) == 6, f"6 device ports ({len(ports)})")
result = check_ground(ly, cell, st, ports=ports)
check(not result.net and "device ports" in result.source, f"device ports alone: {result.source}")
pad = PortSettings("Z", "TopMetal2", "Metal5")       # Cas_out pad edge, as in the guide's capture
cell.shapes(ly.layer(201 + 10, 0)).insert(pya.DBox(-3.215, 20.63, 1.785, 20.63).to_itype(ly.dbu),
                                          ly.properties_id([[PROP_KEY, pad.encode()]]))
ports = collect_ports(ly, cell, stackup=st)
result = check_ground(ly, cell, st, ports=ports)
names = sorted(result.names[l] for l in result.net)
check(result.source == "found from the via ports" and "Metal5" in names, f"with a pad port: ground on {names}")

# 3. move a replaced resistor: its ports and patch are orphaned, the moved device shows as not replaced
inst = next(i for i in cell.each_inst() if i.cell.name.startswith("rsil"))
inst.transform(pya.Trans(0, 2000))                  # 2 um up (dbu 1 nm)
moved = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
orphans = orphaned_tags(ly, cell, moved)
check(len(orphans) == 1 and next(iter(orphans)).startswith("rsil"), f"one orphan, the rsil: {sorted(orphans)}")
check(not next(d for d in moved if d.pcell == "rsil").replaced, "the moved rsil shows as not replaced")
check(all(d.replaced for d in moved if d.pcell != "rsil"), "the other resistors are still replaced")

print("FAILED: " + "; ".join(failed) if failed else "all ok")
