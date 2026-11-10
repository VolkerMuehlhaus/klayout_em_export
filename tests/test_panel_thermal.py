# Batch test (KLayout -z -nc -rx -r): the EM panel's Thermal mode on the user's cascode 1_St_Core_v1_forEM.gds.
# The mode switch shows the heat sources of the region (one per device, the layers of the export), their schematic
# names from the LVS database (tests/data/lvs_cascode, see test_thermal.py) or else from the last export, and the
# boundaries of the last export's .tsimcfg (the export's placeholder: no target layer yet). EM steps are hidden.
# Needs the PDK, run like test_devices.py. The settings file is not touched (in memory here).
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import DATA_DIR, STACKUP, TESTS_DIR, out_dir, layout_file

import pya
sys.path.insert(0, TESTS_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))   # not via salt here
from pdk_env import load_pdk
from klayout_em_export import gui, tech
from klayout_em_export.gui import META_LVSDB, META_STACKUP, META_THERMAL_OUTPUT
from klayout_em_export.panel import EMPanel
from klayout_em_export.stackup import Stackup
from klayout_em_export.thermal import export_thermal

OUT = out_dir("panel_thermal")
LVSDB = os.path.join(DATA_DIR, "lvs_cascode", "cascode.lvsdb")
failed = []


def check(ok, text):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)


def ascii(text):   # the Windows console of KLayout's Python cannot print the check marks and arrows
    for symbol, word in (("✓", "OK"), ("⚠", "WARN"), ("✗", "ERR"), ("→", "->"), ("µ", "u")):
        text = text.replace(symbol, word)
    return text


def mark(step):
    return ascii(step.mark.text.split(">")[1][0])


def column(table, col):
    return [table.item(r, col).text for r in range(table.rowCount)]


settings = {}
gui._load_settings = lambda: dict(settings)
gui._save_settings = lambda s: settings.update(s)
gui.backup_original = lambda layout: None

load_pdk()
view = pya.LayoutView(True)
idx = view.load_layout(layout_file("1_St_Core_v1_forEM.gds"), "sg13g2", True)
cv = view.cellview(idx)
ly = cv.layout()
cell = next(c for c in ly.top_cells() if c.name.startswith("Cascode"))
cv.cell = cell
ly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))
EMPanel._view = lambda self: (view, view.active_cellview())

panel = EMPanel()
check(not panel._thermal() and not panel.ground_step.isHidden() and panel.sources_step.isHidden(),
      "starts in EM mode: EM steps shown, thermal steps hidden")

panel.mode_bar.setCurrentIndex(1)
check(settings.get("panel_mode") == "thermal", "the mode is remembered")
check(all(w.isHidden() for w in (panel.ground_step, panel.devices_step, panel.ports_step, panel.table,
                                   panel.tool_row, panel.em_buttons)) and
      not any(w.isHidden() for w in (panel.sources_step, panel.names_step, panel.boundary_step, panel.sources_table,
                                     panel.thermal_buttons)),
      "Thermal: EM steps, port table and EM buttons hidden; heat sources, names, boundary shown")
print("  Sources :", mark(panel.sources_step), ascii(panel.sources_step.summary.text))
print("  Names   :", mark(panel.names_step), ascii(panel.names_step.summary.text))
print("  Boundary:", mark(panel.boundary_step), ascii(panel.boundary_step.summary.text))
# the stackup's heat target layers per device kind (gds2palace 0.10.0); Activ in a stackup without them
check(panel.sources_step.summary.text in ("5 heat source(s) in HEAT_RESISTOR, HEAT_TRANSISTOR",
                                          "5 heat source(s) in Activ"), "five heat sources in their target layers")
check(column(panel.sources_table, 0) == ["202", "203", "204", "205", "206"], "the layers of the export")
check(column(panel.sources_table, 4) == ["PDK heat shapes"] * 5, "every heat area from the PDK's shapes")
check(not panel.open_thermal_button.isEnabled(), "Open in setupThermal: disabled before the first thermal export")
check("placeholder" in panel.boundary_step.summary.text and "layer 201" in panel.boundary_step.summary.text,
      "Boundary before an export: the outline layer will get a placeholder")

ly.add_meta_info(pya.LayoutMetaInfo(META_LVSDB, LVSDB, "", True))
panel.refresh()
check(column(panel.sources_table, 2) == ["R1", "R2", "R3", "Q1", "Q2"], "instance names from the LVS database")
check(mark(panel.names_step) == "OK" and panel.names_step.summary.text == "5 of 5 from cascode.lvsdb",
      f"Names: {ascii(panel.names_step.summary.text)}")

