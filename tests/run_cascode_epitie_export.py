# Variant of the cascode test (run_cascode_export.py): the devices' reference patches on SUBGND, the PEC sheet on the
# EPI, instead of REF_FOR_TRANSISTOR, so each gets a DC potential through the substrate (the EPI is tied to ground by
# the ptap guard ring). Output folder: environment OUT. Needs the PDK (tests/pdk_env.py), run like test_devices.py.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, TESTS_DIR, layout_file
import json
import pya
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from pdk_env import load_pdk
from klayout_em_export import tech
from klayout_em_export.devices import (DEVICE_KEY, REF_NAME, device_shapes, find_devices, mark_replaced, replace,
                                       touching_patches, unreplace)
from klayout_em_export.locate import next_port_layer
from klayout_em_export.pipeline import NoUndo, export_em
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports, port_problems
from klayout_em_export.stackup import Stackup

OUT = os.environ["OUT"]
os.makedirs(OUT, exist_ok=True)
load_pdk()
st = Stackup(STACKUP)
ly = pya.Layout(); ly.technology_name = "sg13g2"
ly.read(layout_file("1_St_Core_v1_forEM.gds"))
cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))


print("undo the saved replacement:", unreplace(NoUndo(), cell), "shape(s)")
print("replace:", replace(NoUndo(), cell, st, find_devices(ly, cell, st)[0], include_resistors=True))
devices = mark_replaced(ly, cell, find_devices(ly, cell, st)[0])
print("touching patches:", touching_patches(ly, cell, st))
# the Cas_Bias port, as in run_cascode_export.py
bias_layer = next_port_layer(ly, cell)
cell.shapes(ly.layer(bias_layer, 0)).insert(pya.DBox(-29.205, 8.34, -29.205, 10.97).to_itype(ly.dbu),
                                            ly.properties_id([[PROP_KEY, PortSettings("Z", "Metal2", "Metal5").encode()]]))
print("Cas_Bias port on layer", bias_layer)

# Each device's reference patch moves from REF_FOR_TRANSISTOR (top of Activ, in the SiO2) down to SUBGND, the PEC
# sheet on the EPI, and its ports end there: the reference is wired to the EPI. (Activ under the REF patch would do
# the same, but its top face would then carry two boundaries, Activ's and the REF sheet's, which Palace rejects.)
ref_li = ly.find_layer(st.layer(REF_NAME).layer, 0)
sub = st.layer("SUBGND")
sub_li = ly.layer(sub.layer, 0)
remove = device_shapes(ly, devices, st)
activ = st.layer("Activ").layer
existing = pya.Region(cell.begin_shapes_rec(ly.layer(activ, 0))) - remove.get(activ, pya.Region())
moved = []
for shape in cell.shapes(ref_li).each():
    value = shape.property(DEVICE_KEY)
    if isinstance(value, str) and value.startswith("device:"):
        moved.append((shape.bbox(), shape.prop_id))
patches = pya.Region()
for box, prop_id in moved:
    cell.shapes(sub_li).insert(box, prop_id)
    patches.insert(box)
for shape in [s for s in cell.shapes(ref_li).each() if isinstance(s.property(DEVICE_KEY), str)]:
    shape.delete()
print("moved", len(moved), "patches to SUBGND; touching Activ that is exported:",
      not patches.interacting(existing).is_empty())
for layer in range(201, 300):                # device ports: to SUBGND instead of REF_FOR_TRANSISTOR
    li = ly.find_layer(layer, 0)
    if li is None:
        continue
    for shape in list(cell.shapes(li).each()):
        settings = PortSettings.decode(shape.property(PROP_KEY))
        if settings is None or settings.to_layer != REF_NAME:
            continue
        settings.to_layer = sub.name
        props = [[PROP_KEY, settings.encode()], [DEVICE_KEY, shape.property(DEVICE_KEY)]]
        box = shape.bbox()
        shape.delete()
        cell.shapes(li).insert(box, ly.properties_id(props))

ports = collect_ports(ly, cell, stackup=st)
problems = {p.number: port_problems(p, st) for p in ports.values() if port_problems(p, st)}
print("port problems:", problems)
gds = os.path.join(OUT, "cascode_epitie_em.gds")
if os.path.exists(gds.replace(".gds", ".simcfg")):     # a fresh .simcfg, not setupEM settings of an earlier run
    os.remove(gds.replace(".gds", ".simcfg"))
pm = json.load(open(export_em(ly, cell, st, gds, tech.for_layout(ly)[0])["portmap"]))     # as the GUI's export
for row in pm["ports"]:
    print(row["port"], "<- layout", row["layout_port"], row.get("device", "").split("@")[0], row.get("terminal", ""),
          row["settings"], "exported", row.get("direction"))
