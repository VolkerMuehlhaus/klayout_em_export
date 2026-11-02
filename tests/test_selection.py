# Batch test (KLayout -z -nc -rx -r, package installed in salt): "selected shapes only" export.
# Selecting all metals of core_transistor_3port_bce but no vias and no ports must give the same layout as the
# whole-cell export, after the selection is completed with the connecting vias and the touching port shapes.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import EXAMPLE_BCE, out_dir

import pya
from klayout_em_export.export import export_flat
from klayout_em_export.locate import drawn_metals
from klayout_em_export.ports import ports_of
from klayout_em_export.selection import Selection
from klayout_em_export.stackup import Stackup

EX = EXAMPLE_BCE
OUT = out_dir("kee")
os.makedirs(OUT, exist_ok=True)
st = Stackup(os.path.join(EX, "SG13G2_100um_bce_ports.xml"))
ly = pya.Layout(); ly.read(os.path.join(EX, "50_ghz_mpa_core_bce_ports.gds")); cell = ly.top_cell()

metal_layers = {layer for _, layer in drawn_metals(st)}
sel = Selection(ly, cell)
for li in ly.layer_indexes():
    if ly.get_info(li).layer in metal_layers:
        it = cell.begin_shapes_rec(li)
        while not it.at_end():
            sel.add_shape(it.shape(), li, it.trans())
            it.next()
print("selected layers:", sorted(sel.regions), "ports:", len(sel.ports))
done = sel.completed(st)
print("added vias:", done.added_vias, "added ports:", done.added_ports)
print("ports:", sorted(ports_of(ly, cell, done.ports, stackup=st)))

a = export_flat(ly, cell, st, os.path.join(OUT, "sel_whole.gds"))
b = export_flat(ly, cell, st, os.path.join(OUT, "sel_shapes.gds"), selection=done)
print("same kept layers and counts as the whole-cell export:", a.kept == b.kept)
la, lb = pya.Layout(), pya.Layout()
la.read(a.gds_path); lb.read(b.gds_path)
diff = 0
for key in a.kept:
    ra = pya.Region(la.top_cell().begin_shapes_rec(la.find_layer(*key)))
    rb = pya.Region(lb.top_cell().begin_shapes_rec(lb.find_layer(*key)))
    diff += (ra ^ rb).area()
print("XOR area against the whole-cell export:", diff)

# only one metal selected: no via may be added (a via needs two selected metals)
one = Selection(ly, cell)
li = ly.find_layer(30, 0)
it = cell.begin_shapes_rec(li)
while not it.at_end():
    one.add_shape(it.shape(), li, it.trans()); it.next()
print("Metal3 only -> added vias:", one.completed(st).added_vias)

# export dialog with a selection: both modes
from klayout_em_export.gui import ExportDialog, META_STACKUP
ly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, st.path, "", True))   # not set_stackup: keeps ~/.klayout_em_export.json
class CellView:   # the parts of pya.CellView the dialog uses
    def __init__(self, layout, cell): self._layout, self.cell = layout, cell
    def layout(self): return self._layout
    def filename(self): return os.path.join(OUT, "dialog_test.gds")
d = ExportDialog(CellView(ly, cell), sel.bbox().to_dtype(ly.dbu), "bounding box of the selected shapes", sel)
for mode in (d.mode_shapes, d.mode_box):
    mode.setChecked(True)
    print(f"mode shapes_only={d.shapes_only()}: region", d.region.text.replace(chr(10), " "))
    print("   ", ascii(d.ports.text.replace(chr(10), " | ")))   # ascii: the marks (⚠) fail in a cp1252 console
