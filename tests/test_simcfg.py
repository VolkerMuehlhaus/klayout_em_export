# Test (plain Python or KLayout batch): re-exporting keeps setupEM's own settings in an existing .simcfg.
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from klayout_em_export.simcfg import port_entry, write_simcfg

out = sys.argv[1] if len(sys.argv) > 1 else os.environ["OUT"]
path, gds = os.path.join(out, "keep_em.simcfg"), os.path.join(out, "e2e_em.gds")
stackup = r"D:\github-claude\gds2palace_ihp_sg13g2\XML_stackup\latest\IHP\SG13G2_FEM_200um.xml"
if os.path.exists(path):
    os.remove(path)
print("first export updated an existing file:", write_simcfg(path, gds, stackup, "TOP", [port_entry(1, 201, "Z", None, "Metal3", "TopMetal2")]))
data = json.load(open(path))                    # what setupEM's Save Config adds
data["saved_values"].update({"fstart": 1.0, "fstop": 120.0, "fstep": 2.0, "refined_cellsize": 1.5, "order": 2})
data["elmer_mode"] = False
json.dump(data, open(path, "w"), indent=4)
print("second export updated an existing file:", write_simcfg(path, gds, stackup, "TOP",
      [port_entry(1, 201, "Z", None, "Metal3", "TopMetal2"), port_entry(2, 202, "X", "TopMetal2")]))
data = json.load(open(path))
v = data["saved_values"]
print("kept:", {k: v[k] for k in ("fstart", "fstop", "fstep", "refined_cellsize", "order")}, "elmer_mode" in data,
      "| set:", v["cellname"], os.path.basename(v["GdsFile"]), "| ports:", [p["portnumber"] for p in data["ports"]])
