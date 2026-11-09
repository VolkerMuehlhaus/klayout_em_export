# Batch test (KLayout -z -nc -rx -r): the Draw Region tool. Its mouse events are driven on a view of a layout whose
# top cell holds an instance (as an inductor of a PDK layout): a drag draws the EM region box on the grid, a second
# drag replaces it, Shift+drag adds a box (a piece of a split region), a plain drag over a split region asks first,
# and in a cell descended into, the drawn box lands in that cell at the place it was drawn.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import out_dir

import pya
from klayout_em_export import gui
from klayout_em_export.pipeline import EM_REGION
from klayout_em_export.tool import RegionTool

OUT = out_dir("test_region_tool")
failures = []


def check(ok, text):
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failures.append(text)


ly = pya.Layout()
top = ly.create_cell("top")
coil = ly.create_cell("coil")
coil.shapes(ly.layer(134, 0)).insert(pya.Box(-80000, -1000, 80000, 160000))
top.insert(pya.CellInstArray(coil.cell_index(), pya.Trans(pya.Trans.R90, pya.Vector(500000, 20000))))
path = os.path.join(OUT, "with_instance.gds")
ly.write(path)

view = pya.LayoutView(True)
idx = view.load_layout(path, True)
view.set_config("grid-micron", "0.5")
view.transaction = lambda text: None    # a standalone view crashes on undo steps in batch (pipeline.NoUndo)
view.commit = lambda: None
cv = view.cellview(idx)
layout = cv.layout()
tool = RegionTool(view)
tool.grab_mouse = tool.ungrab_mouse = lambda: None    # only a tool made by its factory may grab the mouse
L, S = pya.ButtonState.LeftButton, pya.ButtonState.LeftButton | pya.ButtonState.ShiftKey


def drag(a, b, buttons=L):
    tool.mouse_button_pressed_event(pya.DPoint(*a), buttons, True)
    tool.mouse_moved_event(pya.DPoint(*b), buttons, True)
    check(tool.marker is not None, f"a rubber band while dragging to {b}")
    tool.mouse_button_released_event(pya.DPoint(*b), buttons, True)
    check(tool.marker is None, "the rubber band is gone after the release")


def boxes(cell):
    li = layout.find_layer(*EM_REGION)
    return [] if li is None else sorted(str(s.dbbox()) for s in cell.shapes(li).each())


drag((300.2, -20.1), (620.3, 120.4))
check(boxes(cv.cell) == [str(pya.DBox(300, -20, 620.5, 120.5))], f"a drag draws the region on the grid: {boxes(cv.cell)}")
drag((310, -10), (600, 100))
check(boxes(cv.cell) == [str(pya.DBox(310, -10, 600, 100))], f"a second drag replaces it: {boxes(cv.cell)}")
drag((600, -10), (700, 100), S)
check(len(boxes(cv.cell)) == 2, f"Shift+drag adds a piece: {boxes(cv.cell)}")
asked = []
answer = pya.MessageBox.No
pya.MessageBox.question = lambda *args: asked.append(args[1]) or answer
drag((300, -20), (700, 120))
check(asked and "split into 2 pieces" in asked[0] and len(boxes(cv.cell)) == 2, "over a split region: asked, No keeps it")
answer = pya.MessageBox.Yes
drag((300, -20), (700, 120))
check(len(boxes(cv.cell)) == 1, "Yes replaces the pieces by the box")
drag((10, 10), (10, 50))
check(len(boxes(cv.cell)) == 1, "a click without area changes nothing")
check(layout.cell(cv.cell.cell_index()).name == "top", "all in the top cell")

# descended into the instance: drawn in top coordinates, stored in the coil cell's coordinates
view_top = cv.cell                      # the loaded layout's top cell, not the one written above
inst = next(view_top.each_inst())
view.active_cellview().descend([pya.InstElement(inst)])
cv = view.active_cellview()
check(cv.cell.name == "coil", f"descended into {cv.cell.name}")
drag((400, 0), (520, 100))
expected = pya.DBox(400, 0, 520, 100).transformed(inst.dcplx_trans.inverted())
check(boxes(cv.cell) == [str(expected)], f"the box in the coil cell where it was drawn: {boxes(cv.cell)} vs {expected}")
check(len(boxes(view_top)) == 1, "the top cell's region is untouched")
print("FAIL: " + "; ".join(failures) if failures else "all passed")
