# Batch test (KLayout -z -nc -rx -r, package installed in salt): crossings of the EM region box and boundary ports.
# OctaDiffTap demo, region box with its bottom edge at y = -35 um: it cuts the three TopMetal2 feeds (signal) and
# the Metal1 ground, above the hand-drawn ports at y = -42 (outside the box). Ground: marked on Metal1.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, layout_file, out_dir

import pya
from klayout_em_export.boundary import create_ports, find_crossings
from klayout_em_export.pipeline import NoUndo   # a standalone layout in batch mode has no undo manager
from klayout_em_export.connectivity import check_ground
from klayout_em_export.ports import collect_ports
from klayout_em_export.stackup import Stackup

st = Stackup(STACKUP)
view = pya.LayoutView(True)
idx = view.load_layout(layout_file("OctaDiffTap_0n50_ports3.gds"), True)
ly = view.cellview(idx).layout()
cell = ly.top_cell()
um = lambda v: round(v / ly.dbu)
box = pya.Box(um(-50), um(-35), um(140), um(140))

metal1 = pya.Region(cell.begin_shapes_rec(ly.find_layer(8, 0))).merged()
inside = list(metal1.each())[0].decompose_trapezoids()[0].bbox().center()   # a point in the Metal1 ground
ground = check_ground(ly, cell, st, box, seeds=[(8, inside)], ports=collect_ports(ly, cell, box, stackup=st))
print(ground.summary().replace("\n", " | "))
crossings = find_crossings(ly, cell, st, box, ground)
for c in crossings:
    print(f"  {c.side:6s} {c.name:10s} {str(c.edge.to_dtype(ly.dbu)):32s} {c.status()}")
numbers = create_ports(NoUndo(), cell, st, crossings)
print("new ports:", numbers)
for layer in sorted(collect_ports(ly, cell, box, stackup=st).items()):
    port = layer[1]
    print(f"  port {port.number}: {port.settings} on {[str(s.bbox().to_dtype(ly.dbu)) for s, t, p in port.items]}",
          "available:", sorted(port.available or []))
print("second run, all crossings handled:", [c.status() for c in find_crossings(ly, cell, st, box, ground) if not c.ground])

# export the region with the new boundary ports (for a gds2palace check outside KLayout)
from klayout_em_export.boundary import moved_ports
from klayout_em_export.export import export_flat
from klayout_em_export.ports import simcfg_ports
from klayout_em_export.simcfg import write_simcfg
OUT = out_dir("boundary")
os.makedirs(OUT, exist_ok=True)
gds = os.path.join(OUT, "octa_cut_em.gds")
dbox = box.to_dtype(ly.dbu)
result = export_flat(ly, cell, st, gds, box=dbox)
ports = collect_ports(ly, cell, box, stackup=st)
if os.path.exists(gds.replace(".gds", ".simcfg")):
    os.remove(gds.replace(".gds", ".simcfg"))
write_simcfg(gds.replace(".gds", ".simcfg"), gds, st.path, result.cellname, ports=simcfg_ports(ports))
print("exported", os.path.basename(gds), "ports in .simcfg:", [p["portnumber"] for p in simcfg_ports(ports)])

# EM panel ports table (box on 800/0): the boundary ports with their export numbers, nothing left to propose;
# and a moved box
from klayout_em_export.gui import META_STACKUP
from klayout_em_export.panel import EMPanel
ly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, st.path, "", True))
cell.shapes(ly.layer(800, 0)).insert(box)
EMPanel._view = lambda self: (view, view.active_cellview())
panel = EMPanel()
print("panel:", [(kind, panel.table.item(r, 0).text, panel.table.item(r, 3).text) for r, (kind, item) in enumerate(panel.rows)])
print("moved box -> boundary ports off the edge:", moved_ports(ly, cell, box.moved(0, round(2 / ly.dbu))))

# as port walls: the same crossings get in-plane ports on the cut metal, pointing into the region, and the export
# writes that side as a gds2palace port wall into the .simcfg (other sides kept)
import json
from klayout_em_export.boundary import port_wall_sides
from klayout_em_export.simcfg import with_port_walls
view2 = pya.LayoutView(True)
idx2 = view2.load_layout(layout_file("OctaDiffTap_0n50_ports3.gds"), True)
ly2 = view2.cellview(idx2).layout()
cell2 = ly2.top_cell()
ground2 = check_ground(ly2, cell2, st, box, seeds=[(8, inside)], ports=collect_ports(ly2, cell2, box, stackup=st))
crossings2 = find_crossings(ly2, cell2, st, box, ground2)
print("port wall status:", [c.status(True) for c in crossings2 if c.needs_port])
numbers2 = create_ports(NoUndo(), cell2, st, crossings2, port_wall=True)
from klayout_em_export.ports import port_problems
wall_ports = collect_ports(ly2, cell2, box, stackup=st)
wall_problems = {n: port_problems(p, st) for n, p in wall_ports.items() if p.on_wall}
print("port wall ports:", sorted(n - 200 for n in wall_problems), "problems:", wall_problems)
if len(wall_problems) != len(numbers2) or any(wall_problems.values()):
    print("FAIL: zero-width in-plane ports on the region edge are port wall ports and must pass the port check")
ports2 = collect_ports(ly2, cell2, box, stackup=st)
made = [ports2[200 + n].settings for n in numbers2]
print("port wall ports:", numbers2, [str(s) for s in made])
if not numbers2 or any(s.is_via or s.direction != "Y" or s.target != "TopMetal2" for s in made):
    print("FAIL: port wall ports are not in-plane ports on TopMetal2 pointing into the region (Y)")
