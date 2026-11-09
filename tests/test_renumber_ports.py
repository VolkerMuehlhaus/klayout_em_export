# Batch test (KLayout -z -nc -rx -r): renumber ports after the fact (the ports table's right-click menu): Set Number
# moves a port to a number and shifts the ports in between by one place, Move Up/Down swaps with the neighbour;
# shapes keep their properties (settings, device tag), a port in a subcell moves too, no temporary layer is left,
# and a stackup layer inside 201..299 is skipped.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP

import pya
from klayout_em_export import gui
from klayout_em_export.gui import META_STACKUP
from klayout_em_export.ports import DEVICE_KEY, PROP_KEY, PortSettings
from klayout_em_export.stackup import Stackup

failures = []


def check(ok, text):
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failures.append(text)


view = pya.LayoutView(True)
view.transaction = lambda text: None    # a standalone view crashes on undo steps in batch (pipeline.NoUndo)
view.commit = lambda: None
view.add_missing_layers = lambda: None
gui.backup_original = lambda layout: None
ly = pya.Layout()
top = ly.create_cell("top")
sub = ly.create_cell("sub")
top.insert(pya.CellInstArray(sub.cell_index(), pya.Trans()))
um = lambda v: round(v / ly.dbu)
tagged = ly.properties_id([[PROP_KEY, PortSettings("Z", "Metal1", "REF_FOR_TRANSISTOR").encode()],
                           [DEVICE_KEY, "device:npn13G2@0,0:B"]])
for layer, name, x, cell, props in ((201, "A", 0, top, 0), (202, "B", 10, top, 0), (203, "C", 20, sub, 0),
                                    (204, "D", 30, top, tagged)):
    box = pya.Box(um(x), 0, um(x + 1), um(5))
    if props:
        cell.shapes(ly.layer(layer, 0)).insert(box, props)
    else:
        cell.shapes(ly.layer(layer, 0)).insert(box)
path = os.path.join(os.environ.get("TEMP", "/tmp"), "renumber_ports.gds")
ly.write(path)
idx = view.load_layout(path, True)
cv = view.cellview(idx)
layout = cv.layout()
names = {0: "A", 10: "B", 20: "C", 30: "D"}


def where():
    """{port number: name} from the x position of each port shape, through the hierarchy"""
    out = {}
    for layer in range(201, 300):
        li = layout.find_layer(layer, 0)
        if li is None:
            continue
        it = layout.top_cell().begin_shapes_rec(li)
        while not it.at_end():
            out[layer - 200] = names[round(it.shape().bbox().transformed(it.trans()).left * layout.dbu)]
            it.next()
    return out


check(where() == {1: "A", 2: "B", 3: "C", 4: "D"}, f"start: {where()}")
gui.renumber_port(view, cv, 204, 202)
check(where() == {1: "A", 2: "D", 3: "B", 4: "C"}, f"Set Number 4 -> 2, the others move up one place: {where()}")
li = layout.find_layer(202, 0)
shape = next(layout.top_cell().shapes(li).each())
check(shape.property(DEVICE_KEY) == "device:npn13G2@0,0:B" and shape.property(PROP_KEY) is not None,
      "the moved port keeps its settings and device tag")
gui.renumber_port(view, cv, 203, 202)
check(where() == {1: "A", 2: "B", 3: "D", 4: "C"}, f"Move Up of port 3: a swap with port 2: {where()}")
gui.renumber_port(view, cv, 202, 205)
check(where() == {1: "A", 2: "D", 3: "C", 5: "B"}, f"Set Number 2 -> 5 (5 was free): {where()}")
infos = [str(layout.get_info(li)) for li in layout.layer_indexes()]
print("layers:", infos)
check(sorted(infos) == ["201/0", "202/0", "203/0", "204/0", "205/0"], f"no temporary layer left: {infos}")
holder = {layout.cell(ci).name: [str(layout.get_info(li)) for li in layout.layer_indexes()
                                 if not layout.cell(ci).shapes(li).is_empty()] for ci in range(layout.cells())}
print("shapes per cell:", holder)
check("203/0" in holder.get("sub", []), "the subcell's port C moved within the subcell (now 3)")

# a stackup layer inside 201..299 is not a port number: it is skipped
layout.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))
allowed = gui.port_numbers(layout)
gaps = [l for l in range(201, 300) if l not in allowed]
print("stackup layers in 201..299:", gaps)
if gaps:
    g = gaps[0]
    below = max(l for l in allowed if l < g)
    above = min(l for l in allowed if l > g)
    layout.top_cell().shapes(layout.layer(above, 0)).insert(pya.Box(um(40), 0, um(41), um(5)))
    names[40] = "E"
    gui.renumber_port(view, cv, above, allowed[allowed.index(above) - 1])
    check(where().get(below - 200) == "E" and g - 200 not in where(),
          f"Move Up over the stackup layer {g}: from {above - 200} to {below - 200}")
print("FAIL: " + "; ".join(failures) if failures else "all passed")
