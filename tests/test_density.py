# Batch test (KLayout -z -nc -rx -r): Fill Density Holes and Merge Metal (density.py) - which holes are cheesing, the
# merge of the cell with the metal of its plain subcells (placed twice or more, or once and holding filled holes),
# what stays (devices, cells placed once, cells placed elsewhere too, vias, texts, shapes with properties), and on
# the FMD layouts if present: the metal after = before + fill exactly, fewer polygons, vias and devices unchanged.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, layout_file

import pya
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))   # not via salt here
from klayout_em_export.density import density_holes, fill_and_merge, merged_layers
from klayout_em_export.devices import find_devices
from klayout_em_export.stackup import Stackup

failed = []


def check(ok, text):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)


def um(x):
    return round(x * 1000)


def plate(holes, size, extra=(), w=100, h=100):
    """A w x h um plate with `holes` square holes of `size` um in a grid, and extra (x, y, w, h) holes."""
    region = pya.Region(pya.Box(0, 0, um(w), um(h)))
    for i in range(holes):
        x, y = 5 + 9 * (i % 10), 5 + 9 * (i // 10)
        region -= pya.Region(pya.Box(um(x), um(y), um(x + size), um(y + size)))
    for x, y, bw, bh in extra:
        region -= pya.Region(pya.Box(um(x), um(y), um(x + bw), um(y + bh)))
    return region


def flat(layout, cell, layer):
    """A copy of the layer's metal in cell and its subcells (a Region made from an iterator reads the layout lazily)."""
    region = pya.Region()
    li = layout.find_layer(layer, 0)
    if li is not None:
        region.insert(cell.begin_shapes_rec(li))
    return region


# ---- the rule: any shape with a hole size found 20 times or more
fill, kept = density_holes(plate(25, 2, [(60, 60, 10, 10)]))
check(len(fill) == 25 and kept == 1, f"25 holes of one size are cheesing, the one 10 um hole is not: {len(fill)}, {kept}")
fill, kept = density_holes(plate(19, 2))
check(not fill and kept == 19, f"19 holes of one size are not cheesing: {len(fill)}")
strip = pya.Region(pya.Box(0, 0, um(20), um(100)))
for i in range(25):
    strip -= pya.Region(pya.Box(um(5), um(5 + 3 * i), um(7), um(6 + 3 * i)))
fill, kept = density_holes(strip)
check(len(fill) == 25, f"any shape counts, also a slotted 20 um line: {len(fill)} filled")

# ---- a layout: Metal3 (30/0), Metal2 (10/0), Via2 (29/0)
st = Stackup(STACKUP)
check(29 not in merged_layers(st) and {10, 30} <= set(merged_layers(st)), "via layers are not merged")
ly = pya.Layout()
ly.dbu = 0.001
top = ly.create_cell("TOP")
M3, M2, V2 = ly.layer(30, 0), ly.layer(10, 0), ly.layer(29, 0)
top.shapes(M3).insert(plate(25, 2, [(60, 60, 10, 10)]))
top.shapes(M3).insert(pya.Box(um(100), um(40), um(150), um(45)))         # a line touching the plate: merges into it
top.shapes(M3).insert(pya.Text("GND", um(10), um(1)))
ref = top.shapes(M3).insert(pya.Box(um(200), 0, um(201), um(1)), ly.properties_id([[202, "device:x@0,0"]]))
# a via stack placed three times along the line: its Metal3 pad merges into the line, its vias stay
stack = ly.create_cell("via_stack")
stack.shapes(M3).insert(pya.Box(0, 0, um(2), um(2)))
stack.shapes(M2).insert(pya.Box(0, 0, um(2), um(2)))
stack.shapes(V2).insert(pya.Box(um(0.5), um(0.5), um(0.7), um(0.7)))
top.insert(pya.CellInstArray(stack.cell_index(), pya.Trans(um(110), um(41)), pya.Vector(um(10), 0), pya.Vector(), 3, 1))
# a pad cell placed once, away from everything: stays a cell
pad = ly.create_cell("pad")
pad.shapes(M3).insert(pya.Box(0, 0, um(10), um(10)))
top.insert(pya.CellInstArray(pad.cell_index(), pya.Trans(um(300), 0)))
# a cheesed plate in a cell placed once (a GND cell): its metal moves, so the fill merges with it
gnd = ly.create_cell("GND")
gnd.shapes(M2).insert(plate(25, 2))
top.insert(pya.CellInstArray(gnd.cell_index(), pya.Trans(0, um(200))))
# a cell placed twice in TOP and once in another top cell: stays (moving its metal would change the other cell)
shared = ly.create_cell("shared")
shared.shapes(M3).insert(pya.Box(0, 0, um(1), um(1)))
top.insert(pya.CellInstArray(shared.cell_index(), pya.Trans(um(400), 0), pya.Vector(um(5), 0), pya.Vector(), 2, 1))
other = ly.create_cell("OTHER")
other.insert(pya.CellInstArray(shared.cell_index(), pya.Trans()))

before = {layer: flat(ly, top, layer) for layer in (30, 10)}
fills = {layer: pya.Region(density_holes(before[layer])[0]) for layer in before}
vias_before = flat(ly, top, 29).count()
done, cells = fill_and_merge(ly, top, st)
check(all((flat(ly, top, layer) ^ (before[layer] + fills[layer])).is_empty() for layer in before),
      "metal after = metal before + fill, exactly")
check(done["Metal3"].filled == 25 and done["Metal2"].filled == 25, f"filled: Metal3 {done['Metal3'].filled}, "
      f"Metal2 {done['Metal2'].filled} (in the GND cell)")
check(cells == 2 and stack.shapes(M3).is_empty() and stack.shapes(M2).is_empty() and stack.shapes(V2).size() == 1
      and gnd.shapes(M2).is_empty(), f"moved: the via stack's metal (vias stay) and GND's plate ({cells} cells)")
check(pad.shapes(M3).size() == 1 and shared.shapes(M3).size() == 1,
      "a cell placed once without holes, and a cell also placed elsewhere, keep their metal")
texts = [s for s in top.shapes(M3).each() if s.is_text()]
tagged = [s for s in top.shapes(M3).each() if s.prop_id != 0]
check(len(texts) == 1 and len(tagged) == 1, "the text and the shape with a property are kept as they are")
check(flat(ly, top, 29).count() == vias_before, "vias unchanged")
plates = [p for p in top.shapes(M3).each() if not p.is_text() and p.prop_id == 0]
check(len(plates) == 1 and plates[0].polygon.holes() == 1,
      f"Metal3 of TOP: plate, line and the three pads are one polygon, with its one 10 um hole ({len(plates)})")
check(done["Metal3"].after < done["Metal3"].before, f"Metal3 polygons {done['Metal3'].before} -> "
                                                    f"{done['Metal3'].after}")

# ---- the FMD layouts: exact, fewer polygons, vias and devices unchanged
for name in ("FMD_QNC_60_ghz_mpa_filled.gds", "FMD_QNC_Stacked_180GHz_PA.gds"):
    path = layout_file(name)
    if not os.path.exists(path):
        print("skipped: no", path)
        continue
    fmd = pya.Layout()
    fmd.technology_name = "sg13g2"
    fmd.read(path)
    cell = max(fmd.top_cells(), key=lambda c: c.bbox().area())
    layers = merged_layers(st)
    vias = [l.layer for l in st.layers if l.kind == "via"]
    before = {layer: flat(fmd, cell, layer) for layer in layers}
    fills = {layer: pya.Region(density_holes(before[layer])[0]) for layer in layers}
    via_counts = {v: flat(fmd, cell, v).count() for v in vias}
    devices = sorted((d.id, sorted(d.terminals)) for d in find_devices(fmd, cell, st)[0])
    done, cells = fill_and_merge(fmd, cell, st)
    exact = all((flat(fmd, cell, layer) ^ (before[layer] + fills[layer])).is_empty() for layer in layers)
    total = (sum(r.before for r in done.values()), sum(r.after for r in done.values()))
    check(exact and total[1] < total[0] and all(r.after <= r.before for r in done.values()),
          f"{name}: metal = before + fill, polygons {total[0]} -> {total[1]}, none more on any layer "
          f"({sum(r.filled for r in done.values())} holes filled, {cells} subcells' metal moved)")
    check({v: flat(fmd, cell, v).count() for v in vias} == via_counts
          and sorted((d.id, sorted(d.terminals)) for d in find_devices(fmd, cell, st)[0]) == devices,
          f"{name}: vias and devices ({len(devices)}) unchanged")

print("all passed" if not failed else f"FAILED: {'; '.join(failed)}")
