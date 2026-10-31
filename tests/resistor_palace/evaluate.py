# R of each resistor from Palace's port-S.csv at the lowest frequency: R = -1/Y12 of its port pair, compared with
# the PDK value (cell label) and the sheet estimate.
import json
import sys

import numpy as np

rows = [l for l in open(sys.argv[1]) if l.strip()]
head = [h.strip() for h in rows[0].split(",")]
data = np.array([[float(v) for v in r.split(",")] for r in rows[1:]])
f = data[0, 0]
n = int(round(np.sqrt((len(head) - 1) / 2)))
S = np.zeros((n, n), complex)
for c, h in enumerate(head[1:], start=1):
    if h.startswith("|S["):
        i, j = int(h[3:h.index("]")]) - 1, int(h.split("[")[2].split("]")[0]) - 1
        mag = 10 ** (data[0, c] / 20)
        S[i, j] = mag * np.exp(1j * np.radians(data[0, c + 1]))
z0 = 50.0
Y = np.linalg.solve(np.eye(n) + S, np.eye(n) - S) / z0      # Y = (I + S)^-1 (I - S) / Z0
info = json.load(open(sys.argv[2]))
print(f"f = {f} GHz")
print(f"{'cell':26s} {'PDK (label)':>12s} {'Palace':>10s} {'diff':>7s}")
for r in info:
    a, b = r["ports"][0] - 1, r["ports"][1] - 1
    R = (-1 / Y[a, b]).real
    pdk = float(r["label"].split("r=")[1].replace("k", "")) * (1e3 if r["label"].endswith("k") else 1)
    print(f"{r['cell']:26s} {pdk:12.2f} {R:10.2f} {100 * (R / pdk - 1):+6.1f}%")
