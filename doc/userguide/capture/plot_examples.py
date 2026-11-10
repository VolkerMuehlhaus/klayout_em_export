# S-parameter figure for examples/README.md (split region example): the joined result against the full model, with
# plot_snp (pip package plot_snp, needs scikit-rf and matplotlib).
#   python doc/userguide/capture/plot_examples.py
import os

import matplotlib
matplotlib.use("Agg")
from plot_snp import parse_parameter, plot_all, read_network  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.normpath(os.path.join(HERE, "..", "..", "..", "examples", "split_region"))
networks = []
for name, label in (("two_inductors_full", "full model"), ("two_inductors_joined", "joined (p1 + p2)")):
    network = read_network(os.path.join(EXAMPLE, "reference", name + ".s2p"))
    network.name = label
    networks.append(network)
figure = plot_all(networks, [parse_parameter("S11"), parse_parameter("S21")])[0]
figure.suptitle("Two inductors in series: joined result and full model")
path = os.path.join(EXAMPLE, "images", "joined_vs_full_sparameters.png")
figure.savefig(path, dpi=110)
print("wrote", path)
