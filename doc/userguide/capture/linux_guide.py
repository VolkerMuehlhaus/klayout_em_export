# The Linux edition of the user's guide: the same text, with the screenshots from images_linux where they exist
# (figures that are not screenshots stay in images). The main guide is the only source; rerun this after editing it.
# Screenshots: capture.py and capture_setupem.py with SHOTS / output folder doc/userguide/images_linux, on Linux.
#   python doc/userguide/capture/linux_guide.py            # writes klayout_em_export_userguide_linux.md
#   python doc/userguide/capture/linux_guide.py --pdf      # also the PDF, with build_pdf.py
import os
import re
import sys

GUIDE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SOURCE = os.path.join(GUIDE, "klayout_em_export_userguide.md")
TARGET = os.path.join(GUIDE, "klayout_em_export_userguide_linux.md")
NOTE = ("Linux edition: the same text as the main guide, with screenshots taken on Ubuntu 26.04 (GNOME) with "
        "KLayout 0.30.5 and setupEM 0.16.0.")

text = open(SOURCE, encoding="utf-8").read()


def linux_image(match):
    name = match.group(1)
    return f"images_linux/{name}" if os.path.isfile(os.path.join(GUIDE, "images_linux", name)) else match.group(0)


text = re.sub(r"images/([\w.-]+\.png)", linux_image, text)
text = re.sub(r"^(# .*)$", r"\1 (Linux)", text, count=1, flags=re.M)
text = re.sub(r"^(Document version: .*)$", r"\1" + "\n\n" + NOTE, text, count=1, flags=re.M)
with open(TARGET, "w", encoding="utf-8", newline="\n") as f:
    f.write(text)
print(f"wrote {TARGET}: {text.count('images_linux/')} Linux screenshot(s)")

if "--pdf" in sys.argv:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from build_pdf import build_pdf
    build_pdf(TARGET)
