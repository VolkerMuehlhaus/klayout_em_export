# Batch test (KLayout -z -nc -rx -r): which technology a layout gets (tech.for_layout), the generic fallback, the
# IHP SG13CMOS5L stackup with the IHP technology, and the circuit wrapper with the port map's technology. Needs the
# PDK (klayout_em_export_tests/pdk_env.py); run with KLAYOUT_PATH/KLAYOUT_HOME pointing to an empty folder.
import importlib.util
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import GDS2PALACE, STACKUP, TESTS_DIR, palace_testcases

import pya
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(HERE, "..", "python"))   # not via salt here
from pdk_env import load_pdk
from klayout_em_export import tech
from klayout_em_export.connectivity import check_ground, wiring
from klayout_em_export.devices import find_devices
from klayout_em_export.stackup import Stackup

failed = []


def check(ok, text):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)


def layout_with(cell_name=None, technology=""):
    ly = pya.Layout()
    ly.technology_name = technology
    top = ly.create_cell("TOP")
    if cell_name:
        child = ly.create_cell(cell_name)
        top.insert(pya.CellInstArray(child.cell_index(), pya.Trans()))
    return ly


# ---- choosing the technology
for cell_name, technology, expected in ((None, "", "generic"), (None, "sg13g2", "ihp_sg13"),
                                        (None, "sg13cmos5l", "ihp_sg13"), ("rhigh_CDNS_1234", "", "ihp_sg13"),
                                        ("mycell_CDNS_1234", "", "generic"), (None, "gf180mcu", "generic")):
    module, reason = tech.for_layout(layout_with(cell_name, technology))
    check(module.NAME == expected, f"cell {cell_name}, KLayout technology '{technology}': {module.NAME} ({reason})")
module, reason = tech.for_layout(layout_with(None, "sg13g2"), override="generic")
check(module.NAME == "generic", f"override in the settings: {module.NAME} ({reason})")
try:
    tech.load("nonsense")
    check(False, "an unknown technology name is refused")
except ValueError as e:
    check(True, f"an unknown technology name is refused: {e}")
check(tech.device_level_names() == {"Activ"}, f"device level names: {tech.device_level_names()}")

# ---- the cascode: IHP devices found; with the generic technology none, and the ground check does not change
load_pdk()
st = Stackup(STACKUP)
ly = pya.Layout()
ly.technology_name = "sg13g2"       # the PDK library binds its pcells to this technology
ly.read(palace_testcases("klayout_export", "1_St_Core_v1.gds"))
cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))
module, reason = tech.for_layout(ly)
check(module.NAME == "ihp_sg13", f"cascode: {module.NAME} ({reason})")
ihp = find_devices(ly, cell, st)[0]
generic = find_devices(ly, cell, st, tech.load("generic"))[0]
check("npn13G2" in {d.pcell for d in ihp} and not generic,
      f"devices: IHP {sorted(d.pcell for d in ihp)}, generic {len(generic)}")

# ---- SG13CMOS5L stackup: same wiring below Metal2 as SG13G2, the devices found with the same terminals
cmos5l = Stackup(os.path.join(GDS2PALACE, "XML_stackup", "latest", "IHP", "SG13CMOS5L_200um.xml"))
metals, _ = wiring(cmos5l)
check("Activ" not in metals.values() and "Metal1" in metals.values(), f"SG13CMOS5L wiring: {sorted(metals.values())}")
c5 = find_devices(ly, cell, cmos5l)[0]
same = [(d.pcell, sorted(d.terminals)) for d in ihp] == [(d.pcell, sorted(d.terminals)) for d in c5]
check(same and not any(d.problems for d in c5), f"SG13CMOS5L stackup: {[(d.pcell, sorted(d.terminals)) for d in c5]}")
result = check_ground(ly, cell, cmos5l)
check(result is not None, f"ground check with the SG13CMOS5L stackup runs: {result.pieces} piece(s)")

# ---- circuit wrapper: the device models of the port map's technology
spec = importlib.util.spec_from_file_location("spice_wrapper", os.path.join(HERE, "..", "tools", "spice_wrapper.py"))
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)
ports = [{"port": 1, "in_simcfg": True, "layout_port": 1, "settings": None},
         {"port": 2, "in_simcfg": True, "layout_port": 2, "settings": None, "device": "rsil@0,0", "terminal": "PLUS"},
         {"port": 3, "in_simcfg": True, "layout_port": 3, "settings": None, "device": "rsil@0,0", "terminal": "MINUS"}]
devices = {"rsil@0,0": {"pcell": "rsil", "params": {"w": "0.5u", "l": "2u", "b": "0"}}}
for technology, model_line in ((None, "rsil"), ("ihp_sg13", "rsil"), ("generic", None)):
    pm = {"ports": ports, "devices": devices}
    if technology:
        pm["technology"] = technology
    c = wrapper.build(pm, 3, False, "t")
    text = wrapper.write_vacask(c, "t_le.inc", "t_le", [])
    has_device = any(item[0] == "device" for item in c.items)
    ok = has_device == (model_line is not None) and (("sg13g2_vacask_common" in text) == (c.tech.NAME == "ihp_sg13"))
    check(ok, f"wrapper, port map technology {technology}: {c.tech.NAME}, device instantiated {has_device}, "
              f"notes {c.notes}")
try:
    wrapper.build({"ports": ports[:1], "technology": "nonsense"}, 1, False, "t")
    check(False, "wrapper: an unknown technology stops it")
except SystemExit as e:
    check("unknown technology" in str(e), f"wrapper: an unknown technology stops it: {e}")

print("all passed" if not failed else f"{len(failed)} failed")
