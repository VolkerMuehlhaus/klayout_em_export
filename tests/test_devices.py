# Batch test (KLayout -z -nc -rx -r, package installed in salt): device replacement on 50_ghz_mpa_core.gds
# (one npn13G2, rotated). Needs the SG13G2 PDK: loaded with ../klayout_em_export_tests/pdk_env.py (sparse checkout by
# its setup_pdk.sh); run with KLAYOUT_PATH/KLAYOUT_HOME pointing to an empty folder, as its run_all.sh does.
import os
import sys
import pya
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "klayout_em_export_tests"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))   # not via salt here
from pdk_env import load_pdk
from klayout_em_export.devices import device_level_layers, device_shapes, find_devices, mark_replaced, port_line, replace
from klayout_em_export.ports import collect_ports
from klayout_em_export.stackup import Stackup

load_pdk()
st = Stackup(r"D:\github-claude\gds2palace_ihp_sg13g2\XML_stackup\latest\IHP\SG13G2_FEM_200um.xml")
ly = pya.Layout()
ly.technology_name = "sg13g2"
ly.read(r"D:\github-claude\klayout_em_export_tests\testcases\50_ghz_mpa_core.gds")
cell = next(c for c in ly.top_cells() if not c.name.startswith("$$$"))
dbu = ly.dbu

devices, unknown = find_devices(ly, cell, st)
print("unknown/unsupported:", unknown)
for d in devices:
    print(f"device {d.id} {d.pcell} {d.params} bbox {d.bbox.to_dtype(dbu)} problems {d.problems}")
    for t, (layer, box) in sorted(d.terminals.items()):
        print(f"   {t}: pin on layer {layer} {box.to_dtype(dbu)} -> port line {port_line(d, t).to_dtype(dbu)}")
print("device level layers:", sorted(device_level_layers(st)))


class NoUndo:   # a standalone layout in batch mode has no undo manager
    def transaction(self, text): pass
    def commit(self): pass
    def add_missing_layers(self): pass


print("replace:", replace(NoUndo(), cell, st, devices))
again = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
print("found again as replaced:", [(d.id, d.replaced, d.ports) for d in again])
for layer, port in sorted(collect_ports(ly, cell, stackup=st).items()):
    print(f"   port {port.number}: {port.settings} at {[str(s.bbox().to_dtype(dbu)) for s, t, _ in port.items]}"
          f" metals at the port: {sorted(port.available or [])}")
print("REF patch:", [str(s.dbbox()) for s in cell.shapes(ly.find_layer(300, 0)).each()])
removed = device_shapes(ly, again, st)
print("device shapes removed at export:", {l: r.count() for l, r in sorted(removed.items())})

# export with the device replaced: its shapes below Metal1 are removed, ports and REF patch are kept
import json
from klayout_em_export.devices import device_shapes as _ds
from klayout_em_export.export import export_flat
from klayout_em_export.ports import export_numbering, port_map, simcfg_ports
from klayout_em_export.simcfg import write_simcfg
OUT = os.environ.get("OUT", r"C:/Users/volker/AppData/Local/Temp/claude/d--github-claude/87a3a291-8748-4bcb-85dc-b9bbb004dff7/scratchpad/npn")
os.makedirs(OUT, exist_ok=True)
gds = os.path.join(OUT, "mpa_core_npn_em.gds")
ports = collect_ports(ly, cell, stackup=st)
numbering = export_numbering(ports)
result = export_flat(ly, cell, st, gds, port_layers=numbering, remove=removed)
if os.path.exists(gds.replace(".gds", ".simcfg")):
    os.remove(gds.replace(".gds", ".simcfg"))
write_simcfg(gds.replace(".gds", ".simcfg"), gds, st.path, cell.name, ports=simcfg_ports(ports, numbering))
pm = port_map(ports, numbering)
json.dump(pm, open(gds.replace(".gds", "_portmap.json"), "w"), indent=2)
print("simulated ports:", [(r["port"], r["layout_port"], r.get("device", "").split("@")[0], r.get("terminal", "")) for r in pm["ports"] if r["in_simcfg"]])
check = pya.Layout(); check.read(gds)
dev_box = again[0].bbox
for layer, name in ((1, "Activ"), (6, "Cont"), (8, "Metal1"), (19, "Via1"), (10, "Metal2"), (300, "REF")):  # Metal1: B, C strips stay, E islands go
    li = check.find_layer(layer, 0)
    inside = 0 if li is None else (pya.Region(check.top_cell().begin_shapes_rec(li)) & pya.Region(dev_box)).count()
    print(f"   exported {name:7s} polygons inside the device box: {inside}")

# EM panel: Devices step before and after Replace All (fresh view of the file, technology sg13g2)
from klayout_em_export import gui
from klayout_em_export.devices import replace as _replace
from klayout_em_export.gui import META_STACKUP
from klayout_em_export.panel import EMPanel
view = pya.LayoutView(True)
idx = view.load_layout(r"D:\github-claude\klayout_em_export_tests\testcases\50_ghz_mpa_core.gds", "sg13g2", True)
vly = view.cellview(idx).layout()
vly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, st.path, "", True))
view.cellview(idx).cell = next(c for c in vly.top_cells() if not c.name.startswith("$$$"))
gui.replace_devices = lambda v, c: _replace(NoUndo(), c.cell, st, gui.find_layout_devices(c.layout(), c.cell, st)[0])
EMPanel._view = lambda self: (view, view.active_cellview())
panel = EMPanel()
print("devices step:", panel.devices_step.summary.text, "|", panel.devices_detail.text)
panel._replace_devices()
print("after Replace All:", panel.devices_step.summary.text, "|", panel.devices_detail.text)
print("port rows:", [panel.table.item(r, 2).text.encode("ascii", "replace").decode() for r in range(panel.table.rowCount)])

# cascode (1_St_Core_v1.gds): two npn13G2 placed side by side, their cell boxes touch. The REF patches follow the
# pins and must stay separate (also in the export, which merges each layer)
from klayout_em_export.devices import touching_patches
cas = pya.Layout(); cas.technology_name = "sg13g2"
cas.read(r"D:\Palace_testcases\klayout_export\1_St_Core_v1.gds")
ccell = next(c for c in cas.top_cells() if c.name.startswith("Cascode"))
cdev = find_devices(cas, ccell, st)[0]
replace(NoUndo(), ccell, st, cdev)
print("cascode REF patches:", [str(s.dbbox()) for s in ccell.shapes(cas.find_layer(300, 0)).each() if s.property(202)])
print("touching patches:", touching_patches(cas, ccell, st))
cgds = os.path.join(OUT, "cascode_em.gds")
cports = collect_ports(cas, ccell, stackup=st)
export_flat(cas, ccell, st, cgds, port_layers=export_numbering(cports), remove=device_shapes(cas, mark_replaced(cas, ccell, find_devices(cas, ccell, st)[0]), st))
cchk = pya.Layout(); cchk.read(cgds)
print("exported REF polygons:", [str(p.bbox().to_dtype(cchk.dbu)) for p in pya.Region(cchk.top_cell().shapes(cchk.find_layer(300, 0))).merged().each()])
