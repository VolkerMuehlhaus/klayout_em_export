# Batch test (KLayout -z -nc -rx -r): export a GDS with a stackup, whole cell and clipped to a box.
# Environment: GDS, STACKUP, OUT (output folder), optional BOX="x1,y1,x2,y2" in um.
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
import pya
from klayout_em_export.stackup import Stackup
from klayout_em_export.export import export_flat
from klayout_em_export.simcfg import write_simcfg

gds, stackup_file, out = os.environ["GDS"], os.environ["STACKUP"], os.environ["OUT"]
os.makedirs(out, exist_ok=True)
stackup = Stackup(stackup_file)
print("stackup GDS layers:", stackup.gds_layers())
print("metals:", stackup.metal_names())

layout = pya.Layout()
layout.read(gds)
cell = next(c for c in layout.top_cells() if c.name != "$$$CONTEXT_INFO$$$")
name = os.path.splitext(os.path.basename(gds))[0]

for tag, box in [("whole", None)] + ([("box", pya.DBox(*map(float, os.environ["BOX"].split(","))))] if os.environ.get("BOX") else []):
    path = os.path.join(out, f"{name}_{tag}.gds")
    result = export_flat(layout, cell, stackup, path, box=box)
    print(f"### {tag}\n" + result.report())
    write_simcfg(path.replace(".gds", ".simcfg"), path, stackup_file, result.cellname)
