# Figures of the user's guide that are not screenshots: the workflow overview, plus copies of figures from the
# cascode test reports. Run in a Python with matplotlib and Pillow.
import os
import shutil

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "images")
DOC = os.path.join(HERE, "..", "..")
INK, MUTED, ACCENT, PLAIN = "#1f1f1e", "#6b6a64", "#2a78d6", "#f3f2ee"

# ---------- workflow overview ----------
steps = [("Your layout", "in KLayout, with the\nIHP SG13G2 PDK", PLAIN),
         ("EM plug-in", "stackup, region, ports,\ntransistors → ports,\nexport", "#dbe8f8"),
         ("setupEM + Palace", "EM simulation:\nS-parameters of the\ninterconnect", PLAIN),
         ("Create Circuit", "EM model + PDK\ntransistor models\nput back", "#dbe8f8"),
         ("Circuit simulator", "ngspice, VACASK,\nXyce or Spectre:\nbias, gain, ...", PLAIN)]
fig, ax = plt.subplots(figsize=(11, 2.6))
ax.set_xlim(0, 10.25)
ax.set_ylim(0, 2.6)
ax.axis("off")
w, gap = 1.75, 0.3
for i, (title, text, color) in enumerate(steps):
    x = 0.1 + i * (w + gap)
    ax.add_patch(FancyBboxPatch((x, 0.35), w, 1.8, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=color, ec=ACCENT if color != PLAIN else MUTED, lw=1.5))
    ax.text(x + w / 2, 1.82, title, ha="center", va="center", fontsize=11.5, fontweight="bold", color=INK)
    ax.text(x + w / 2, 1.0, text, ha="center", va="center", fontsize=9.5, color=INK)
    if i < len(steps) - 1:
        ax.add_patch(FancyArrowPatch((x + w + 0.02, 1.25), (x + w + gap - 0.02, 1.25), arrowstyle="-|>",
                                     mutation_scale=14, color=MUTED, lw=1.5))
ax.text(0.1 + 1 * (w + gap) + w / 2, 0.12, "this guide", ha="center", fontsize=9, color=ACCENT)
ax.text(0.1 + 3 * (w + gap) + w / 2, 0.12, "this guide", ha="center", fontsize=9, color=ACCENT)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "01_flow.png"), dpi=150)

# ---------- figures from the test reports ----------
copies = {"test_cascode_wrapper/fig_full_schematic.png": "13_full_circuit.png",
          "test_cascode_wrapper/fig_device_wiring.png": "13_device_wiring.png",
          "test_cascode_wrapper/fig_amplifier.png": "14_amplifier.png",
          "test_cascode_wrapper/fig_lookalike_vs_em.png": "14_fit.png",
          "test_cascode_wrapper/fig_circuit.png": "03_circuit.png",
          "test_cascode_wrapper/fig_layout.png": "14_layout_ports.png"}
for source, target in copies.items():
    shutil.copyfile(os.path.join(DOC, source), os.path.join(OUT, target))
# the REF patch: where the transistor's ports end (sketch, not to scale in x)
from matplotlib.patches import Rectangle
fig, ax = plt.subplots(figsize=(7.5, 3.8))
for y0, h, color, label in ((0, 2.0, "#d7e2f5", "substrate"), (2.0, 1.75, "#b9cdf0", "EPI"),
                            (3.75, 1.9, "#fbf7dc", "oxide (SiO2)")):
    ax.add_patch(Rectangle((0, y0), 10, h, color=color))
    ax.text(9.8, y0 + h / 2, label, ha="right", va="center", fontsize=9, color=MUTED)
for x, w in ((2.0, 1.2), (4.4, 1.2), (6.8, 1.2)):           # three pins on Metal1: B, C, E
    ax.add_patch(Rectangle((x, 4.79), w, 0.42, color="#7fb3e6"))
    ax.plot([x + w / 2, x + w / 2], [4.15, 4.79], color="#eb6834", lw=2.5)
for x, name in ((2.6, "B"), (5.0, "C"), (7.4, "E")):
    ax.text(x, 5.35, name, ha="center", fontsize=10, fontweight="bold", color=INK)
ax.plot([1.6, 8.4], [4.15, 4.15], color=INK, lw=3)
ax.text(8.55, 4.15, "REF patch", va="center", fontsize=9.5, color=INK)
ax.text(5.0, 6.05, "transistor pins (Metal1)", ha="center", fontsize=9.5, color=INK)
ax.text(3.8, 4.47, "ports", ha="center", fontsize=9, color="#eb6834")
ax.text(5.0, 1.0, "the transistor itself is removed: its pins end in ports\n"
        "to one small sheet, the REF patch, under the device", ha="center", va="center", fontsize=9.5, color=INK)
ax.set_xlim(0, 10)
ax.set_ylim(0, 6.6)
ax.axis("off")
fig.tight_layout()
fig.savefig(os.path.join(OUT, "10_ref_patch.png"), dpi=150)
print("ok")
