# Batch test (KLayout -z -nc -rx -r, package installed in salt): metal edge / gap / metals at a port, on a layout
# given by GDS and STACKUP (environment). Default: the OctaDiffTap demo with three TopMetal2 feeds at y = -42.
import os
import pya
from klayout_em_export.locate import edge_at, gap_at, metals_at, next_port_layer
from klayout_em_export.stackup import Stackup

gds = os.environ.get("GDS", r"D:\Palace_testcases\demo_mcp\OctaDiffTap_0n50_ports3.gds")
st = Stackup(os.environ.get("STACKUP", r"D:\github-claude\gds2palace_ihp_sg13g2\XML_stackup\latest\IHP\SG13G2_FEM_200um.xml"))
ly = pya.Layout(); ly.read(gds); cell = ly.top_cell()
um = lambda x, y: pya.Point(round(x / ly.dbu), round(y / ly.dbu))
tol = round(0.5 / ly.dbu)

for x, y in [(33.7, -42.2), (33.7, -41.8), (39.0, -41.0), (0, 0)]:
    e = edge_at(ly, cell, st, um(x, y), tol)
    g = gap_at(ly, cell, st, um(x, y), round(20 / ly.dbu))
    print(f"click ({x}, {y}): edge {e and (e[0], str(e[1].to_dtype(ly.dbu)))}  gap {g and (g[0], str(g[1].to_dtype(ly.dbu)), g[2])}")
    if e:
        print("   metals at that edge:", metals_at(ly, cell, st, e[1].bbox()))
print("next port layer:", next_port_layer(ly, cell))
