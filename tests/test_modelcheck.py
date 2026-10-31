# Plain Python test (also runs in KLayout batch): model scripts whose ports no longer match a re-export
# (python/klayout_em_export/modelcheck.py). Uses a script written here in a temp folder, and the real setupEM script
# Palace_testcases/klayout_export/1_St_Core_v1_em.py with its .simcfg (see testpaths.py), which must match.
import json
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import palace_testcases

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from klayout_em_export.modelcheck import script_info, stale_scripts

failed = []


def check(ok, text):
    print(("ok    " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


def port(n, layer, frm=None, to=None, target=None, direction="Z", voltage=1.0):
    return {"portnumber": n, "source_layernum": layer, "from_layername": frm, "to_layername": to,
            "target_layername": target, "direction": direction, "port_Z0": 50.0, "voltage": voltage}


def script(gds_literal, ports):
    lines = ["from gds2palace import *", f"settings = {{}}", f"settings['GdsFile'] = {gds_literal!r}"]
    for p in ports:
        args = ", ".join(f"{k}={p[k]!r}" for k in ("portnumber", "voltage", "port_Z0", "source_layernum",
                                                     "from_layername", "to_layername", "target_layername",
                                                     "direction") if p[k] is not None)
        lines.append(f"simulation_ports.add_port(simulation_setup.simulation_port({args}))")
    return "\n".join(lines) + "\n"


folder = tempfile.mkdtemp(prefix="modelcheck_")
gds = os.path.join(folder, "chip_em.gds")
ports = [port(1, 201, "TopMetal2", "Metal5"), port(2, 202, "TopMetal2", "Metal5"), port(3, 203, target="Metal5",
                                                                                          direction="X")]
with open(os.path.join(folder, "chip_em.py"), "w") as f:
    f.write(script(gds, ports))
with open(os.path.join(folder, "relative.py"), "w") as f:            # relative GDS path, excitation changed by hand
    f.write(script("chip_em.gds", [dict(p, voltage=0.0) for p in ports]))
with open(os.path.join(folder, "other.py"), "w") as f:               # a script for another GDS
    f.write(script(os.path.join(folder, "other_em.gds"), ports[:1]))

check(script_info(os.path.join(folder, "other.py"), gds) is None, "a script for another GDS is ignored")
check(script_info(os.path.join(folder, "relative.py"), gds) is not None, "a relative GDS path is recognized")
check(stale_scripts(gds, ports, [folder]) == [], "same ports: nothing stale (excitation is not compared)")

# re-export: port 2 removed, the old port 3 renumbered to 2, a new port 3 on another layer
new = [ports[0], dict(ports[2], portnumber=2, source_layernum=202), port(3, 203, "Metal1", "REF_FOR_TRANSISTOR")]
stale = stale_scripts(gds, new, [folder, folder])
names = sorted(os.path.basename(p) for p, _ in stale)
check(names == ["chip_em.py", "relative.py"], f"both scripts for this GDS are stale, each once: {names}")
diff = dict(stale)[os.path.join(folder, "chip_em.py")]
print("      " + " | ".join(diff))
check(any(d.startswith("port 2:") for d in diff) and any(d.startswith("port 3:") for d in diff),
      "the changed ports are named")

# the real setupEM script made from the cascode export matches its own .simcfg
real = palace_testcases("klayout_export", "1_St_Core_v1_em.py")
if os.path.isfile(real):
    with open(real.replace(".py", ".simcfg")) as f:
        simcfg_ports = json.load(f)["ports"]
    gds_real = palace_testcases("klayout_export", "1_St_Core_v1_em.gds")
    info = script_info(real, gds_real)
    check(info is not None and len(info) == len(simcfg_ports), f"setupEM script recognized, {len(info or {})} ports")
    check(stale_scripts(gds_real, simcfg_ports, [os.path.dirname(real)]) == [], "setupEM script matches its .simcfg")
else:
    print("skip  " + real + " not found")

print("FAILED: " + "; ".join(failed) if failed else "all ok")
