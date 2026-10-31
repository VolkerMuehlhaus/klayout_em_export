# Batch test (KLayout -z -nc -rx -r, package installed in salt): port properties, collection, simcfg list, flat export, dialog.
# Output: OUT (default: a temp folder, see testpaths.py).
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import EXAMPLE_BCE, out_dir
import json
import pya
from klayout_em_export.ports import PortSettings, collect_ports, check_ports, simcfg_ports, PROP_KEY
from klayout_em_export.stackup import Stackup
from klayout_em_export.export import export_flat
EX = EXAMPLE_BCE
OUT = out_dir("kee")
st = Stackup(os.path.join(EX, "SG13G2_100um_bce_ports.xml"))
ly = pya.Layout(); ly.read(os.path.join(EX, "50_ghz_mpa_core_bce_ports.gds")); cell = ly.top_cell()
# settings as in the example's .simcfg; port 5 left without settings, port 4 with a wrong layer name
spec = {201: PortSettings("Z", "Metal3", "TopMetal2"), 202: PortSettings("Z", "Metal3", "TopMetal2"),
        203: PortSettings("Z", "Metal2", "REF_FOR_TRANSISTOR"), 204: PortSettings("-Z", "Metal2", "REF_TRANSISTOR")}
for layer, s in spec.items():
    for sh in cell.shapes(ly.find_layer(layer, 0)).each():
        sh.set_property(PROP_KEY, s.encode())
print(spec[204].encode(), "->", PortSettings.decode(spec[204].encode()))
ports = collect_ports(ly, cell)
print("\n".join(check_ports(collect_ports(ly, cell, stackup=st), st)))
print(json.dumps(simcfg_ports(ports)[3:5]))
# properties survive the flat export?
export_flat(ly, cell, st, os.path.join(OUT, "ports_export.gds"))
l2 = pya.Layout(); l2.read(os.path.join(OUT, "ports_export.gds"))
print("after export:", {k: str(v.settings) for k, v in collect_ports(l2, l2.top_cell()).items()})
# dialog construction (headless, if Qt widgets are available)
try:
    from klayout_em_export.gui import PortDialog
    from klayout_em_export.gui import META_STACKUP
    ly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, st.path, "", True))   # not set_stackup: keeps ~/.klayout_em_export.json
    d = PortDialog(ly, lambda s: ["Metal3", "Metal2"], spec[203], 1)
    print("dialog:", d.result_settings().encode())
    d.direction.setCurrentText("X"); d.target.setCurrentText("Metal3"); d._update()
    print("dialog X:", d.result_settings().encode(), "from enabled:", d.from_layer.isEnabled())
except Exception as e:
    print("dialog test skipped/failed:", repr(e))
# a via port drawn as a zero-height box on the edge of a clipped region must be collected and exported
c2 = ly.create_cell("ZERO")
c2.shapes(ly.layer(206, 0)).insert(pya.Box(0, 0, 5000, 0)).set_property(PROP_KEY, spec[201].encode())
c2.shapes(ly.layer(30, 0)).insert(pya.Box(0, 0, 5000, 1000))
clip = pya.DBox(0, 0, 5, 1)
print("zero-height port in clipped region:", list(collect_ports(ly, c2, clip.to_itype(ly.dbu))),
      export_flat(ly, c2, st, os.path.join(OUT, "zero_port.gds"), box=clip).kept)

# export dialog preview (stackup from the layout's meta info, region clipped)
from klayout_em_export.gui import ExportDialog
class CellView:   # the parts of pya.CellView the dialog uses
    def __init__(self, layout, cell): self._layout, self.cell = layout, cell
    def layout(self): return self._layout
    def filename(self): return os.path.join(OUT, "dialog_test.gds")
d = ExportDialog(CellView(ly, cell), pya.DBox(-80, -60, -30, -30), "test region")
print("export dialog: stackup", d.stackup_label.text, "| output", d.output.text, "| export enabled", d.export_button.isEnabled())
print("  ports:", d.ports.text.replace(chr(10), " | "))
