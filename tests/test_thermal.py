# Batch test (KLayout -z -nc -rx -r): thermal export (thermal.py) of the user's cascode 1_St_Core_v1_forEM.gds.
# Each device becomes one heat source on a marker layer of its own, from the PDK's HeatTrans/HeatRes shapes, in the
# z range of Activ; the devices stay as drawn; EM ports and REF patches are left out; an export again keeps the
# powers, the instance names and the boundaries set in setupThermal. Needs the PDK, run like test_devices.py.
# Output: OUT (default: a temp folder, see testpaths.py).
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, TESTS_DIR, out_dir, palace_testcases

import pya
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))   # not via salt here
from pdk_env import load_pdk
from klayout_em_export import tech
from klayout_em_export.stackup import Stackup
from klayout_em_export.thermal import export_thermal, heat_sources, heat_target, marker_layers

OUT = out_dir("thermal")
failed = []


def check(ok, text):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)


read_back = []      # the layouts read: a Region from a shape iterator needs its layout alive


def shapes(path):
    """{(layer, datatype): Region} of the exported GDS."""
    ly = pya.Layout()
    ly.read(path)
    read_back.append(ly)
    top = ly.top_cell()
    return {(ly.get_info(li).layer, ly.get_info(li).datatype): pya.Region(top.begin_shapes_rec(li))
            for li in ly.layer_indexes()}, ly.dbu


load_pdk()
st = Stackup(STACKUP)
ly = pya.Layout()
ly.technology_name = "sg13g2"
ly.read(palace_testcases("klayout_export", "1_St_Core_v1_forEM.gds"))
cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))
technology = tech.for_layout(ly)[0]
check(heat_target(st, technology) == "Activ", "heat sources in Activ, which has a thickness in the stackup")

# the PDK's heat shapes in the layout: what the export must reproduce, device by device
pdk_heat = pya.Region()
for layer, datatype in technology.HEAT_LAYERS:
    li = ly.find_layer(layer, datatype)
    if li is not None:
        pdk_heat += pya.Region(cell.begin_shapes_rec(li))
print("PDK heat shapes in the cell:", pdk_heat.count(), "area", pdk_heat.area() * ly.dbu ** 2, "um2")

used = {l.layer for l in st.layers} | set(st.gds_layers())
many = marker_layers(st, 120)
check(not set(many) & used and many[0] == 201 and len(many) == 120 and max(many) > 299,
      f"marker layers continue past 299 and skip the stackup's own ({sorted(used & set(range(201, 330)))})")

gds = os.path.join(OUT, "cascode_thermal.gds")
for suffix in (".tsimcfg", "_thermalmap.json"):
    if os.path.exists(gds[:-4] + suffix):
        os.remove(gds[:-4] + suffix)
result = export_thermal(ly, cell, st, gds, technology)
print(result["report"])
thermal_map = json.load(open(result["thermalmap"]))
rows = thermal_map["sources"]
print("sources:", [(r["layer"], r["device"], r["area_um2"], r["polygons"]) for r in rows])
check(result["sources"] == len(rows) == 5, f"one heat source per device: {len(rows)}")
check(not result["bounding_box"] and all(r["heat_area_from"] == "shapes" for r in rows),
      "every heat area from the PDK's shapes")
check(abs(sum(r["area_um2"] for r in rows) - pdk_heat.area() * ly.dbu ** 2) < 1e-6,
      "the heat areas add up to the PDK's heat shapes")
check(thermal_map["outline_layer"] == 201 and [r["layer"] for r in rows] == list(range(202, 207)),
      "region outline on 201, sources on 202..206")

out, dbu = shapes(gds)
check(all((r["layer"], 0) in out and abs(out[(r["layer"], 0)].area() * dbu ** 2 - r["area_um2"]) < 1e-6
          for r in rows), "the GDS has each heat area on its layer")