gds = os.path.join(OUT, "cascode_thermal.gds")
for suffix in (".tsimcfg", "_thermalmap.json"):
    if os.path.exists(gds[:-4] + suffix):
        os.remove(gds[:-4] + suffix)
technology = tech.for_layout(ly)[0]
export_thermal(ly, cell, Stackup(STACKUP), gds, technology, lvsdb=LVSDB)
ly.add_meta_info(pya.LayoutMetaInfo(META_THERMAL_OUTPUT, gds, "", True))
panel.refresh()
check(panel.open_thermal_button.isEnabled(), "Open in setupThermal: enabled after the export")
check(mark(panel.boundary_step) == "WARN" and "layer 201 (region outline)" in panel.boundary_step.summary.text and
      "no target layer yet" in panel.boundary_step.summary.text,
      f"Boundary: the placeholder ({ascii(panel.boundary_step.summary.text)})")

tsimcfg = gds[:-4] + ".tsimcfg"
cfg = json.load(open(tsimcfg))
cfg["thermal"][-1]["target_layername"] = "BACKSIDEGND"
json.dump(cfg, open(tsimcfg, "w"))
panel.refresh()
check(mark(panel.boundary_step) == "OK" and
      ascii(panel.boundary_step.summary.text) == "layer 201 (region outline) -> BACKSIDEGND, 300 K",
      f"Boundary: chosen in setupThermal ({ascii(panel.boundary_step.summary.text)})")

ly.add_meta_info(pya.LayoutMetaInfo(META_LVSDB, "", "", True))
panel.refresh()
check(column(panel.sources_table, 2) == ["R1", "R2", "R3", "Q1", "Q2"] and
      panel.names_step.summary.text == "5 of 5 from the last export (no LVS database)",
      "without the LVS database: the names of the last export")

ly.add_meta_info(pya.LayoutMetaInfo(META_LVSDB, os.path.join(OUT, "gone.lvsdb"), "", True))
panel.refresh()
check(mark(panel.names_step) == "ERR" and column(panel.sources_table, 2) == [""] * 5,
      "a missing LVS database is an error, no names")

region = pya.DBox(cell.dbbox().left, cell.dbbox().bottom, cell.dbbox().center().x, cell.dbbox().top)
mark_layer = ly.layer(*gui.EM_REGION)
cell.shapes(mark_layer).insert(region)
panel.refresh()
print("  half region:", ascii(panel.sources_step.summary.text))
check(panel.sources_table.rowCount < 5 or "cut by the region" in column(panel.sources_table, 4)[0] + "".join(
    column(panel.sources_table, 4)),
      "the EM region box limits the heat sources")
cell.shapes(mark_layer).clear()

panel.mode_bar.setCurrentIndex(0)
check(settings.get("panel_mode") == "em" and not panel.ground_step.isHidden() and panel.sources_step.isHidden() and
      not panel.em_buttons.isHidden() and panel.thermal_buttons.isHidden(), "back to EM")

# where the stackup comes from: chosen for the layout, else the layout's own setupThermal file, else the last used
other = os.path.join(OUT, "other_stackup.xml")
with open(STACKUP, encoding="utf-8") as src, open(other, "w", encoding="utf-8") as dst:
    dst.write(src.read())
fresh = pya.Layout()
layout_file = os.path.join(OUT, "fresh_layout.gds")
own_cfg = os.path.join(OUT, "fresh_layout.tsimcfg")
for stale in (own_cfg,):
    if os.path.exists(stale):
        os.remove(stale)
settings["stackup"] = STACKUP
check(gui.stackup_source(fresh, "thermal", layout_file) == (STACKUP, gui.STACKUP_LAST) and
      gui.stackup_label(fresh, "thermal", layout_file)[0] == gui.WARN,
      "no stackup chosen, no own setup file: the last used one, with a warning")
json.dump({"application": "setupThermal", "saved_values": {"GdsFile": layout_file, "SubstrateFile": other}},
          open(own_cfg, "w"))
check(gui.stackup_source(fresh, "thermal", layout_file) == (other, "fresh_layout.tsimcfg") and
      gui.stackup_label(fresh, "thermal", layout_file)[0] == gui.OK,
      "the layout's own setupThermal file gives its stackup")
fresh.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))
check(gui.stackup_source(fresh, "thermal", layout_file) == (STACKUP, gui.STACKUP_CHOSEN),
      "a stackup chosen for the layout wins")
settings.pop("stackup")
os.remove(own_cfg)
check(gui.stackup_source(pya.Layout(), "em", layout_file) == ("", ""), "nothing at all: none")

print("all passed" if not failed else f"{len(failed)} FAILED")
