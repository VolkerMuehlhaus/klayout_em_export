# Batch test (KLayout -z -nc -rx -r): the headless JSON interface (python/klayout_em_export/cli.py), command by
# command, on the OctaDiffTap demo (ports without settings, no devices) and the cascode (PDK devices, ground mark).
# The cascode export through the CLI must equal pipeline.export_em called directly (the GUI's export). Needs the PDK
# (tests/pdk_env.py); run with KLAYOUT_PATH/KLAYOUT_HOME pointing to an empty folder.
import json
import os
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import DATA_DIR, PDK_ROOT, STACKUP, layout_file

import pya
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))   # not via salt here
from klayout_em_export import cli, tech
from klayout_em_export.pipeline import export_em
from klayout_em_export.stackup import Stackup

OUT = os.environ.get("OUT") or tempfile.mkdtemp(prefix="test_cli_")
os.makedirs(OUT, exist_ok=True)
PDK = PDK_ROOT
failed = []


def check(ok, text):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)


def run(**request):
    try:
        result = cli.run(request)
    except cli.RequestError as e:
        result = {"ok": False, "error": str(e)}
    return result


def out(name):
    return os.path.join(OUT, name)


# ---- OctaDiffTap: three port shapes without settings, TopMetal2 feeds at y = -42 ----
octa = layout_file("OctaDiffTap_0n50_ports3.gds")
r = run(command="status", gds=octa, stackup=STACKUP)
check(r["ok"] and [p["port"] for p in r["ports"]] == [1, 2, 3] and not any(p["complete"] for p in r["ports"]),
      f"status: 3 ports without settings ({[p['problems'] for p in r['ports']]})")
check(r["technology"] == "generic", f"status: technology {r['technology']} ({r['technology_reason']})")
from klayout_em_export import __version__
check(r.get("version") == __version__, f"status: plug-in version {r.get('version')}")

r = run(command="add_via_port", gds=octa, stackup=STACKUP, x=33.7, y=-42.2)
check(not r["ok"] and "output" in r["error"], f"a changing command needs 'output': {r.get('error')}")
r = run(command="add_via_port", gds=octa, stackup=STACKUP, x=33.7, y=-42.2, output=octa)
check(not r["ok"] and "overwrite" in r["error"], f"the input is not overwritten by default: {r.get('error')}")

r = run(command="add_via_port", gds=octa, stackup=STACKUP, x=33.7, y=-42.2, output=out("octa_via.gds"))
check(r["ok"] and r["port"] == 4 and r["settings"] == "port:dir=Z;from=TopMetal2;to=Metal1;z0=50;v=1",
      f"add_via_port on the TopMetal2 feed: port {r.get('port')}, {r.get('settings')}, at {r.get('metals_at_port')}")
r = run(command="status", gds=out("octa_via.gds"))
check(r["ok"] and r["stackup"] == STACKUP, "the stackup is stored in the written layout (meta info)")
check(next(p for p in r["ports"] if p["port"] == 4)["complete"], "the new port is complete")

r = run(command="add_inplane_port", gds=out("octa_via.gds"), x=39.0, y=-41.0, output=out("octa_plane.gds"))
check(r["ok"] and r["settings"] == "port:dir=X;target=TopMetal2;z0=50;v=1" and r["port"] == 5,
      f"add_inplane_port in the gap: port {r.get('port')}, {r.get('settings')}")
r = run(command="add_via_port", gds=octa, stackup=STACKUP, x=0, y=0, output=out("x.gds"))
check(not r["ok"] and "no horizontal or vertical metal edge" in r["error"], f"no edge: {r.get('error')}")
r = run(command="add_via_port", gds=octa, stackup=STACKUP, x=33.7, y=-42.2, metal="Metal7", output=out("x.gds"))
check(not r["ok"] and "not a drawn metal" in r["error"], f"unknown metal: {r.get('error')}")

r = run(command="set_port", gds=out("octa_plane.gds"), port=1, direction="Z", **{"from": "TopMetal2", "to": "Metal1"},
        z0=25, output=out("octa_set.gds"))
check(r["ok"] and r["settings"] == "port:dir=Z;from=TopMetal2;to=Metal1;z0=25;v=1" and not r["problems"],
      f"set_port 1: {r.get('settings')} {r.get('problems')}")
r = run(command="remove_port", gds=out("octa_set.gds"), port=3, output=out("octa_removed.gds"))
check(r["ok"] and r["removed_shapes"] == 1, "remove_port 3")
r = run(command="status", gds=out("octa_removed.gds"))
check([p["port"] for p in r["ports"]] == [1, 2, 4, 5], f"ports after removing 3: {[p['port'] for p in r['ports']]}")

r = run(command="set_region", gds=out("octa_removed.gds"), box=[20, -60, 70, 60], output=out("octa_region.gds"))
r = run(command="status", gds=out("octa_region.gds"))
check(r["region"] == [20.0, -60.0, 70.0, 60.0], f"set_region: {r['region']}")
r = run(command="boundary_ports", gds=out("octa_region.gds"))
check(r["ok"] and isinstance(r["crossings"], list) and r["created"] == [],
      f"boundary_ports lists {len(r.get('crossings', []))} crossing(s) without creating ports")