walls = port_wall_sides(ports2, box)
print("port wall sides:", walls)
if walls != ["ymin"]:
    print("FAIL: expected the bottom side (ymin) as the only port wall")
gds2 = os.path.join(OUT, "octa_cut_portwall_em.gds")
result2 = export_flat(ly2, cell2, st, gds2, box=dbox)
cfg2 = gds2.replace(".gds", ".simcfg")
if os.path.exists(cfg2):
    os.remove(cfg2)
write_simcfg(cfg2, gds2, st.path, result2.cellname, ports=simcfg_ports(ports2), port_walls=walls)
boundary2 = json.load(open(cfg2))["saved_values"]["boundary"]
print("boundary in the new .simcfg:", boundary2)
if boundary2 != ["ABC", "ABC", "PORTWALL", "ABC", "ABC", "ABC"]:
    print("FAIL: new .simcfg boundary")
data = json.load(open(cfg2))
data["saved_values"]["boundary"] = ["PEC", "ABC", "ABC", "PMC", "ABC", "PEC"]   # the user's own choice in setupEM
json.dump(data, open(cfg2, "w"))
write_simcfg(cfg2, gds2, st.path, result2.cellname, ports=simcfg_ports(ports2), port_walls=walls)
boundary3 = json.load(open(cfg2))["saved_values"]["boundary"]
print("boundary in the updated .simcfg:", boundary3)
if boundary3 != ["PEC", "ABC", "PORTWALL", "PMC", "ABC", "PEC"]:
    print("FAIL: an update must only set the port wall sides")
if with_port_walls("PEC", ["xmax"]) != ["PEC", "PORTWALL", "PEC", "PEC", "PEC", "PEC"]:
    print("FAIL: a single boundary value")
print("no port wall for via ports:", port_wall_sides(collect_ports(ly, cell, box, stackup=st), box))
if port_wall_sides(collect_ports(ly, cell, box, stackup=st), box):
    print("FAIL: via ports at the cut must not make a port wall")

# coplanar line (signal and both ground strips on TopMetal2), region box cutting it at the left and right: no other
# metal at the cut, so no via port; as port walls the ground strips on the same metal are enough
cpw = pya.Layout()
cpw.dbu = 0.001
top = cpw.create_cell("cpw")
um2 = lambda v: round(v / cpw.dbu)
tm2 = cpw.layer(134, 0)
for y0, y1 in ((-5, 5), (10, 40), (-40, -10)):
    top.shapes(tm2).insert(pya.Box(um2(0), um2(y0), um2(200), um2(y1)))
# and a Metal1 plane under everything, larger than the box, not marked as ground: it covers every whole side
# of the box, so it is a plane, not a port candidate
top.shapes(cpw.layer(8, 0)).insert(pya.Box(um2(-20), um2(-80), um2(220), um2(80)))
cbox = pya.Box(um2(20), um2(-60), um2(180), um2(60))
seeds = [(134, pya.Point(um2(100), um2(25))), (134, pya.Point(um2(100), um2(-25)))]
g = check_ground(cpw, top, st, cbox, seeds=seeds, ports=collect_ports(cpw, top, cbox, stackup=st))
cross = find_crossings(cpw, top, st, cbox, g)
print("cpw crossings:", [(c.side, "ground" if c.ground else "signal", c.status(), c.status(True)) for c in cross])
via_proposed = [c for c in cross if c.needs(False)]
wall_proposed = [c for c in cross if c.needs(True)]
print("cpw proposed: via", len(via_proposed), "port wall", len(wall_proposed))
planes = [c for c in cross if c.plane]
print("cpw planes:", [(c.side, c.name, c.status()) for c in planes])
if sorted((c.side, c.name) for c in planes) != [(side, "Metal1") for side in ("bottom", "left", "right", "top")] or any(c.needs(True) for c in planes):
    print("FAIL: the Metal1 plane across the whole side must be a plane, not a port candidate")
if via_proposed or len(wall_proposed) != 2:
    print("FAIL: a coplanar line gets no via port, but one port wall port at each cut")
made_cpw = create_ports(NoUndo(), top, st, cross, port_wall=True)
cports = collect_ports(cpw, top, cbox, stackup=st)
print("cpw ports:", made_cpw, [str(cports[200 + n].settings) for n in made_cpw], "walls:", port_wall_sides(cports, cbox))
if sorted(cports[200 + n].settings.direction for n in made_cpw) != ["-X", "X"] or port_wall_sides(cports, cbox) != ["xmin", "xmax"]:
    print("FAIL: cpw port wall ports")

# the panel on the coplanar layout without any ground mark: one row for all cuts ("mark ground"), not one per cut
cpw.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, st.path, "", True))
top.shapes(cpw.layer(800, 0)).insert(cbox)
for layer in (201, 202):
    top.shapes(cpw.layer(layer, 0)).clear()
cpw_file = os.path.join(OUT, "cpw_noground.gds")
cpw.write(cpw_file)
view3 = pya.LayoutView(True)
view3.load_layout(cpw_file, True)
view3.active_cellview().layout().add_meta_info(pya.LayoutMetaInfo(META_STACKUP, st.path, "", True))
EMPanel._view = lambda self: (view3, view3.active_cellview())
panel3 = EMPanel()
rows3 = [[panel3.table.item(r, c).text for c in (2, 4)] for r in range(panel3.table.rowCount)]
print("cpw panel without ground:", rows3, "|", panel3.ports_step.summary.text)
if len(rows3) != 1 or "mark ground" not in rows3[0][1]:
    print("FAIL: without ground the panel must show one row asking to mark ground")
