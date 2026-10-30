# Batch test (KLayout -z -nc -rx -r, package installed in salt): crossings of the EM region box and boundary ports.
# OctaDiffTap demo, region box with its bottom edge at y = -35 um: it cuts the three TopMetal2 feeds (signal) and
# the Metal1 ground, above the hand-drawn ports at y = -42 (outside the box). Ground: marked on Metal1.
import os
import pya
from klayout_em_export.boundary import create_ports, find_crossings
from klayout_em_export.connectivity import check_ground
from klayout_em_export.ports import collect_ports
from klayout_em_export.stackup import Stackup

st = Stackup(r"D:\github-claude\gds2palace_ihp_sg13g2\XML_stackup\latest\IHP\SG13G2_FEM_200um.xml")
view = pya.LayoutView(True)
idx = view.load_layout(r"D:\Palace_testcases\demo_mcp\OctaDiffTap_0n50_ports3.gds", True)
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
class NoUndo:   # a standalone LayoutView in batch mode has no undo manager: view.transaction() crashes there
    def transaction(self, text): pass
    def commit(self): pass
    def add_missing_layers(self): pass
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
OUT = os.environ.get("OUT", r"C:/Users/volker/AppData/Local/Temp/claude/d--github-claude/87a3a291-8748-4bcb-85dc-b9bbb004dff7/scratchpad/boundary")
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
