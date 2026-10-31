# Batch test (KLayout -z -nc -rx -r, package installed in salt): ground net from via ports and from a marked shape.
#  1. OctaDiffTap demo: three feed ports Metal1 (ground) -> TopMetal2 (feeds LA, LB, LC).
#  2. core_transistor_3port_bce: ports 1-2 Metal3 -> TopMetal2, ports 3-5 Metal2 -> REF_FOR_TRANSISTOR (a sheet,
#     not traced), with the settings of the example's .simcfg.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import EXAMPLE_BCE, STACKUP, palace_testcases
import json
import pya
from klayout_em_export.connectivity import check_ground
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports
from klayout_em_export.stackup import Stackup



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


run("OctaDiffTap, ground from the via ports", palace_testcases("demo_mcp", "OctaDiffTap_0n50_ports3.gds"),
    STACKUP,
    {l: PortSettings("Z", "Metal1", "TopMetal2") for l in (201, 202, 203)})

ex = EXAMPLE_BCE
simcfg = json.load(open(os.path.join(ex, "50_ghz_mpa_core_bce_ports.simcfg")))
settings = {p["source_layernum"]: PortSettings(p["direction"], p["from_layername"] or "", p["to_layername"] or "",
                                               p["target_layername"] or "", p["port_Z0"], p["voltage"])
            for p in simcfg["ports"]}
print("bce ports:", {l: str(s) for l, s in settings.items()})
run("3-port BCE transistor, ground from the via ports", os.path.join(ex, "50_ghz_mpa_core_bce_ports.gds"),
    os.path.join(ex, "SG13G2_100um_bce_ports.xml"), settings)

run("OctaDiffTap, marked: the LA feed on TopMetal2 (ports would say Metal1)",
    palace_testcases("demo_mcp", "OctaDiffTap_0n50_ports3.gds"),
    STACKUP,
    {l: PortSettings("Z", "Metal1", "TopMetal2") for l in (201, 202, 203)}, seeds=[(134, 33.7, -41.5)])

# a shorted port: OctaDiffTap with a TopVia-free direct short is not available, so use a port whose both ends are
# the inductor: TopMetal1 -> TopMetal2 at a TopVia2 crossing joins the same net
st = Stackup(STACKUP)
ly = pya.Layout(); ly.read(palace_testcases("demo_mcp", "OctaDiffTap_0n50_ports3.gds"))
cell = ly.top_cell()
for layer in (201, 202, 203):
    for shape in cell.shapes(ly.find_layer(layer, 0)).each():
        shape.set_property(PROP_KEY, PortSettings("Z", "Metal1", "TopMetal2").encode())
tv2 = pya.Region(cell.begin_shapes_rec(ly.find_layer(133, 0)))
via = list(tv2.each())[0].bbox()                                   # a TopVia2: TopMetal1 and TopMetal2 both there
cell.shapes(ly.layer(204, 0)).insert(pya.Box(via.left, via.center().y, via.right, via.center().y)).set_property(
    PROP_KEY, PortSettings("Z", "TopMetal1", "TopMetal2").encode())
result = check_ground(ly, cell, st, ports=collect_ports(ly, cell, stackup=st))
print("## OctaDiffTap with port 4 across a TopVia2\n" + result.summary())
