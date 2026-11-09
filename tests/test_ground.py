# Batch test (KLayout -z -nc -rx -r, package installed in salt): ground net from via ports and from a marked shape.
#  1. OctaDiffTap demo: three feed ports Metal1 (ground) -> TopMetal2 (feeds LA, LB, LC).
#  2. core_transistor_3port_bce: ports 1-2 Metal3 -> TopMetal2, ports 3-5 Metal2 -> REF_FOR_TRANSISTOR (a sheet,
#     not traced), with the settings of the example's .simcfg.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import EXAMPLE_BCE, STACKUP, layout_file
import json
import pya
from klayout_em_export.connectivity import check_ground
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports
from klayout_em_export.stackup import Stackup



def run(title, gds, stackup_file, settings, seeds=()):
    st = Stackup(stackup_file)
    ly = pya.Layout(); ly.read(gds)
    cell = next(c for c in ly.top_cells() if not c.name.startswith("$$$"))
    for layer, s in settings.items():
        for shape in cell.shapes(ly.find_layer(layer, 0)).each():
            shape.set_property(PROP_KEY, s.encode())
    ports = collect_ports(ly, cell, stackup=st)
    seeds = [(layer, pya.Point(round(x / ly.dbu), round(y / ly.dbu))) for layer, x, y in seeds]
    result = check_ground(ly, cell, st, seeds=seeds, ports=ports)
    print(f"## {title}\n" + result.summary())


run("OctaDiffTap, ground from the via ports", layout_file("OctaDiffTap_0n50_ports3.gds"),
    STACKUP,
    {l: PortSettings("Z", "Metal1", "TopMetal2") for l in (201, 202, 203)})

ex = EXAMPLE_BCE
simcfg = json.load(open(os.path.join(ex, "50_ghz_mpa_core_bce_ports.simcfg")))
settings = {p["source_layernum"]: PortSettings(p["direction"], p["from_layername"] or "", p["to_layername"] or "",
                                               p["target_layername"] or "", p["port_Z0"], p["voltage"])
            for p in simcfg["ports"]}
print("bce ports:", {l: str(s) for l, s in settings.items()})
run("3-port BCE transistor, ground from the via ports", os.path.join(ex, "50_ghz_mpa_core_bce_ports.gds"),
    os.path.join(ex, "SG13G2_100um_bce_ports.xml"), settings)

run("OctaDiffTap, marked: the LA feed on TopMetal2 (ports would say Metal1)",
    layout_file("OctaDiffTap_0n50_ports3.gds"),
    STACKUP,
    {l: PortSettings("Z", "Metal1", "TopMetal2") for l in (201, 202, 203)}, seeds=[(134, 33.7, -41.5)])

# a shorted port: OctaDiffTap with a TopVia-free direct short is not available, so use a port whose both ends are
# the inductor: TopMetal1 -> TopMetal2 at a TopVia2 crossing joins the same net
st = Stackup(STACKUP)
ly = pya.Layout(); ly.read(layout_file("OctaDiffTap_0n50_ports3.gds"))
cell = ly.top_cell()
for layer in (201, 202, 203):
    for shape in cell.shapes(ly.find_layer(layer, 0)).each():
        shape.set_property(PROP_KEY, PortSettings("Z", "Metal1", "TopMetal2").encode())
tv2 = pya.Region(cell.begin_shapes_rec(ly.find_layer(133, 0)))
via = list(tv2.each())[0].bbox()                                   # a TopVia2: TopMetal1 and TopMetal2 both there
cell.shapes(ly.layer(204, 0)).insert(pya.Box(via.left, via.center().y, via.right, via.center().y)).set_property(
    PROP_KEY, PortSettings("Z", "TopMetal1", "TopMetal2").encode())
result = check_ground(ly, cell, st, ports=collect_ports(ly, cell, stackup=st))
print("## OctaDiffTap with port 4 across a TopVia2\n" + result.summary())

# a marked ground plane larger than the region: the mark (a point in the plane) lies outside the region box, the
# plane's part inside is ground (Metal3 30/0 plane with a Via3 to a Metal4 strip inside the box)
ly = pya.Layout()
ly.dbu = 0.001
cell = ly.create_cell("PLANE")
cell.shapes(ly.layer(30, 0)).insert(pya.Box(0, 0, 400000, 400000))
cell.shapes(ly.layer(49, 0)).insert(pya.Box(200000, 200000, 200500, 200500))
cell.shapes(ly.layer(50, 0)).insert(pya.Box(190000, 190000, 260000, 210000))
box = pya.Box(150000, 150000, 300000, 300000)
result = check_ground(ly, cell, st, box, seeds=[(30, pya.Point(10000, 10000))], ports={})
print("## Metal3 plane marked outside the region box\n" + result.summary())
print("ok  " if sorted(result.names[l] for l in result.net) == ["Metal3", "Metal4"] else "FAIL",
      "plane marked outside the region: ground", sorted(result.names[l] for l in result.net))


# 3. marking at a point through the hierarchy: a pad frame stacked on Metal1..Metal3 without vias in a subcell
# (three separate nets), one click marks all three; Shift+click (unmark) removes them again
from klayout_em_export import gui
st = Stackup(STACKUP)
ly = pya.Layout()
ly.dbu = 0.001
top = ly.create_cell("top")
frame = ly.create_cell("frame")
um = lambda v: round(v / ly.dbu)
for layer in (8, 10, 30):
    frame.shapes(ly.layer(layer, 0)).insert(pya.Box(um(0), um(0), um(70), um(70)))