r = run(command="export", gds=out("octa_removed.gds"), out=out("octa_em.gds"))
check(r["ok"] and r["ports"] == 4 and r["simcfg_ports"] == 3 and r["checks"]["left_out"] == [2],
      f"export: {r.get('ports')} ports, {r.get('simcfg_ports')} in the .simcfg, left out {r.get('checks', {}).get('left_out')}")
check(all(os.path.isfile(r[k]) for k in ("gds", "simcfg", "portmap")), "export wrote the .gds, .simcfg and port map")
r = run(command="export", gds=octa, stackup=STACKUP, out=octa)
check(not r["ok"] and "layout itself" in r["error"], f"export refuses to overwrite the layout: {r.get('error')}")
r = run(command="nonsense", gds=octa)
check(not r["ok"] and "unknown command" in r["error"], "unknown command")

# ---- cascode: PDK devices, a ground mark in the layout ----
cascode = layout_file("1_St_Core_v1_forEM.gds")
cell = "Cascode_DegInd_CBias_Sym_Res_tb"
r = run(command="status", gds=cascode, stackup=STACKUP, pdk=PDK)
check(not r["ok"] and "top cells" in r["error"], "several top cells: 'cell' is asked for")
r = run(command="status", gds=cascode, cell=cell, stackup=STACKUP, pdk=PDK)
check(r["ok"] and r["technology"] == "ihp_sg13" and r["ground"]["marks"] == 1,
      f"cascode status: {r.get('technology')}, ground marks {r.get('ground', {}).get('marks')}")
check(sorted(d["pcell"] for d in r["devices"]) == ["npn13G2", "npn13G2", "rhigh", "rhigh", "rsil"],
      f"devices with the PDK library: {sorted(d['pcell'] for d in r['devices'])}")

r = run(command="devices", action="unreplace", gds=cascode, cell=cell, stackup=STACKUP, pdk=PDK, output=out("c1.gds"))
check(r["ok"] and not any(d["replaced"] for d in r["devices"]), f"unreplace: {r.get('removed_shapes')} shape(s)")
r = run(command="devices", action="replace", resistors=True, gds=out("c1.gds"), cell=cell, pdk=PDK,
        output=out("c2.gds"))
check(r["ok"] and all(d["replaced"] for d in r["devices"]), f"replace with resistors: {len(r.get('replaced', {}))}")
r = run(command="add_via_port", gds=out("c2.gds"), cell=cell, pdk=PDK, x=-29.205, y=9.6, metal="Metal2", to="Metal5",
        output=out("c3.gds"))
check(r["ok"] and r["settings"] == "port:dir=Z;from=Metal2;to=Metal5;z0=50;v=1",
      f"Cas_Bias port: {r.get('settings')}")
r = run(command="export", gds=out("c3.gds"), cell=cell, pdk=PDK, out=out("cascode_cli_em.gds"))
check(r["ok"] and r["ports"] == 15 and not r["checks"]["problems"], f"cascode export: {r.get('ports')} ports, "
      f"problems {r.get('checks', {}).get('problems')}")

# the same layout exported directly with export_em, as the GUI does
ly = pya.Layout()
ly.technology_name = "sg13g2"
ly.read(out("c3.gds"))
direct = export_em(ly, ly.cell(cell), Stackup(STACKUP), out("cascode_direct_em.gds"), tech.for_layout(ly)[0],
                   seeds=cli.ground_seeds(ly))
for suffix in ("_portmap.json", ".simcfg"):
    a = json.load(open(out("cascode_cli_em" + suffix)))
    b = json.load(open(out("cascode_direct_em" + suffix)))
    for d in (a, b):
        d.get("saved_values", {}).pop("GdsFile", None)     # the file names differ
    check(a == b, f"CLI export == export_em: {suffix}")

# thermal export through the CLI: one heat source per device, from the PDK's heat shapes
r = run(command="export_thermal", gds=out("c3.gds"), cell=cell, pdk=PDK, out=out("cascode_cli_thermal.gds"),
        lvsdb=os.path.join(DATA_DIR, "lvs_cascode", "cascode.lvsdb"))
check(r["ok"] and r["sources"] == 5 and not r["bounding_box"] and
      all(os.path.isfile(r[k]) for k in ("gds", "tsimcfg", "thermalmap")),
      f"thermal export: {r.get('sources')} heat sources, bounding box used for {r.get('bounding_box')}")
check(r["lvs"]["named"] == 5, f"thermal export: names from LVS {r.get('lvs')}")

# KLayout knows sg13g2 now (the PDK was loaded above): without "pdk", a layout still gets no technology from that
r = run(command="status", gds=octa, stackup=STACKUP)
check(r["technology"] == "generic", f"no pdk in the request: technology {r['technology']} although KLayout knows "
      "sg13g2 now")

print("all passed" if not failed else f"FAILED: {'; '.join(failed)}")
