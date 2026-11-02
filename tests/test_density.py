# Batch test (KLayout -z -nc -rx -r): density holes (density.py) - which holes of a ground plane are cheesing, the
# fill added to the cell (subcells untouched), a second run, removal (also after a GDS round trip), and on
# FMD_QNC_60_ghz_mpa_filled.gds if present: the holes found, and the same ground check results after the fill.
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, out_dir, palace_testcases

import pya
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))   # not via salt here
from klayout_em_export.connectivity import check_ground
from klayout_em_export.density import density_holes, fill_density_holes, remove_density_fill
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports
from klayout_em_export.stackup import Stackup

OUT = out_dir("density")
failed = []


def check(ok, text):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)


def um(x):
    return round(x * 1000)


def plane(holes, size, extra=()):
    """A 100 x 100 um plane with `holes` square holes of `size` um in a grid, and extra (x, y, w, h) holes."""
    region = pya.Region(pya.Box(0, 0, um(100), um(100)))
    for i in range(holes):
        x, y = 5 + 9 * (i % 10), 5 + 9 * (i // 10)
        region -= pya.Region(pya.Box(um(x), um(y), um(x + size), um(y + size)))
    for x, y, w, h in extra:
        region -= pya.Region(pya.Box(um(x), um(y), um(x + w), um(y + h)))
    return region


def holes_left(layout, cell, layer):
    return sum(p.holes() for p in pya.Region(cell.begin_shapes_rec(layout.find_layer(layer, 0))).merged().each())


# ---- the rule
area = um(100) * um(100)
found = density_holes(plane(25, 2, [(60, 60, 10, 10)]), area)
check(found.planes == 1 and len(found.fill) == 25 and found.kept == 1,
      f"25 holes of one size are cheesing, the one 10 um hole is not: planes {found.planes}, fill {len(found.fill)}, "
      f"kept {found.kept}")
found = density_holes(plane(19, 2), area)
check(not found.fill and found.kept == 19, f"19 holes of one size are not cheesing: fill {len(found.fill)}")
# an L of 20 um wide strips is no ground plane: its outline covers 36 % of its bounding box (a ring is a plane: the
# outline is taken with its holes filled, as in gds_prepare_for_EM)
strip = pya.Region(pya.Box(0, 0, um(20), um(100))) + pya.Region(pya.Box(0, 0, um(100), um(20)))
for i in range(25):
    strip -= pya.Region(pya.Box(um(5), um(25 + 3 * i), um(7), um(26 + 3 * i)))
found = density_holes(strip, area)
check(found.planes == 0 and not found.fill, f"an L of strips is no ground plane: planes {found.planes}")
found = density_holes(plane(25, 2), area * 20)
check(found.planes == 0, f"a plane under 10 % of the cell is no ground plane: planes {found.planes}")

# ---- fill in a layout: the plane (Metal3, 30/0) in a subcell; a port shape with its own property in the top cell
st = Stackup(STACKUP)
ly = pya.Layout()
ly.dbu = 0.001
top = ly.create_cell("TOP")
sub = ly.create_cell("PLANE")
sub.shapes(ly.layer(30, 0)).insert(plane(25, 2, [(60, 60, 10, 10)]))
top.insert(pya.CellInstArray(sub.cell_index(), pya.Trans()))
port = top.shapes(ly.layer(201, 0)).insert(pya.Box(0, 0, 0, um(5)),
                                           ly.properties_id([[PROP_KEY, PortSettings("Z", "Metal3", "Metal2").encode()]]))
sub_shapes = sub.shapes(ly.find_layer(30, 0)).size()
result = fill_density_holes(ly, top, st)
check(len(result["Metal3"].fill) == 25 and holes_left(ly, top, 30) == 1,
      f"fill: Metal3 {len(result['Metal3'].fill)} filled, holes left {holes_left(ly, top, 30)}")
check(sub.shapes(ly.find_layer(30, 0)).size() == sub_shapes and top.shapes(ly.find_layer(30, 0)).size() == 25,
      "fill: added to the cell itself, the subcell is untouched")
again = fill_density_holes(ly, top, st)
check(not again["Metal3"].fill, f"a second run fills nothing: {len(again['Metal3'].fill)}")
path = os.path.join(OUT, "filled.gds")
ly.write(path)
removed = remove_density_fill(ly, top)
check(removed == 25 and holes_left(ly, top, 30) == 26 and top.shapes(ly.find_layer(201, 0)).size() == 1,
      f"remove: {removed} removed, holes back {holes_left(ly, top, 30)}, the port shape stays")
back = pya.Layout()
back.read(path)
removed = remove_density_fill(back, back.cell("TOP"))
check(removed == 25 and holes_left(back, back.cell("TOP"), 30) == 26, f"remove after a GDS round trip: {removed}")

# ---- the cheesed layout: holes found; the ground check gives the same results with the fill
path = palace_testcases("klayout_export", "FMD_QNC_60_ghz_mpa_filled.gds")
if not os.path.exists(path):
    print("skipped: no", path)
else:
    from klayout_em_export.locate import drawn_metals, edge_at, metals_at, via_layers
    fmd = pya.Layout()
    fmd.read(path)
    cell = fmd.top_cell()
    # one via port on the left edge of the largest TopMetal2 shape, down to the next metal
    tm2 = dict(drawn_metals(st))["TopMetal2"]
    b = max(pya.Region(cell.begin_shapes_rec(fmd.find_layer(tm2, 0))).each(), key=lambda p: p.area()).bbox()
    edge = edge_at(fmd, cell, st, pya.Point(b.left, b.center().y), 500)
    cell.shapes(fmd.layer(201, 0)).insert(edge[1].bbox(), fmd.properties_id([[PROP_KEY, PortSettings(
        "Z", *via_layers(metals_at(fmd, cell, st, edge[1].bbox()), edge[0])).encode()]]))
    ports = collect_ports(fmd, cell, None, stackup=st)
    t = time.time()
    before = check_ground(fmd, cell, st, None, (), ports)
    t_before = time.time() - t
    t = time.time()
    found = fill_density_holes(fmd, cell, st)
    t_fill = time.time() - t
    counts = {name: len(h.fill) for name, h in found.items() if h.fill}
    check(counts == {"Metal2": 853, "Metal3": 993}, f"FMD: density holes {counts} in {t_fill:.2f} s")
    t = time.time()
    after = check_ground(fmd, cell, st, None, (), collect_ports(fmd, cell, None, stackup=st))
    t_after = time.time() - t
    check(after.ports == before.ports and after.shorted == before.shorted and sorted(after.net) == sorted(before.net)
          and after.source == before.source,
          f"FMD ground check after the fill: same results (ports {after.ports}, shorted {after.shorted}); "
          f"{t_before:.1f} s before, {t_after:.1f} s after")

print("all passed" if not failed else f"FAILED: {'; '.join(failed)}")
