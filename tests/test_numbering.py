# Batch test (KLayout -z -nc -rx -r, package installed in salt): a partial export gets port numbers without gaps.
# The user's case: BM_Ardavan_Rahimian_with_ports_partial.gds has ports 1-8; the EM region box (800/0) keeps
# port 1 and cuts five conductors, which get boundary ports 9-13. Exported: ports 1..6, with a port map.
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, palace_testcases, out_dir
import json
import pya
from klayout_em_export.boundary import create_ports, find_crossings
from klayout_em_export.connectivity import check_ground
from klayout_em_export.export import export_flat, marker_box
from klayout_em_export.ports import collect_ports, export_numbering, port_map, simcfg_ports
from klayout_em_export.simcfg import write_simcfg
from klayout_em_export.stackup import Stackup

OUT = out_dir("bm")
st = Stackup(STACKUP)
ly = pya.Layout(); ly.read(palace_testcases("klayout_export", "BM_Ardavan_Rahimian_with_ports_partial.gds"))
cell = ly.top_cell()
dbox = marker_box(ly, cell, (800, 0)); box = dbox.to_itype(ly.dbu)


class NoUndo:   # a standalone view in batch mode has no undo manager
    def transaction(self, text): pass
    def commit(self): pass
    def add_missing_layers(self): pass


ground = check_ground(ly, cell, st, box, ports=collect_ports(ly, cell, box, stackup=st))
print("ground:", ground.source, "| new boundary ports:", create_ports(NoUndo(), cell, st, find_crossings(ly, cell, st, box, ground)))
ports = collect_ports(ly, cell, box, stackup=st)
numbering = export_numbering(ports)
print("layout ports in the region:", sorted(p.number for p in ports.values()))
gds = os.path.join(OUT, "bm_partial_em.gds")
export_flat(ly, cell, st, gds, box=dbox, port_layers=numbering)
simcfg = gds.replace(".gds", ".simcfg")
if os.path.exists(simcfg):
    os.remove(simcfg)
write_simcfg(simcfg, gds, st.path, cell.name, ports=simcfg_ports(ports, numbering))
json.dump(port_map(ports, numbering), open(gds.replace(".gds", "_portmap.json"), "w"), indent=2)
print(".simcfg ports:", [(p["portnumber"], p["source_layernum"]) for p in json.load(open(simcfg))["ports"]])
for row in port_map(ports, numbering)["ports"]:
    print(f"  port {row['port']} (layer {row['layer']}) <- layout port {row['layout_port']} (layer {row['layout_layer']})")
check = pya.Layout(); check.read(gds)
print("port layers in the exported GDS:", sorted(check.get_info(li).layer for li in check.layer_indexes()
                                                 if 201 <= check.get_info(li).layer <= 299))
for layer in sorted(numbering.values()):
    li = check.find_layer(layer, 0)
    print(f"  layer {layer}:", [str(s.dbbox()) for s in check.top_cell().shapes(li).each()])
