# Batch test (KLayout -z -nc -rx -r): stackup layers inside the port layer range 201..299 are not ports (SUBGND is
# layer 250 in the SG13G2 stackups, 210 in the SG13CMOS5L ones). Environment: OUT (output folder).
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import GDS2PALACE

import pya
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
from klayout_em_export.export import export_flat, port_layer_numbers
from klayout_em_export.locate import next_port_layer
from klayout_em_export.ports import (PROP_KEY, PortSettings, collect_ports, export_numbering, export_port_numbers,
                                     simcfg_ports)
from klayout_em_export.stackup import Stackup

OUT = os.environ["OUT"]
os.makedirs(OUT, exist_ok=True)
XML = os.path.join(GDS2PALACE, "XML_stackup")
cases = [(os.path.join(XML, "latest", "IHP", "SG13G2_FEM_200um.xml"), 250),
         (os.path.join(XML, "legacy", "SG13CMOS5L_200um.xml"), 210)]
failed = []


def check(ok, text):
    print(("ok    " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


for xml, sub in cases:
    st = Stackup(xml)
    name = os.path.basename(xml)
    check(sub not in port_layer_numbers(st) and sub in port_layer_numbers(), f"{name}: {sub} is no port layer")
    ly = pya.Layout()
    ly.dbu = 0.001
    cell = ly.create_cell("TOP")
    m1, m2 = st.layer("Metal1").layer, st.layer("Metal2").layer
    cell.shapes(ly.layer(m1, 0)).insert(pya.DBox(0, 0, 100, 10).to_itype(ly.dbu))
    cell.shapes(ly.layer(m2, 0)).insert(pya.DBox(0, 0, 100, 10).to_itype(ly.dbu))
    cell.shapes(ly.layer(sub, 0)).insert(pya.DBox(0, 20, 100, 30).to_itype(ly.dbu))     # SUBGND shape
    settings = PortSettings("Z", "Metal1", "Metal2").encode()
    for i in range(10):                              # ten ports: with SUBGND on 210, the tenth needs layer 211
        layer = next_port_layer(ly, cell, stackup=st)
        x = 5 + 9 * i
        cell.shapes(ly.layer(layer, 0)).insert(pya.DBox(x, 2, x, 8).to_itype(ly.dbu),
                                               ly.properties_id([[PROP_KEY, settings]]))
    ports = collect_ports(ly, cell, stackup=st)
    check(sub not in ports and len(ports) == 10, f"{name}: 10 ports collected, SUBGND not among them ({sorted(ports)})")
    numbering = export_numbering(ports, st)
    check(sub not in numbering.values(), f"{name}: exported port layers skip {sub} ({sorted(numbering.values())})")
    numbers = export_port_numbers(numbering)
    check(sorted(numbers.values()) == list(range(1, 11)), f"{name}: port numbers 1..10 without gaps")
    entries = simcfg_ports(ports, numbering)
    check([e["portnumber"] for e in entries] == list(range(1, 11)) and
          all(e["source_layernum"] != sub for e in entries), f"{name}: .simcfg ports 1..10, none on layer {sub}")
    gds = os.path.join(OUT, f"portlayers_{sub}.gds")
    result = export_flat(ly, cell, st, gds, port_layers=numbering)
    out = pya.Layout()
    out.read(gds)
    li = out.find_layer(sub, 0)
    check(li is not None and out.top_cell().bbox_per_layer(li).height() == 10000,
          f"{name}: the SUBGND shape is exported on layer {sub}")

print("FAILED: " + "; ".join(failed) if failed else "all passed")
