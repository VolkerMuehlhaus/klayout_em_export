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

print("FAIL: " + "; ".join(failures) if failures else "all passed")
