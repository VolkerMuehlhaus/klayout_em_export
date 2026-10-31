# Give the GUI screenshots (panels, dialogs, menus) a resolution of 200 dpi, so the PDF shows them at a natural size
# instead of the full page width. Layout images and full windows keep theirs. GitHub ignores the value.
import glob
import os

from PIL import Image

IMAGES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images")
SMALL = ("04_em_menu", "05_panel", "07_port_dialog", "07_panel", "07_port_overview", "08_panel", "09_panel",
         "10_panel", "11_export_dialog", "13_circuit_dialog", "13_simulator_choice", "13_circuit_done")
for path in sorted(glob.glob(os.path.join(IMAGES, "*.png"))):
    name = os.path.basename(path)
    if name.startswith(SMALL):
        image = Image.open(path)
        image.load()
        image.save(path, dpi=(200, 200))
        print("200 dpi:", name)
