# Batch test (KLayout -z -nc -rx -r, package installed in salt): metal edge / gap / metals at a port, on a layout
# given by GDS and STACKUP (environment). Default: the OctaDiffTap demo with three TopMetal2 feeds at y = -42.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, layout_file

import pya
from klayout_em_export.locate import edge_at, gap_at, metals_at, next_port_layer, via_layers
from klayout_em_export.stackup import Stackup

gds = os.environ.get("GDS", layout_file("OctaDiffTap_0n50_ports3.gds"))
st = Stackup(os.environ.get("STACKUP", STACKUP))
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

# Only the given layers are searched (the EM Port tool passes the visible ones)
p = um(33.7, -42.2)
found = edge_at(ly, cell, st, p, tol)
top = dict((l.name, l.layer) for l in st.layers)[found[0]]
others = {l.layer for l in st.layers if l.is_metal} - {top}
print("ok  " if edge_at(ly, cell, st, p, tol, {top}) == found else "FAIL",
      f"edge with only {found[0]} searched: the same edge")
hidden = edge_at(ly, cell, st, p, tol, others)
print("ok  " if hidden is None or hidden[0] != found[0] else "FAIL",
      f"edge with {found[0]} hidden: {hidden and hidden[0]}")
print("ok  " if edge_at(ly, cell, st, p, tol, set()) is None else "FAIL", "edge with nothing visible: none")
print("ok  " if gap_at(ly, cell, st, um(39.0, -41.0), round(20 / ly.dbu), set()) is None else "FAIL",
      "gap with nothing visible: none")

# A new via port goes from the clicked metal down to the next metal at the port
here = ["TopMetal2", "Metal5", "Metal4", "Metal3"]
for clicked, expected in [("Metal4", ("Metal4", "Metal3")), ("TopMetal2", ("TopMetal2", "Metal5")),
                          ("Metal3", ("Metal3", "Metal4")), ("Metal1", ("", ""))]:
    got = via_layers(here, clicked)
    print("ok  " if got == expected else "FAIL", f"via port on a {clicked} edge with {here}: from/to {got}")
print("ok  " if via_layers(["Metal3"], "Metal3") == ("Metal3", "") else "FAIL", "only the clicked metal: no other end")
e = edge_at(ly, cell, st, um(33.7, -42.2), tol)
print("via port at the TopMetal2 feed:", via_layers(metals_at(ly, cell, st, e[1].bbox()), e[0]))
