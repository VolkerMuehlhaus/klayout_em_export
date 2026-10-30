# Batch test (KLayout -z -nc -rx -r, package installed in salt): ground net from via ports and from a marked shape.
#  1. OctaDiffTap demo: three feed ports Metal1 (ground) -> TopMetal2 (feeds LA, LB, LC).
#  2. core_transistor_3port_bce: ports 1-2 Metal3 -> TopMetal2, ports 3-5 Metal2 -> REF_FOR_TRANSISTOR (a sheet,
#     not traced), with the settings of the example's .simcfg.
import json
import os
import pya
from klayout_em_export.connectivity import check_ground
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports
from klayout_em_export.stackup import Stackup

IHP = r"D:\github-claude\gds2palace_ihp_sg13g2"


def run(title, gds, stackup_file, settings, seeds=()):
    st = Stackup(stackup_file)
    ly = pya.Layout(); ly.read(gds)
    cell = next(c for c in ly.top_cells() if not c.name.startswith("$$$"))
    for layer, s in settings.items():
        for shape in cell.shapes(ly.find_layer(layer, 0)).each():
            shape.set_property(PROP_KEY, s.encode())
    ports = collect_ports(ly, cell, stackup=st)
    seeds = [(layer, pya.Point(round(x / ly.dbu), round(y / ly.dbu))) for layer, x, y in seeds]
    result = check_ground(ly, cell, st, seeds=seeds, ports=ports)
    print(f"## {title}\n" + result.summary())


run("OctaDiffTap, ground from the via ports", r"D:\Palace_testcases\demo_mcp\OctaDiffTap_0n50_ports3.gds",
    os.path.join(IHP, r"XML_stackup\latest\IHP\SG13G2_FEM_200um.xml"),
    {l: PortSettings("Z", "Metal1", "TopMetal2") for l in (201, 202, 203)})

ex = os.path.join(IHP, r"more_examples\core_transistor_3port_bce")
simcfg = json.load(open(os.path.join(ex, "50_ghz_mpa_core_bce_ports.simcfg")))
settings = {p["source_layernum"]: PortSettings(p["direction"], p["from_layername"] or "", p["to_layername"] or "",
                                               p["target_layername"] or "", p["port_Z0"], p["voltage"])
            for p in simcfg["ports"]}
print("bce ports:", {l: str(s) for l, s in settings.items()})
run("3-port BCE transistor, ground from the via ports", os.path.join(ex, "50_ghz_mpa_core_bce_ports.gds"),
    os.path.join(ex, "SG13G2_100um_bce_ports.xml"), settings)

run("OctaDiffTap, marked: the LA feed on TopMetal2 (ports would say Metal1)",
    r"D:\Palace_testcases\demo_mcp\OctaDiffTap_0n50_ports3.gds",
    os.path.join(IHP, r"XML_stackup\latest\IHP\SG13G2_FEM_200um.xml"),
    {l: PortSettings("Z", "Metal1", "TopMetal2") for l in (201, 202, 203)}, seeds=[(134, 33.7, -41.5)])
