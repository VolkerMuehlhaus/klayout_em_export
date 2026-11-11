# Batch test (KLayout -zz -nc -rx -r, needs pya): layer types in any case. gds2palace reads Type="conductor",
# "Conductor" or "CONDUCTOR" alike (a PCB stackup such as pcb_ro4003.xml writes "Conductor"); the plug-in must too,
# or it finds no metals and the device step crashes on an empty min() (seen on a PCB hairpin, 2026-11-10). A stackup
# without any conductor lists no devices instead of failing.
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python"))
import pya  # noqa: E402
from klayout_em_export.connectivity import wiring  # noqa: E402
from klayout_em_export.devices import device_level_layers, find_devices  # noqa: E402
from klayout_em_export.stackup import Stackup  # noqa: E402

failed = []


def check(ok, text):
    print(("ok    " if ok else "FAIL  ") + text)
    if not ok:
        failed.append(text)


XML = """<?xml version="1.0" encoding="UTF-8"?>
<Stackup schemaVersion="2.0">
  <Materials>
    <Material Name="Cu" Type="Conductor" Permittivity="1" DielectricLossTangent="0" Conductivity="5.8e7"/>
    <Material Name="FR4" Type="Dielectric" Permittivity="4.4" DielectricLossTangent="0.02" Conductivity="0"/>
    <Material Name="AIR" Type="Dielectric" Permittivity="1" DielectricLossTangent="0" Conductivity="0"/>
  </Materials>
  <ELayers LengthUnit="um">
    <Dielectrics>
      <Dielectric Name="AIR" Material="AIR" Thickness="1000"/>
      <Dielectric Name="FR4" Material="FR4" Thickness="500"/>
      <Dielectric Name="AIR" Material="AIR" Thickness="1000"/>
    </Dielectrics>
    <Layers>
      <Substrate Offset="1000"/>
      {layers}
    </Layers>
  </ELayers>
</Stackup>
"""
LAYERS = """<Layer Name="Bottom" Type="Conductor" Zmin="0" Zmax="35" Material="Cu" Layer="1"/>
      <Layer Name="Via" Type="VIA" Zmin="35" Zmax="465" Material="Cu" Layer="5"/>
      <Layer Name="Top" Type="CONDUCTOR" Zmin="465" Zmax="500" Material="Cu" Layer="10"/>"""

with tempfile.TemporaryDirectory() as tmp:
    def stackup(layers, name):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(XML.replace("{layers}", layers))
        return Stackup(path)

    st = stackup(LAYERS, "mixed_case.xml")
    check([l.kind for l in st.layers] == ["conductor", "via", "conductor"],
          f"types read in lower case: {[l.kind for l in st.layers]}")
    metals, connections = wiring(st)
    check(metals == {1: "Bottom", 10: "Top"} and connections == [(5, 1, 10)],
          f"metals {metals} and the via between them {connections}")
    layout = pya.Layout()
    cell = layout.create_cell("top")
    cell.shapes(layout.layer(10, 0)).insert(pya.Box(0, 0, 1000, 100))
    check(find_devices(layout, cell, st)[0] == [], "find_devices on a PCB layout: no devices, no error")

    # ReferenceEdge in any case, as gds2palace: "TOP" places the layer like "Top"
    cover = '<Layer Name="Cover" Type="conductor" Reference="FR4" ReferenceEdge="{edge}" Zmin="0" Zmax="10" ' \
            'Material="Cu" Layer="20"/>'
    upper, title = (stackup(cover.replace("{edge}", e), f"edge_{e}.xml") for e in ("TOP", "Top"))
    z_upper, z_title = (s.z_range(s.layer("Cover")) for s in (upper, title))
    check(z_upper == z_title and z_title is not None and z_title[1] > 0,
          f"ReferenceEdge TOP == Top: {z_upper} vs {z_title}")

    bare = stackup("", "no_conductor.xml")
    check(device_level_layers(bare) == set(), "no conductor: no device level layers")
    check(find_devices(layout, cell, bare) == ([], []), "no conductor: no devices instead of an error")

print("all passed" if not failed else f"FAILED: {'; '.join(failed)}")
sys.exit(1 if failed else 0)
