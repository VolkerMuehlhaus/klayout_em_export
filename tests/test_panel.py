# Batch test (KLayout -z -nc -rx -r, package installed in salt): the EM panel checklist on the user's
# BM_Ardavan_Rahimian_with_ports_partial.gds (ports 1-8, EM region box on 800/0 that keeps port 1 and cuts five
# conductors). In batch mode there is no main window: the panel gets the view through a stand-in for _view().
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, layout_file

import pya
from klayout_em_export import gui
from klayout_em_export.pipeline import NoUndo   # a standalone layout in batch mode has no undo manager
from klayout_em_export.boundary import create_ports
from klayout_em_export.gui import META_STACKUP
from klayout_em_export.panel import EMPanel
from klayout_em_export.stackup import Stackup
from klayout_em_export.ports import collect_ports

view = pya.LayoutView(True)   # editable, as in the GUI edit mode
idx = view.load_layout(layout_file("BM_Ardavan_Rahimian_with_ports_partial.gds"), True)
cv = view.cellview(idx)
ly = cv.layout()
ly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))   # not set_stackup: keeps ~/.klayout_em_export.json


_load_settings = gui._load_settings
gui._load_settings = lambda: dict(_load_settings(), panel_mode="em")    # the EM steps, whatever the user last chose
gui.create_boundary_ports = lambda v, c, crossings, port_wall=False: create_ports(NoUndo(), c.cell, Stackup(STACKUP), crossings,
                                                                               port_wall=port_wall)
EMPanel._view = lambda self: (view, view.active_cellview())


def ascii(text):   # the Windows console of KLayout's Python cannot print the check marks and arrows
    for symbol, word in (("\u2713", "OK"), ("\u26a0", "WARN"), ("\u2717", "ERR"), ("\u2192", "->"), ("\u2013", "-")):
        text = text.replace(symbol, word)
    return text


def show(panel, title):
    print(f"## {title}")
    for step in (panel.stackup_step, panel.region_step, panel.ground_step, panel.ports_step):
        print("  ", ascii(step.mark.text.split(">")[1][0]), ascii(step.summary.text))
    for r in range(panel.table.rowCount):
        print("    ", [ascii(panel.table.item(r, c).text) for c in range(panel.table.columnCount)])


panel = EMPanel()
show(panel, "after loading")

# clicking a row highlights, it does not select
panel.table.selectRow(0)
print("row 1 clicked: markers", len(panel.highlight), "| layout selection", sum(1 for _ in view.each_object_selected()))

# a selected port line (e.g. selected by hand) does not change the export region
port_shape = next(ly.top_cell().shapes(ly.find_layer(201, 0)).each())
p = pya.ObjectInstPath(); p.cv_index = idx; p.top = ly.top_cell().cell_index(); p.layer = ly.find_layer(201, 0); p.shape = port_shape
view.object_selection = [p]
print("port line selected -> region:", gui.region_source(view, cv)[1])
view.clear_selection()

panel._create_proposed()
show(panel, "after Create Proposed Ports")

# without the boundary ports 9-13 (as before they were created): proposed rows, then Create
for layer in range(209, 214):
    li = ly.find_layer(layer, 0)
    if li is not None:
        ly.top_cell().shapes(li).clear()
panel.refresh()
show(panel, "boundary ports removed")
# as port walls: the proposed rows name the port wall, the new ports are in-plane ports on the cut metal
panel.port_walls.setChecked(True)
rows = [ascii(panel.table.item(r, 2).text) for r, (kind, _) in enumerate(panel.rows) if kind == "proposed"]
print("proposed as port walls:", rows)
if not rows or not all("port wall" in t for t in rows):
    print("FAIL: proposed rows do not name the port wall")
before = set(collect_ports(ly, ly.top_cell()))
panel._create_proposed()
made = [p.settings for layer, p in collect_ports(ly, ly.top_cell()).items() if layer not in before]
print("made as port walls:", [str(s) for s in made])
if not made or any(s.is_via for s in made):
    print("FAIL: Create Proposed Ports as port walls made via ports")
for layer in set(collect_ports(ly, ly.top_cell())) - before:
    ly.top_cell().shapes(ly.find_layer(layer, 0)).clear()
panel.port_walls.setChecked(False)
panel.refresh()
panel._create_proposed()
show(panel, "after Create Proposed Ports")
