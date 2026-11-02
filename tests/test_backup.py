# Batch test (KLayout -z -nc -rx -r): the backup of an original layout before the plug-in's first change
# (gui.backup_original, gui.has_em_data). In batch mode a layout has no view, so the test gives its file name.
# Output: OUT (default: a temp folder, see testpaths.py).
import filecmp
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import out_dir

import pya
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))   # not via salt here
from klayout_em_export import gui
from klayout_em_export.ports import PROP_KEY, PortSettings

OUT = out_dir("backup")
failed = []


def check(ok, text):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)


def original(name):
    """A plain layout written to OUT/name (any old .bak removed), read back; gui._layout_file gives its path."""
    path = os.path.join(OUT, name)
    for p in (path, path + gui.BACKUP_SUFFIX):
        if os.path.exists(p):
            os.remove(p)
    ly = pya.Layout()
    top = ly.create_cell("TOP")
    top.shapes(ly.layer(8, 0)).insert(pya.Box(0, 0, 1000, 1000))
    top.shapes(ly.layer(201, 0)).insert(pya.Box(0, 0, 0, 500))      # a plain port shape (gds2palace): no data of ours
    ly.write(path)
    back = pya.Layout()
    back.read(path)
    gui._layout_file = lambda layout, p=path: p
    return back, path


ly, path = original("plain.gds")
check(not gui.has_em_data(ly), "a plain layout (with a port shape without settings) holds no data of the plug-in")
backup = gui.backup_original(ly)
check(backup == path + ".bak" and filecmp.cmp(path, backup, shallow=False), f"first change: backup {backup}")
check(gui.backup_original(ly) is None, "second change in the session: no new backup")

# an existing .bak is never replaced: it keeps the oldest original
gui._backup_checked.clear()
with open(backup, "ab") as f:
    f.write(b"older")
size = os.path.getsize(backup)
check(gui.backup_original(ly) is None and os.path.getsize(backup) == size, "an existing .bak stays as it is")

# a layout with the plug-in's data is no original: no backup
for name, change in (("meta.gds", lambda l: l.add_meta_info(pya.LayoutMetaInfo(gui.META_STACKUP, "x.xml", "", True))),
                     ("port.gds", lambda l: l.top_cell().shapes(l.layer(202, 0)).insert(
                         pya.Box(0, 0, 0, 500), l.properties_id([[PROP_KEY, PortSettings("Z", "Metal1", "Metal2")
                                                                  .encode()]]))),
                     ("ref.gds", lambda l: l.top_cell().shapes(l.layer(300, 0)).insert(
                         pya.Box(0, 0, 100, 100), l.properties_id([[202, "device:x@0,0"]]))),
                     ("region.gds", lambda l: l.top_cell().shapes(l.layer(*gui.EM_REGION)).insert(
                         pya.Box(0, 0, 100, 100)))):
    ly, path = original(name)
    change(ly)
    gui._backup_checked.clear()
    check(gui.has_em_data(ly) and gui.backup_original(ly) is None and not os.path.exists(path + ".bak"),
          f"{name}: the plug-in's data found, no backup")

print("all passed" if not failed else f"FAILED: {'; '.join(failed)}")
