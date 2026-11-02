# Batch test (KLayout -z -nc -rx -r): Remove Dummy Fill (dummyfill.py) - floating repeated shapes on stackup metals
# are removed (any datatype, flat or as placements of a tile cell), and what stays: vias and via arrays, shapes
# touching a via, a label or a port, a single floating shape, a floating structure with a shape of its own size; on
# the FMD layouts if present: vias and devices unchanged.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, palace_testcases

import pya
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))   # not via salt here
from klayout_em_export.devices import find_devices
from klayout_em_export.dummyfill import remove_dummy_fill
from klayout_em_export.stackup import Stackup

failed = []


def check(ok, text):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)


def um(x):
    return round(x * 1000)


def count(layout, cell, layer, datatype):
    li = layout.find_layer(layer, datatype)
    if li is None:
        return 0
    region = pya.Region()
    region.insert(cell.begin_shapes_rec(li))
    return region.count()


st = Stackup(STACKUP)
ly = pya.Layout()
ly.dbu = 0.001
top = ly.create_cell("TOP")
M1, M1F, M2, V1, P201, TXT = (ly.layer(8, 0), ly.layer(8, 22), ly.layer(10, 0), ly.layer(19, 0), ly.layer(201, 0),
                              ly.layer(8, 25))
# a fill tile cell (Metal1, datatype 22), placed as a 10 x 3 array: 30 tiles at a 4 um pitch
tile = ly.create_cell("TILE")
tile.shapes(M1F).insert(pya.Box(0, 0, um(2), um(2)))
top.insert(pya.CellInstArray(tile.cell_index(), pya.Trans(0, 0), pya.Vector(um(4), 0), pya.Vector(0, um(4)), 10, 3))
# tile (0, 0): a Via1 on it and Metal2 above - connected, stays; tile (4, 0): a label on it; tile (8, 0): a port
top.shapes(V1).insert(pya.Box(um(0.5), um(0.5), um(0.7), um(0.7)))
top.shapes(M2).insert(pya.Box(0, 0, um(1), um(1)))
top.shapes(TXT).insert(pya.Text("sig", um(5), um(1)))
top.shapes(P201).insert(pya.Box(um(8), um(1), um(8), um(1.5)))
# a via array on Via1 (30 vias, each isolated): never removed
for i in range(30):
    top.shapes(V1).insert(pya.Box(um(100 + 0.5 * i), 0, um(100.2 + 0.5 * i), um(0.2)))
# flat floating repeated fill on datatype 0: 25 squares - removed
for i in range(25):
    top.shapes(M1).insert(pya.Box(um(200 + 4 * i), 0, um(202 + 4 * i), um(2)))
# a single floating Metal1 shape: stays
top.shapes(M1).insert(pya.Box(um(0), um(50), um(30), um(60)))
# a floating "shield": 25 identical strips joined by one spine of its own size - stays
for i in range(25):
    top.shapes(M1).insert(pya.Box(um(50 + 2 * i), um(50), um(51 + 2 * i), um(70)))
top.shapes(M1).insert(pya.Box(um(50), um(70), um(100), um(72)))

vias_before = count(ly, top, 19, 0)
removed, cells = remove_dummy_fill(ly, top, st)
check(count(ly, top, 8, 22) == 3 and removed.get((8, 22)) == 27,
      f"tile placements: 27 removed, the 3 touching a via, a label and a port stay ({count(ly, top, 8, 22)} left)")
check(count(ly, top, 19, 0) == vias_before, "vias and the via array are never removed")
check(removed.get((8, 0)) == 25 and count(ly, top, 8, 0) == 1 + 26,
      f"flat floating repeated fill on datatype 0 removed ({removed.get((8, 0))}); the single shape and the shield "
      f"(26 shapes) stay ({count(ly, top, 8, 0)} left)")
check(cells == 0 and ly.has_cell("TILE"), "the tile cell stays while placements of it are left")

# all placements are fill: the tile cell goes
ly2 = pya.Layout()
ly2.dbu = 0.001
top2 = ly2.create_cell("TOP")
tile2 = ly2.create_cell("TILE")
tile2.shapes(ly2.layer(8, 22)).insert(pya.Box(0, 0, um(2), um(2)))
top2.insert(pya.CellInstArray(tile2.cell_index(), pya.Trans(), pya.Vector(um(4), 0), pya.Vector(0, um(4)), 5, 5))
removed, cells = remove_dummy_fill(ly2, top2, st)
check(removed.get((8, 22)) == 25 and cells == 1 and not ly2.has_cell("TILE"),
      f"all placements fill: 25 removed, the empty tile cell deleted ({cells})")

# the FMD layouts: vias and devices unchanged
for name in ("FMD_QNC_60_ghz_mpa_filled.gds", "FMD_QNC_Stacked_180GHz_PA.gds"):
    path = palace_testcases("klayout_export", name)
    if not os.path.exists(path):
        print("skipped: no", path)
        continue
    fmd = pya.Layout()
    fmd.technology_name = "sg13g2"
    fmd.read(path)
    cell = max(fmd.top_cells(), key=lambda c: c.bbox().area())
    vias = [l.layer for l in st.layers if l.kind == "via"]
    via_counts = {v: count(fmd, cell, v, 0) for v in vias}
    devices = sorted((d.id, sorted(d.terminals)) for d in find_devices(fmd, cell, st)[0])
    removed, cells = remove_dummy_fill(fmd, cell, st)
    check({v: count(fmd, cell, v, 0) for v in vias} == via_counts
          and sorted((d.id, sorted(d.terminals)) for d in find_devices(fmd, cell, st)[0]) == devices,
          f"{name}: {sum(removed.values())} fill shapes removed, {cells} cells deleted; vias and devices "
          f"({len(devices)}) unchanged")

print("all passed" if not failed else f"FAILED: {'; '.join(failed)}")
