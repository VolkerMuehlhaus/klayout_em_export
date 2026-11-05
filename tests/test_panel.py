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

view = pya.LayoutView(True)   # editable, as in the GUI edit mode
idx = view.load_layout(layout_file("BM_Ardavan_Rahimian_with_ports_partial.gds"), True)
cv = view.cellview(idx)
ly = cv.layout()
ly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))   # not set_stackup: keeps ~/.klayout_em_export.json


_load_settings = gui._load_settings
gui._load_settings = lambda: dict(_load_settings(), panel_mode="em")    # the EM steps, whatever the user last chose
gui.create_boundary_ports = lambda v, c, crossings: create_ports(NoUndo(), c.cell, Stackup(STACKUP), crossings)
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
panel._create_proposed()
show(panel, "after Create Proposed Ports")
