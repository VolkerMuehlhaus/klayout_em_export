# Batch test (KLayout -z -nc -rx -r, package installed in salt): values stored for a layout survive closing it
# without saving (no meta info in the file) through the settings file. Uses its own settings file; the layout's
# file name, found through the main window in the GUI, is given by a stand-in.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import tests_data, out_dir

import pya
from klayout_em_export import gui

OUT = out_dir("kee")
GDS = tests_data("testcases", "50_ghz_mpa_core.gds")
gui.SETTINGS_FILE = os.path.join(OUT, "settings_test.json")
if os.path.exists(gui.SETTINGS_FILE):
    os.remove(gui.SETTINGS_FILE)
files = {}
gui._layout_file = lambda layout: files.get(id(layout), "")

first = pya.Layout(); first.read(GDS); files[id(first)] = GDS
gui.set_layout_value(first, gui.META_OUTPUT, os.path.join(OUT, "..", "e2e", "e2e_em.gds"), "test")   # has a .simcfg
gui._set_ground_seeds(first, [(8, pya.Point(1000, 2000))])
print("session 1: output", gui.layout_value(first, gui.META_OUTPUT), "| ground", [(l, str(p)) for l, p in gui.ground_seeds(first)])

second = pya.Layout(); second.read(GDS); files[id(second)] = GDS     # reopened, not saved: no meta info
print("meta info in the reopened file:", second.meta_info_value(gui.META_OUTPUT))
print("session 2: output", gui.layout_value(second, gui.META_OUTPUT), "| ground", [(l, str(p)) for l, p in gui.ground_seeds(second)],
      "| last .simcfg", gui.last_simcfg(second))