ref = st.layer("REF_FOR_TRANSISTOR").layer
check((ref, 0) not in out, "no REF_FOR_TRANSISTOR patches (left from the EM replacement)")
em_ports = {key for key in out if 201 <= key[0] <= 299} - {(r["layer"], 0) for r in rows} - {(201, 0)}
check(not em_ports, f"no EM port shapes ({sorted(em_ports)})")
cont = st.layer("Cont").layer
devices_box = pya.Region()
for r in rows:
    devices_box += pya.Region(pya.DBox(*r["bbox_um"]).to_itype(dbu))
check(not (out[(cont, 0)] & devices_box).is_empty(), "the devices' contacts are kept (heat paths)")

cfg = json.load(open(result["tsimcfg"]))
sources = [t for t in cfg["thermal"] if t["type"] == "source"]
check(cfg["application"] == "setupThermal" and len(sources) == 5 and
      all(t["target_layername"] == "Activ" and t["power"] == 0.0 for t in sources),
      ".tsimcfg: 5 sources in Activ, power 0 W")
check([t for t in cfg["thermal"] if t["type"] != "source"] ==
      [{"source_layernum": thermal_map["outline_layer"], "target_layername": "", "type": "constanttemp", "temp": 300.0}],
      ".tsimcfg: one placeholder boundary, on the region outline, without a target layer")

# setupThermal: the boundary's target, powers and a setting; the map: an instance name; export again
for t in cfg["thermal"]:
    if t["type"] == "source":
        t["power"] = 0.001 * (t["source_layernum"] - 200)
cfg["thermal"][-1]["target_layername"] = "BACKSIDEGND"
cfg["saved_values"]["my_setting"] = 42
json.dump(cfg, open(result["tsimcfg"], "w"))
thermal_map["sources"][0]["instance"] = "XQ1"
json.dump(thermal_map, open(result["thermalmap"], "w"))
again = export_thermal(ly, cell, st, gds, technology)
cfg2 = json.load(open(again["tsimcfg"]))
map2 = json.load(open(again["thermalmap"]))
check(again["kept_settings"] and cfg2["saved_values"].get("my_setting") == 42, "export again: settings kept")
check([t["power"] for t in cfg2["thermal"] if t["type"] == "source"] == [0.002, 0.003, 0.004, 0.005, 0.006],
      "export again: powers kept per device")
check([t for t in cfg2["thermal"] if t["type"] == "constanttemp"] == [cfg["thermal"][-1]], "export again: boundary kept")
check(map2["sources"][0]["instance"] == "XQ1", "export again: instance name kept")

# schematic names from LVS: IHP's deck on this cell against a schematic written for the test (Q1, Q2, R1..R3; a
# substrate tap inside Q2's box, a MIM capacitor), flat and with Q1, Q2 in a subcircuit instance Xcore
lvs_dir = os.path.join(TESTS_DIR, "testcases", "lvs_cascode")
for lvsdb, names in (("cascode.lvsdb", ["R1", "R2", "R3", "Q1", "Q2"]),
                     ("cascode_hier.lvsdb", ["R1", "R2", "R3", "XCORE.Q1", "XCORE.Q2"])):
    named = export_thermal(ly, cell, st, gds, technology, lvsdb=os.path.join(lvs_dir, lvsdb))
    map3 = json.load(open(named["thermalmap"]))
    check([r["instance"] for r in map3["sources"]] == names and named["lvs"]["named"] == 5 and
          not named["lvs"]["unnamed"] and not named["lvs"]["conflicts"] and not named["lvs"]["notes"],
          f"{lvsdb}: instance names {[r['instance'] for r in map3['sources']]}, {named['lvs']}")
    check(map3["lvsdb"].endswith(lvsdb), f"{lvsdb}: the map records the LVS database")
print("lvs_name:", [r["lvs_name"] for r in map3["sources"]])
cfg3 = json.load(open(named["tsimcfg"]))
check([t["power"] for t in cfg3["thermal"] if t["type"] == "source"] == [0.002, 0.003, 0.004, 0.005, 0.006],
      "export with LVS names: powers kept")
