# Batch test (KLayout -z -nc -rx -r): what the EM panel does on a layout opened for other work. A layout without EM
# setup (no region box, no ports in its cell, no ground marks) whose stackup is only the last one used is not
# checked until asked (Run Checks, or choosing its stackup); a closed panel (EM switched off) does nothing at all.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, layout_file

import pya
from klayout_em_export import gui
from klayout_em_export.gui import META_STACKUP
from klayout_em_export.panel import EMPanel, IDLE_TEXT

failures = []


def check(ok, text):
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failures.append(text)


_load_settings = gui._load_settings
last_used = {"stackup": STACKUP}           # the stackup chosen for another layout
gui._load_settings = lambda: dict(_load_settings(), panel_mode="em", **last_used)
state = {}
EMPanel._view = lambda self: (state["view"], state["view"].active_cellview())


def open_layout(name, prefix=""):
    view = pya.LayoutView(True)
    idx = view.load_layout(layout_file(name), True)
    cv = view.cellview(idx)
    cell = next((c for c in cv.layout().top_cells() if c.name.startswith(prefix)), cv.cell)
    cv.cell = cell
    state["view"] = view
    return cv


def text(step):
    return step.summary.text


# cascode: devices, no ports in the top cell, no region box
cv = open_layout("cascode.gds", "Cascode")
panel = EMPanel()
check(gui.stackup_source(cv.layout())[1] == gui.STACKUP_LAST, "stackup: only the last one used")
check(panel.idle and text(panel.ground_step).endswith(IDLE_TEXT) and panel.result is None,
      f"no EM setup: ground not checked ({text(panel.ground_step)!r})")
check(panel.devices_table.rowCount == 0 and "not checked" in text(panel.devices_step),
      f"no EM setup: devices not searched ({text(panel.devices_step)!r})")

panel.refresh(run_checks=True)
check(not panel.idle and panel.devices_table.rowCount == 3, f"Run Checks: 3 devices ({text(panel.devices_step)!r})")

# chosen for this layout: checked on every refresh
cv.layout().add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))
panel.refresh()
check(not panel.idle and panel.devices_table.rowCount == 3, "stackup chosen for the layout: checked")

# a layout with ports in its cell and a region box: checked with the last used stackup too
cv = open_layout("BM_Ardavan_Rahimian_with_ports_partial.gds")
panel.refresh()
check(not panel.idle and panel.result is not None, f"ports and region box: checked ({text(panel.ground_step)!r})")

# no stackup at all: nothing to check, as before (not 'not checked')
last_used.clear()
cv = open_layout("cascode.gds", "Cascode")
panel.refresh()
check(not panel.idle and "stackup" in text(panel.ground_step), f"no stackup: {text(panel.ground_step)!r}")
last_used["stackup"] = STACKUP

# EM switched off (panel closed): refresh and the selection-following region line do nothing
before = text(panel.ground_step)
panel.is_open = lambda: False
cv = open_layout("BM_Ardavan_Rahimian_with_ports_partial.gds")
panel.refresh(run_checks=True)
panel._update_region()
check(text(panel.ground_step) == before, "panel closed: no refresh")
panel.is_open = lambda: True
panel.refresh()
check(panel.result is not None, "panel opened again: checked")

# an exported EM model (1_St_Core_v1_em.gds, the GDS file of 1_St_Core_v1_em.simcfg, relative paths): the export
# removed the replaced devices and kept their tagged ports. Not "no longer there", and no Undo Replace, which would
# delete the device ports. Found from another working directory too (relative to the .simcfg, as setupEM reads it).
import tempfile
os.chdir(tempfile.gettempdir())
files = {}
gui._layout_file = lambda layout: files.get(id(layout), "")
cv = open_layout("1_St_Core_v1_em.gds")
files[id(cv.layout())] = layout_file("1_St_Core_v1_em.gds")
check(gui.exported_model(cv.layout()) == "1_St_Core_v1_em.simcfg", "the export's .simcfg found from another folder")
panel.refresh()
check(panel.exported == "1_St_Core_v1_em.simcfg" and text(panel.devices_step).startswith("exported EM model: 5 device"),
      f"exported model: {text(panel.devices_step)!r}")
check("no longer there" not in panel.devices_detail.text, "exported model: no 'no longer there'")
check(not panel.replace_button.isEnabled() and not panel.unreplace_button.isEnabled(),
      "exported model: Replace All and Undo Replace off")
tagged = sum(1 for li in cv.layout().layer_indexes() for s in cv.cell.shapes(li).each() if s.property(202))
panel._unreplace_devices()
after = sum(1 for li in cv.layout().layer_indexes() for s in cv.cell.shapes(li).each() if s.property(202))
check(tagged > 0 and after == tagged, f"exported model: Undo Replace does nothing ({tagged} tagged shapes kept)")

# a design with devices whose replaced ports partly lost their device: still reported, buttons on
cv = open_layout("1_St_Core_v1_forEM.gds", "Cascode")
files[id(cv.layout())] = layout_file("1_St_Core_v1_forEM.gds")
cv.layout().add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))
panel.refresh()
check(panel.exported is None and "no longer there" in text(panel.devices_step) and panel.unreplace_button.isEnabled(),
      f"design with moved devices: {text(panel.devices_step)!r}")

print("FAIL: " + "; ".join(failures) if failures else "all passed")
