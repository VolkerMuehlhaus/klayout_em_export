# Batch test (KLayout -z -nc -rx -r): which technology a layout gets (tech.for_layout), the generic fallback, the
# IHP SG13CMOS5L stackup with the IHP technology, and the circuit wrapper with the port map's technology. Needs the
# PDK (tests/pdk_env.py); run with KLAYOUT_PATH/KLAYOUT_HOME pointing to an empty folder.
import importlib.util
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import GDS2PALACE, STACKUP, TESTS_DIR, layout_file

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
                                        ("mycell_CDNS_1234", "", "generic"), (None, "gf180mcu", "generic"),
                                        ("npn13G2$1", "", "ihp_sg13"), ("mycell$1", "", "generic")):
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

# ---- static device cells: <device>_CDNS_<n> (Cadence) and <device>$<n> (a pcell saved without pcell context, as a
# fill tool writes it): parameters from the labels; a static npn without its Ae= label is not replaced
from klayout_em_export.tech import ihp_sg13
ly = layout_with()
for name, label, expected in (("npn13G2$1", "Ae=10*1*0.07*0.90", ("npn13G2", {"Nx": 10, "Ny": 1, "we": "0.07u",
                                                                               "le": "0.90u"})),
                              ("npn13G2$2", None, ("npn13G2", {})),
                              ("rppd_CDNS_1", "rppd r=2.4k", ("rppd", {"label": "rppd r=2.4k"})),
                              ("rppd$3", "rppd r=999.847", ("rppd", {"label": "rppd r=999.847"})),
                              ("mycell$1", "Ae=1*1*0.07*0.90", (None, {}))):
    c = ly.create_cell(name)
    if label:
        c.shapes(ly.layer(*ihp_sg13.TEXT_LAYER)).insert(pya.Text(label, 0, 0))
    got = ihp_sg13.identify(c, ihp_sg13.context(ly, st))[:2]
    check(got == expected, f"static cell {name} labelled {label!r}: {got}")
top = ly.top_cells()[0]
top.insert(pya.CellInstArray(ly.cell_by_name("npn13G2$2"), pya.Trans()))
problems = [d.problems for d in find_devices(ly, top, st, ihp_sg13)[0] if d.id.startswith("npn13G2$2")]
check(problems and any(p.startswith("no parameters") for p in problems[0]),
      f"static npn without Ae= label is not replaced: {problems}")

# a static nmos without a label (as in lo_core): w, l, ng from its gates, GatPoly over Activ; a static rhigh whose
# two Metal1 pins are drawn twice (identical shapes) has two pins, not four
um = lambda v: round(v / ly.dbu)
mos = ly.create_cell("nmos$7")
mos.shapes(ly.layer(*ihp_sg13.ACTIV_LAYER)).insert(pya.Box(0, 0, um(6.42), um(2)))
for k in range(12):
    x = 0.34 + 0.51 * k
    mos.shapes(ly.layer(ihp_sg13.POLY_LAYER, 0)).insert(pya.Box(um(x), um(-0.18), um(x + 0.13), um(2.18)))
got = ihp_sg13.identify(mos, ihp_sg13.context(ly, st))[:2]
check(got == ("nmos", {"w": "24u", "l": "0.13u", "ng": 12, "from_gates": True}), f"static nmos from its gates: {got}")
check(ihp_sg13.describe(type("D", (), {"params": got[1]})()).endswith("(from the drawn gates)"),
      "the Value column says where the size comes from")
# the same rule on the PDK's own MOSFET pcells made static: w (total width), l, ng read back, also for a narrow
# long-channel device (W < L) and rotated by 90 degrees; a width off the 5 nm grid comes back as drawn (w=10u, ng=3:
# fingers of 3.33 um, 9.99u)
lib = pya.Library.library_by_name("SG13_dev", "sg13g2")
for name, w, l, ng, expected_w in (("nmos", "2u", "0.13u", 2, 2.0), ("pmos", "5u", "0.5u", 4, 5.0),
                                   ("nmosHV", "0.15u", "0.45u", 1, 0.15), ("pmos", "0.3u", "2u", 2, 0.3),
                                   ("nmos", "10u", "1u", 3, 9.99)):
    decl = lib.layout().pcell_declaration(name)
    values = {d.name: d.default for d in decl.get_parameters()}
    values.update(w=w, l=l, ng=str(ng))
    static = ly.cell(ly.convert_cell_to_static(ly.add_pcell_variant(lib, decl.id(), values)))
    rotated = ly.create_cell(f"{name}$rot")
    rotated.copy_shapes(static)
    rotated.transform(pya.Trans(pya.Trans.R90))
    got, got_rotated = ihp_sg13._mos_size_from_gates(static), ihp_sg13._mos_size_from_gates(rotated)
    check(got == got_rotated and got.get("ng") == ng and abs(float(got["w"][:-1]) - expected_w) < 1e-6
          and got["l"] == l, f"pcell {name} w={w} l={l} ng={ng} made static: {got}")
res = ly.create_cell("rhigh$5")
res.shapes(ly.layer(*ihp_sg13.TEXT_LAYER)).insert(pya.Text("rhigh r=19993.333", 0, 0))
for _ in range(2):
    for y in (-0.41, 14.15):
        res.shapes(ly.layer(8, ihp_sg13.PIN_DATATYPE)).insert(pya.Box(um(0.02), um(y), um(0.98), um(y + 0.26)))
top.insert(pya.CellInstArray(res.cell_index(), pya.Trans(pya.Point(um(100), 0))))
found = [d for d in find_devices(ly, top, st, ihp_sg13)[0] if d.id.startswith("rhigh$5")]
check(found and not found[0].problems and set(found[0].terminals) == {"PLUS", "MINUS"},
      f"rhigh with its pins drawn twice: {found[0].problems if found else 'not found'}")
ly = pya.Layout()
ly.technology_name = "sg13g2"       # the PDK library binds its pcells to this technology
ly.read(layout_file("1_St_Core_v1.gds"))
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
