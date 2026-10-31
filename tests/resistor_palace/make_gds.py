# Test layout: six SG13G2 resistor cells, each between two via ports (Metal1 -> Metal2 plate), as in
# gds2palace more_examples/derived_layers_and_resistors. Ports 2k+1 (top head) and 2k+2 (bottom head).
import json

import gdspy

CASCODE = r"D:/Palace_testcases/klayout_export/guide/cascode.gds"
EXAMPLE = r"D:/github-claude/gds2palace_ihp_sg13g2/more_examples/derived_layers_and_resistors/resistors_with_ports.gds"
CELLS = [(CASCODE, "rsil_CDNS_785835985925"), (CASCODE, "rhigh_CDNS_785835985924"),
         (CASCODE, "rhigh_CDNS_785835985923"), (EXAMPLE, "rsil_CDNS_786372201261"),
         (EXAMPLE, "rppd_CDNS_786372201260"), (EXAMPLE, "rhigh_CDNS_786372201262")]
LEAD = 1.0      # Metal1 lead beyond each head (um)

lib = gdspy.GdsLibrary(unit=1e-6, precision=1e-9)
top = lib.new_cell("resistors")
info = []
x = 0.0
for k, (path, name) in enumerate(CELLS):
    src = gdspy.GdsLibrary(infile=path).cells[name]
    cell = src.copy(name, deep_copy=True)
    lib.add(cell)
    top.add(gdspy.CellReference(cell, (x, 0)))
    heads = sorted((p for (l, d), ps in cell.get_polygons(by_spec=True).items() if (l, d) == (8, 0) for p in ps),
                   key=lambda p: p[:, 1].min())
    lo, hi = heads[0], heads[-1]
    x1, x2 = lo[:, 0].min() + x, lo[:, 0].max() + x
    yb, yt = lo[:, 1].min() - LEAD, hi[:, 1].max() + LEAD
    top.add(gdspy.Rectangle((x1, yb), (x2, lo[:, 1].max()), layer=8))
    top.add(gdspy.Rectangle((x1, hi[:, 1].min()), (x2, yt), layer=8))
    top.add(gdspy.Rectangle((x1 - 0.6, yb - 0.6), (x2 + 0.6, yt + 0.6), layer=10))
    top.add(gdspy.Rectangle((x1, yt), (x2, yt), layer=201 + 2 * k))
    top.add(gdspy.Rectangle((x1, yb), (x2, yb), layer=202 + 2 * k))
    label = [t.text for t in cell.labels if t.layer == 63][0]
    info.append({"cell": name, "label": label, "ports": [2 * k + 1, 2 * k + 2]})
    x += max(6.0, x2 - x + 5.0)
lib.write_gds("resistor_test.gds")
json.dump(info, open("resistor_test.json", "w"), indent=1)
print(json.dumps(info, indent=1))
