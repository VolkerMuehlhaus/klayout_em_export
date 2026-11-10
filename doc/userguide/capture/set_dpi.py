# Give the GUI screenshots (panels, dialogs, menus) a resolution entry of at least 200 dpi, and enough to keep them at
# most 5.5 inches wide, so the PDF shows them at a natural size instead of the full page width. Layout images and full windows keep theirs. GitHub ignores the value.
# Optional argument: the image folder (default doc/userguide/images).
import glob
import os
import sys

from PIL import Image

IMAGES = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images")
SMALL = ("04_em_menu", "05_panel", "07_port_dialog", "07_panel", "07_port_overview", "08_panel", "09_panel",
         "10_panel", "11_export_dialog", "13_circuit_dialog", "13_simulator_choice", "13_circuit_done")
for path in sorted(glob.glob(os.path.join(IMAGES, "*.png"))):
    name = os.path.basename(path)
    if name.startswith(SMALL):
        image = Image.open(path)
        image.load()
        dpi = max(200, round(image.width / 5.5))
        image.save(path, dpi=(dpi, dpi))
        print(f"{dpi} dpi:", name)
