# Batch test (KLayout -z -nc -rx -r): replace and undo selected devices only (the device table's right-click menu),
# on the cascode (2 transistors, 3 resistors). Needs the PDK (tests/pdk_env.py), run like test_devices.py.
# A chosen resistor is replaced whatever "include resistors" says; undo of one device leaves the others; Replace All
# still replaces the rest.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, TESTS_DIR, layout_file

import pya

sys.path.insert(0, TESTS_DIR)
from pdk_env import load_pdk
load_pdk()
from klayout_em_export import gui
from klayout_em_export.gui import META_STACKUP
from klayout_em_export.panel import EMPanel

failures = []


def check(ok, text):
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failures.append(text)


view = pya.LayoutView(True)
view.transaction = lambda text: None    # a standalone view crashes on undo steps in batch (pipeline.NoUndo)
view.commit = lambda: None
idx = view.load_layout(layout_file("cascode.gds"), "sg13g2", True)
ly = view.cellview(idx).layout()
ly.add_meta_info(pya.LayoutMetaInfo(META_STACKUP, STACKUP, "", True))
EMPanel._view = lambda self: (view, view.active_cellview())
gui.backup_original = lambda layout: None
panel = EMPanel()
panel.refresh()


def states():
    return {d.id: d.replaced for d in panel.device_rows}


rows = panel.device_rows
transistor = next(d for d in rows if not d.is_resistor)
resistor = next(d for d in rows if d.is_resistor)
check(len(rows) == 5 and not any(states().values()), f"cascode: {len(rows)} devices, none replaced")
panel.include_resistors.setChecked(False)
panel._replace_selected([transistor, resistor])
replaced = {i for i, r in states().items() if r}
check(replaced == {transistor.id, resistor.id},
      f"Replace Selected: only the two chosen, the resistor too although include resistors is off: {sorted(replaced)}")
panel._unreplace_selected([d for d in panel.device_rows if d.id == transistor.id])
replaced = {i for i, r in states().items() if r}
check(replaced == {resistor.id}, f"Undo Replace of one: the other stays replaced: {sorted(replaced)}")
check(sum(len(d.ports) for d in panel.device_rows if d.replaced) == 2, "the resistor keeps its two ports")
panel.include_resistors.setChecked(True)
panel._replace_devices()
check(all(states().values()), f"Replace All replaces the rest: {states()}")
print("FAIL: " + "; ".join(failures) if failures else "all passed")
