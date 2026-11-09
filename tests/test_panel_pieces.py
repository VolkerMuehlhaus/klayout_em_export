# Batch test (KLayout -z -nc -rx -r): the EM panel on a split region. A 480 um coplanar line on TopMetal2 with
# line-end ports and two EM region boxes without numbers (drawn by hand): the panel numbers them, shows both pieces,
# proposes one port wall port per piece at the cut, creates them, and shows each port's number in its piece and in
# the joined result. In batch mode there is no main window: the panel gets the view through a stand-in for _view().
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, out_dir

import pya
from klayout_em_export import gui
from klayout_em_export.boundary import create_ports
from klayout_em_export.gui import META_STACKUP
from klayout_em_export.panel import EMPanel
from klayout_em_export.pipeline import META_GROUND, NoUndo
from klayout_em_export.ports import PROP_KEY, PortSettings
from klayout_em_export.regions import number_pieces, read_pieces
from klayout_em_export.stackup import Stackup

OUT = out_dir("test_panel_pieces")
failures = []


def check(ok, text):
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failures.append(text)


def ascii(text):   # the Windows console of KLayout's Python cannot print the check marks and arrows
    for symbol, word in (("✓", "OK"), ("⚠", "WARN"), ("✗", "ERR"), ("→", "->"), ("–", "-")):
        text = text.replace(symbol, word)
    return text


# the layout, written and loaded into a view as a user would open it
ly = pya.Layout()
cell = ly.create_cell("line")
um = lambda v: round(v / ly.dbu)
m = cell.shapes(ly.layer(134, 0))
for box in ((0, 15, 480, 55), (0, -55, 480, -15), (1, -5, 479, 5)):
    m.insert(pya.Box(um(box[0]), um(box[1]), um(box[2]), um(box[3])))
for layer, direction, x0 in ((201, "X", 0), (202, "-X", 479)):
    cell.shapes(ly.layer(layer, 0)).insert(pya.Box(um(x0), um(-5), um(x0 + 1), um(5)),
                                           ly.properties_id([[PROP_KEY, PortSettings(direction, target="TopMetal2").encode()]]))
region = cell.shapes(ly.layer(800, 0))
region.insert(pya.Box(um(0), um(-55), um(240), um(55)))
region.insert(pya.Box(um(240), um(-55), um(480), um(55)))
path = os.path.join(OUT, "split_line.gds")
ly.write(path)

view = pya.LayoutView(True)
idx = view.load_layout(path, True)
cv = view.cellview(idx)
layout = cv.layout()
layout.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))
layout.add_meta_info(pya.LayoutMetaInfo(META_GROUND, json.dumps([[134, um(100), um(30)], [134, um(100), um(-30)]]),
                                        "", True))

_load_settings = gui._load_settings
gui._load_settings = lambda: dict(_load_settings(), panel_mode="em")
gui.create_boundary_ports = lambda v, c, crossings, port_wall=False: create_ports(NoUndo(), c.cell, Stackup(STACKUP),
                                                                               crossings, port_wall=port_wall)
gui.number_pieces = lambda v, c: number_pieces(c.layout(), c.cell)     # no undo manager in batch mode
EMPanel._view = lambda self: (view, view.active_cellview())


def rows(panel):
    return [[ascii(panel.table.item(r, c).text) for c in range(panel.table.columnCount)] for r in range(panel.table.rowCount)]


panel = EMPanel()
print("region:", ascii(panel.region_step.summary.text), "| ports:", ascii(panel.ports_step.summary.text))
for r in rows(panel):
    print("   ", r)
pieces, _ = read_pieces(layout, cv.cell)
check([p.name for p in pieces] == ["p1", "p2"], f"the panel numbered the two boxes: {pieces}")
check("2 EM region pieces" in panel.region_step.summary.text, "the Region step names the two pieces")
check([panel.piece_choice.itemText(i) for i in range(panel.piece_choice.count)] == ["p1", "p2"] and
      not panel.piece_choice.isHidden(), "the piece choice lists p1, p2")
check(len(panel.piece_markers) == 4, f"an outline and a name per piece in the view: {len(panel.piece_markers)}")
proposed = [r[2] for r in rows(panel) if r[4].startswith("proposed")]
check(len(proposed) == 2 and any(t.startswith("p1:") and "cut to p2" in t for t in proposed) and
      any(t.startswith("p2:") and "cut to p1" in t for t in proposed), f"one proposed cut port per piece: {proposed}")
check(panel.result is not None and panel.result.net, "the Ground step has the ground of the chosen piece")

panel._create_proposed()
after = rows(panel)
for r in after:
    print("   ", r)
check(not any(r[4].startswith("proposed") for r in after), "after Create Proposed Ports nothing is proposed")
numbers = {r[0]: r[3] for r in after}
check(numbers.get("1") == "p1 #1, joined #1" and numbers.get("2") == "p2 #1, joined #2",
      f"outer ports: their number in the piece and in the joined result: {numbers}")
check(numbers.get("3", "").startswith("p1 #") and numbers.get("4", "").startswith("p2 #"),
      f"the cut ports: one in each piece: {numbers}")
check(all(r[4] == "ok" for r in after), f"the ports at the cut pass the port check (zero-width on a box edge): {[r[4] for r in after]}")

panel.piece_choice.setCurrentIndex(1)
check(panel.active_name == "p2", f"choosing p2 checks p2: {panel.active_name}")

print("FAIL: " + "; ".join(failures) if failures else "all passed")
