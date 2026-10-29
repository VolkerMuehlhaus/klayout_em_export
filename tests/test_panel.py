# Batch test (KLayout -z -nc -rx -r, package installed in salt): the EM panel's port table and row selection,
# on core_transistor_3port_bce with settings on some ports. In batch mode there is no main window, so the panel
# is given the view through a stand-in for _view().
import os
import pya
from klayout_em_export.gui import META_STACKUP
from klayout_em_export.panel import EMPanel
from klayout_em_export.ports import PROP_KEY, PortSettings

EX = r"D:\github-claude\gds2palace_ihp_sg13g2\more_examples\core_transistor_3port_bce"
view = pya.LayoutView(True)   # editable, as in the GUI edit mode (port settings change shapes)
idx = view.load_layout(os.path.join(EX, "50_ghz_mpa_core_bce_ports.gds"), True)
cv = view.cellview(idx)
ly = cv.layout()
ly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, os.path.join(EX, "SG13G2_100um_bce_ports.xml"), "", True))
cell = ly.top_cell()
for layer, s in {201: PortSettings("Z", "Metal3", "TopMetal2"), 203: PortSettings("Z", "Metal2", "REF_FOR_TRANSISTOR"),
                 204: PortSettings("-Z", "Metal5", "TopMetal2")}.items():
    for shape in cell.shapes(ly.find_layer(layer, 0)).each():
        shape.set_property(PROP_KEY, s.encode())

EMPanel._view = lambda self: (view, view.active_cellview())
panel = EMPanel()
print("stackup:", panel.stackup_label.text)
for r in range(panel.table.rowCount):  # property in KLayout's Qt binding
    print("  ", [panel.table.item(r, c).text for c in range(panel.table.columnCount)])
print("region:", panel.region_label.text)
panel.table.selectRow(2)
print("row 3 selected -> layout selection:", [str(o.shape.bbox().to_dtype(ly.dbu)) for o in view.each_object_selected()])