top.insert(pya.CellInstArray(frame.cell_index(), pya.Trans(pya.Point(um(100), um(100)))))
top.shapes(ly.layer(134, 0)).insert(pya.Box(um(0), um(120), um(300), um(124)))   # a line, not under the click
click = pya.Point(um(130), um(130))
print("## mark at a point")
print("metals at the click:", gui.metals_at_point(ly, top, st, click))
marked = gui.mark_ground_at(ly, top, st, click)
print("marked:", marked, "| marks:", len(gui.ground_seeds(ly)))
check = check_ground(ly, top, st, seeds=gui.ground_seeds(ly), ports={})
print(check.summary())
if marked != ["Metal3", "Metal2", "Metal1"] or sorted(check.net) != [8, 10, 30]:
    print("FAIL: one click must mark the whole stacked frame in the subcell as ground")
print("unmarked:", gui.unmark_ground_at(ly, top, st, click), "| marks left:", len(gui.ground_seeds(ly)))
if gui.ground_seeds(ly):
    print("FAIL: Shift+click must remove the marks of the shapes under the click")
print("nothing at a point beside the frame:", gui.mark_ground_at(ly, top, st, pya.Point(um(50), um(50))))

# 4. click outside the EM region box on a frame reaching into it: the stored point lies inside the box, so the
# ground check (which looks inside the box) sees the frame
from klayout_em_export.gui import EM_REGION
top.shapes(ly.layer(*EM_REGION)).insert(pya.Box(um(150), um(150), um(300), um(300)))
outside = pya.Point(um(105), um(105))
print("click outside the box marks:", gui.mark_ground_at(ly, top, st, outside))
seeds = gui.ground_seeds(ly)
print("stored points:", [(l, p.x * ly.dbu, p.y * ly.dbu) for l, p in seeds])
box = pya.Box(um(150), um(150), um(300), um(300))
if any(not box.contains(p) for l, p in seeds):
    print("FAIL: the stored ground points must lie inside the EM region box")
check = check_ground(ly, top, st, box, seeds=seeds, ports={})
if sorted(check.net) != [8, 10, 30]:
    print("FAIL: the ground check inside the box must see the frame marked by the outside click")
print("unmark by the outside click:", gui.unmark_ground_at(ly, top, st, outside), "| left:", len(gui.ground_seeds(ly)))
if gui.ground_seeds(ly):
    print("FAIL: unmark must find the moved points through the clicked shapes")

# 4b. a ground plane that enters the box in two parts, joined only outside it (a U around a slot): a click on it
# outside the box marks both parts, not only the first (lo_core: the chip's Metal4 plane and a strip of it)
top.shapes(ly.layer(*EM_REGION)).clear()
top.shapes(ly.layer(*EM_REGION)).insert(pya.Box(um(1050), um(1200), um(1250), um(1300)))
u = pya.Region(pya.Box(um(1000), um(1000), um(1300), um(1300))) - pya.Region(pya.Box(um(1100), um(1050), um(1200), um(1300)))
for poly in u.each():
    top.shapes(ly.layer(50, 0)).insert(poly)
print("click on the U's base outside the box marks:", gui.mark_ground_at(ly, top, st, pya.Point(um(1150), um(1020))))
seeds = [(l, p) for l, p in gui.ground_seeds(ly) if l == 50]
xs = sorted(p.x * ly.dbu for _, p in seeds)
print("stored Metal4 points:", [(p.x * ly.dbu, p.y * ly.dbu) for _, p in seeds])
if len(seeds) != 2 or not (xs[0] < 1100 < 1200 < xs[1]):
    print("FAIL: both arms of the plane inside the box must get a ground mark")
check = check_ground(ly, top, st, pya.Box(um(1050), um(1200), um(1250), um(1300)), seeds=gui.ground_seeds(ly), ports={})
if len(check.net.get(50, [])) != 2 if isinstance(check.net, dict) else False:
    print("FAIL: the ground check must see both arms")
gui.unmark_ground_at(ly, top, st, pya.Point(um(1150), um(1020)))
if gui.ground_seeds(ly):
    print("FAIL: unmark at the same click must remove both marks")
top.shapes(ly.layer(*EM_REGION)).clear()

# 5. a click on something that is not a traced metal: nothing marked, the layers there are named
from klayout_em_export.tool import _no_metal
top.shapes(ly.layer(8, 2)).insert(pya.Box(um(400), um(400), um(420), um(420)))     # Metal1.pin
top.shapes(ly.layer(39, 0)).insert(pya.Box(um(400), um(400), um(420), um(420)))    # EdgeSeal
odd = pya.Point(um(410), um(410))
print("marks on a pin/marker:", gui.mark_ground_at(ly, top, st, odd), "| drawn:", gui.layers_at_point(ly, top, odd))
print("status:", _no_metal(ly, top, odd))
if gui.ground_seeds(ly) or sorted(gui.layers_at_point(ly, top, odd)) != ["39/0", "8/2"]:
    print("FAIL: a click on a non-wiring layer must mark nothing and name the layers drawn there")
