# The PDF of the user's guide, with this repo's figure sizes: all figures except the workflow,
# the layout views and the first main window shot at PDF_SCALE of the width the shared builder would give them (their
# dpi, at most the text width). The widths go into a temporary copy of the Markdown only; the .md and the images stay
# as they are. Needs doc/pdf_build/requirements.txt (pandoc, typst, Pillow).
#   python doc/userguide/capture/build_pdf.py [guide.md]     # default: the main guide; the PDF next to it
import os
import re
import subprocess
import sys

from PIL import Image

GUIDE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
BUILDER = os.path.normpath(os.path.join(GUIDE, "..", "pdf_build", "build_userguide_pdf.py"))
FULL_SIZE = ("01_flow", "02_main_window_start", "03_layout", "07_pad_port_top", "08_ground_in_layout", "09_region_",
             "09_boundary_port", "10_q1_", "10_resistors_after", "14_layout_ports")
PDF_SCALE = 0.7
TEXT_WIDTH_IN = (210 - 2 * 22) / 25.4           # A4 minus the template's 22 mm side margins
JPEG_ABOVE = 150_000                            # the builder embeds larger opaque images as JPEG, without their dpi


def builder_width(path):
    """Fraction of the text width the builder gives the image without a width."""
    with Image.open(path) as im:
        opaque = im.convert("RGBA").getextrema()[3][0] == 255
        width_in = im.width / im.info.get("dpi", (72, 72))[0]
    if opaque and os.path.getsize(path) >= JPEG_ABOVE:
        return 1.0
    return min(width_in / TEXT_WIDTH_IN, 1.0)


def with_widths(text, folder):
    def sized(match):
        path = match.group(2)
        if os.path.basename(path).startswith(FULL_SIZE):
            return match.group(0)
        return f"{match.group(0)}{{width={round(100 * PDF_SCALE * builder_width(os.path.join(folder, path)))}%}}"
    return re.sub(r"(!\[[^\]]*\]\()([^)\s]+)\)", sized, text)


def build_pdf(md_path):
    folder, name = os.path.split(os.path.abspath(md_path))
    pdf = os.path.join(folder, os.path.splitext(name)[0] + ".pdf")
    tmp = os.path.join(folder, "_pdf_" + name)
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(with_widths(open(md_path, encoding="utf-8").read(), folder))
    try:
        subprocess.run([sys.executable, BUILDER, tmp, "-o", pdf, "--chapter-pagebreak"],
                       cwd=os.path.dirname(BUILDER), check=True)
    finally:
        os.remove(tmp)
    return pdf


if __name__ == "__main__":
    build_pdf(sys.argv[1] if len(sys.argv) > 1 else os.path.join(GUIDE, "klayout_em_export_userguide.md"))