again = export_thermal(ly, cell, st, gds, technology)
check([r["instance"] for r in json.load(open(again["thermalmap"]))["sources"]] == names,
      "export again without the LVS database: its names kept")
try:
    export_thermal(ly, cell, st, gds, technology, lvsdb=os.path.join(lvs_dir, "cascode_extracted.cir"))
    check(False, "an unreadable LVS database is refused")
except ValueError as e:
    check(True, f"an unreadable LVS database is refused: {e}")

# the guide's EM region: the bias resistor and the transistors inside, the outline is the box
box = pya.DBox(-28.9, -11.275, 21.595, 20.63)
boxed = export_thermal(ly, cell, st, os.path.join(OUT, "cascode_thermal_region.gds"), technology, box=box)
out_box, _ = shapes(boxed["gds"])
check(out_box[(201, 0)].bbox() == box.to_itype(dbu), "region export: outline = region box")
print("region export:", boxed["sources"], "source(s), cut by the region:", boxed["cut"])

# a PDK before the heat shapes (March 2025 and older) draws none: the PDK's rule gives the same rectangles from the
# device's own layers (npn emitter windows + 0.05 um, resistor bodies on PolyRes)
with_shapes = heat_sources(ly, cell, st, technology)
check(all(s.how == "shapes" for s in with_shapes), "with the PDK's heat shapes: how = shapes")
for layer in technology.HEAT_LAYERS:
    li = ly.find_layer(*layer)
    for c in ly.each_cell():
        c.shapes(li).clear()
without = heat_sources(ly, cell, st, technology)
check([s.how for s in without] == ["rule"] * 5, f"without them: from the rule ({[s.how for s in without]})")
check(all((a.area ^ b.area).is_empty() for a, b in zip(with_shapes, without)),
      "the rule gives exactly the PDK's heat shapes: " +
      ", ".join(f"{b.device.pcell} {b.area.area() * dbu ** 2:.4g} um2" for b in without))
ruled = export_thermal(ly, cell, st, os.path.join(OUT, "cascode_thermal_rule.gds"), technology)
rows_rule = json.load(open(ruled["thermalmap"]))["sources"]
check(ruled["from_rule"] == [s.device.id for s in without] and not ruled["bounding_box"] and
      all(r["heat_area_from"] == "rule" and r["from_pdk"] for r in rows_rule), "the map and the result say so")

# MOSFETs (none in the cascode): the rule equals the pcell's HeatTrans (gate fingers with end caps); the rf MOSFETs
# draw none in any PDK version, so no rule: bounding box
lib = pya.Library.library_by_name("SG13_dev", "sg13g2")
mos_layout = pya.Layout()
mos_layout.technology_name = "sg13g2"
for pcell, params in (("nmos", {"ng": 2}), ("pmosHV", {"ng": 3}), ("rfnmos", {})):
    ci = mos_layout.add_pcell_variant(lib, lib.layout().pcell_declaration(pcell).id(), params)
    device = type("Device", (), {"pcell": pcell, "cell_index": ci, "trans": pya.Trans(),
                                 "bbox": mos_layout.cell(ci).bbox()})
    li = mos_layout.find_layer(51, 0)
    # merged(): a copy, the Region reads the layout lazily
    pdk_heat = pya.Region(mos_layout.cell(ci).begin_shapes_rec(li)).merged() if li is not None else pya.Region()
    if li is not None:
        mos_layout.cell(ci).shapes(li).clear()
    area, how = technology.heat_area(mos_layout, device)
    if pcell == "rfnmos":
        check(pdk_heat.is_empty() and how == "bbox", "rfnmos: no PDK heat shapes, no rule: bounding box")
    else:
        check(how == "rule" and (area ^ pdk_heat).is_empty() and not area.is_empty(),
              f"{pcell}: the rule gives the PDK's HeatTrans ({pdk_heat.count()} fingers)")
print("all passed" if not failed else f"FAILED: {'; '.join(failed)}")
