# Batch test (KLayout -z -nc -rx -r): a split EM region (regions.py, pieces.py). A 480 um coplanar line on TopMetal2
# with line-end ports, two EM region boxes cut at x = 240:
#  numbering, the cut, the ports at the cut (one per piece, port wall, owner), the checks, Export All (whole region
#  with the outer ports, the pieces with their own, the set section), fingerprints (stable, changed only for the
#  edited piece), Split, overlap / via port on a cut / moved box, Import Pieces (round trip, moved design, one box).
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from testpaths import STACKUP, out_dir
import pya
from klayout_em_export.boundary import create_ports, find_crossings
from klayout_em_export.connectivity import check_ground
from klayout_em_export.pieces import (apply_set, cut_problems, export_pieces, import_warnings, piece_ports, read_set,
                                      split_state, stale_piece_folders)
from klayout_em_export.pipeline import NoUndo, export_em
from klayout_em_export.ports import PROP_KEY, PortSettings, collect_ports
from klayout_em_export.regions import (PIECE_KEY, cuts_of, needs_numbers, number_pieces, read_pieces,
                                       split_piece)
from klayout_em_export.stackup import Stackup
from klayout_em_export.tech import ihp_sg13 as tech

OUT = out_dir("test_pieces")
st = Stackup(STACKUP)
TM2 = 134
failures = []


def check(ok, text):
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        failures.append(text)


def make_layout(dx=0, dy=0):
    ly = pya.Layout()
    ly.dbu = 0.001
    cell = ly.create_cell("line")
    um = lambda v: round(v / ly.dbu)
    m = cell.shapes(ly.layer(TM2, 0))
    for box in ((0, 15, 480, 55), (0, -55, 480, -15), (1, -5, 479, 5)):
        m.insert(pya.Box(um(box[0] + dx), um(box[1] + dy), um(box[2] + dx), um(box[3] + dy)))
    for layer, direction, x0 in ((201, "X", 0), (202, "-X", 479)):
        cell.shapes(ly.layer(layer, 0)).insert(pya.Box(um(x0 + dx), um(-5 + dy), um(x0 + 1 + dx), um(5 + dy)),
                                               ly.properties_id([[PROP_KEY, PortSettings(direction, target="TopMetal2").encode()]]))
    return ly, cell, um


def seeds_of(ly):
    return [(TM2, pya.Point(round(100 / ly.dbu), round(30 / ly.dbu))),
            (TM2, pya.Point(round(100 / ly.dbu), round(-30 / ly.dbu)))]


def create_cut_ports(ly, cell, seeds):
    pieces, cuts, _ = split_state(ly, cell)
    made = {}
    for piece in pieces:
        mine = cuts_of(cuts, piece.name)
        ground = check_ground(ly, cell, st, piece.box, seeds, piece_ports(ly, cell, st, piece, cuts))
        crossings = find_crossings(ly, cell, st, piece.box, ground, piece.name, mine)
        made[piece.name] = create_ports(NoUndo(), cell, st, crossings, port_wall=False)
    return made


# ---------- numbering and the cut ----------
ly, cell, um = make_layout()
region = cell.shapes(ly.layer(800, 0))
region.insert(pya.Box(um(240), um(-55), um(480), um(55)))
region.insert(pya.Box(um(0), um(-55), um(240), um(55)))
check(needs_numbers(ly, cell), "two boxes without numbers need numbers")
given = number_pieces(ly, cell)
pieces, problems = read_pieces(ly, cell)
check(given == ["p1", "p2"] and [p.name for p in pieces] == ["p1", "p2"] and pieces[0].box.left == 0,
      f"numbered in reading order (left first): {given}, {pieces}")
check(not problems and not needs_numbers(ly, cell), f"no problems after numbering: {problems}")
check(number_pieces(ly, cell) == [], "numbering again changes nothing")
pieces, cuts, _ = split_state(ly, cell)
check(len(cuts) == 1 and cuts[0].a == "p1" and cuts[0].b == "p2" and cuts[0].vertical and cuts[0].edge.x1 == um(240),
      f"one vertical cut p1|p2 at x = 240: {cuts}")

# ---------- ports at the cut ----------
seeds = seeds_of(ly)
before = cut_problems(ly, cell, st, pieces, cuts, seeds)[0]
check(any("without a port in p1" in t for t in before) and any("without a port in p2" in t for t in before),
      f"the line crossing the cut needs a port in both pieces: {before}")
made = create_cut_ports(ly, cell, seeds)
check(len(made["p1"]) == 1 and len(made["p2"]) == 1, f"one port per piece at the cut, via ports not chosen: {made}")
all_ports = collect_ports(ly, cell, stackup=st)
cut_ports = {p.owner: p for p in all_ports.values() if p.owner}
check(set(cut_ports) == {"p1", "p2"} and str(cut_ports["p1"].settings).strip().startswith("-X on TopMetal2")
      and str(cut_ports["p2"].settings).strip().startswith("X on TopMetal2"),
      f"port wall ports pointing into their piece: { {k: str(v.settings) for k, v in cut_ports.items()} }")
again = create_cut_ports(ly, cell, seeds)
check(again == {"p1": [], "p2": []}, f"a second run makes no more ports: {again}")
p1_ports = piece_ports(ly, cell, st, pieces[0], cuts)
check(sorted(p.number for p in p1_ports.values()) == sorted([1, cut_ports["p1"].number]),
      f"p1 has its outer port and its own cut port only: {sorted(p.number for p in p1_ports.values())}")
problems, warnings = cut_problems(ly, cell, st, pieces, cuts, seeds)
check(not problems and not warnings, f"no problems or warnings at the cut: {problems} {warnings}")

# ---------- Export All ----------
gds = os.path.join(OUT, "split_em.gds")
result = export_pieces(ly, cell, st, gds, tech, seeds=seeds)
check(not result["problems"], f"export without problems: {result['problems']}")
section = result["set"]
print("set:", json.dumps(section, indent=1)[:1500])
main = json.load(open(os.path.join(OUT, "split_em.simcfg")))
check(main.get("pieces") == section and [p["portnumber"] for p in main["ports"]] == [1, 2],
      "the whole region's .simcfg has the outer ports 1, 2 and the pieces section")
whole = pya.Layout(); whole.read(gds)
port_layers = sorted(whole.get_info(li).layer for li in whole.layer_indexes() if 201 <= whole.get_info(li).layer <= 299
                     and not whole.top_cell().shapes(li).is_empty())
check(port_layers == [201, 202], f"the whole region's GDS has no ports at the cut: {port_layers}")
folder = os.path.join(OUT, "split_em_pieces")
for name in ("p1", "p2"):
    data = json.load(open(os.path.join(folder, name + ".simcfg")))
    check(data["saved_values"]["boundary"][:2] == ["PORTWALL", "PORTWALL"] and data.get("piece") == name and
          data.get("piece_of") == "split_em.simcfg" and len(data["ports"]) == 2
          and data.get("wall_sides") == ["xmax", "xmin"],
          f"{name}.simcfg: port walls both x sides, wall sides, piece_of, two ports: "
          f"{data['saved_values']['boundary']} {data.get('wall_sides')}")
full = json.load(open(os.path.join(folder, "full.simcfg")))
check(full["saved_values"]["model_basename"] == "full" and full["saved_values"]["sim_path"] == folder.replace("\\", "/")
      and full.get("piece") == "full" and full["saved_values"]["GdsFile"].endswith("split_em.gds")
      and full.get("wall_sides") == ["xmax", "xmin"]
      and section.get("full") == "split_em_pieces/full.simcfg",
      "the full check model: the whole region's GDS, in the pieces folder, named full")
p1cfg = json.load(open(os.path.join(folder, "p1.simcfg")))
check(p1cfg["saved_values"]["model_basename"] == "p1" and p1cfg["saved_values"]["sim_path"] == folder.replace("\\", "/"),
      "a piece's model is named after it, in the pieces folder")
check(len(section["links"]) == 1 and section["links"][0]["ports"][0][0] == "p1" and section["links"][0]["ports"][1][0] == "p2"
      and section["links"][0]["layer"] == "TopMetal2",
      f"one link p1|p2 on TopMetal2: {section['links']}")
ext = {e["port"]: (e["piece"], e["layout_port"]) for e in section["external"]}
check(ext == {1: ("p1", 1), 2: ("p2", 2)}, f"joined ports: 1 from p1 (layout port 1), 2 from p2 (layout port 2): {ext}")
link = section["links"][0]["ports"]
p1_numbers = section["pieces"][0]["ports"]
check(str(link[0][1]) in p1_numbers and p1_numbers[str(link[0][1])] == cut_ports["p1"].number,
      f"the link names p1's exported number of its cut port: {link} {p1_numbers}")

# ---------- fingerprints ----------
fp = {p["name"]: p["fingerprint"] for p in section["pieces"]}
same = export_pieces(ly, cell, st, gds, tech, seeds=seeds)["set"]
check({p["name"]: p["fingerprint"] for p in same["pieces"]} == fp, "a second export gives the same fingerprints")
cell.shapes(ly.layer(TM2, 0)).insert(pya.Box(um(400), um(5), um(410), um(12)))     # a stub in p2
edited = {p["name"]: p["fingerprint"] for p in export_pieces(ly, cell, st, gds, tech, seeds=seeds)["set"]["pieces"]}
check(edited["p1"] == fp["p1"] and edited["p2"] != fp["p2"], "an edit inside p2 changes only p2's fingerprint")

# ---------- Split, overlap, via port on a cut, moved box ----------
low, high = split_piece(ly, cell, pya.Point(um(360), 0), vertical=True)
check((low.name, high.name) == ("p2", "p3") and low.box.right == um(360) and high.box.left == um(360),
      f"splitting p2 at x = 360 keeps p2 on the left, p3 on the right: {low}, {high}")
pieces, cuts, problems = split_state(ly, cell)
check([p.name for p in sorted(pieces, key=lambda p: p.number)] == ["p1", "p2", "p3"] and len(cuts) == 2 and not problems,
      f"three pieces, two cuts: {pieces} {cuts} {problems}")
moved = cut_problems(ly, cell, st, pieces, cuts, seeds)[0]
check(any("p3" in t and "without a port" in t for t in moved) and any("p2" in t and "without a port" in t for t in moved),
      f"the new cut needs its ports: {moved}")
create_cut_ports(ly, cell, seeds)
pieces, cuts, _ = split_state(ly, cell)
check(not cut_problems(ly, cell, st, pieces, cuts, seeds)[0], "after Create Proposed Ports the new cut is complete")
three = export_pieces(ly, cell, st, gds, tech, seeds=seeds)
check(not three["problems"] and len(three["set"]["pieces"]) == 3 and len(three["set"]["links"]) == 2,
      f"three pieces exported with two links: {three['problems']}")
region.insert(pya.Box(um(100), um(-20), um(300), um(20)))
check(any("overlap" in t for t in split_state(ly, cell)[2]), "an overlapping box is reported")
# back to three pieces: remove the overlapping box (the one without a number)
pieces, _ = read_pieces(ly, cell)
from klayout_em_export.regions import set_pieces
set_pieces(ly, cell, [p for p in pieces if p.number is not None])
via_layer = 250 - 1
cell.shapes(ly.layer(via_layer, 0)).insert(pya.Box(um(360), um(-5), um(360), um(5)),
                                           ly.properties_id([[PROP_KEY, PortSettings("Z", "Metal1", "TopMetal2").encode()]]))
pieces, cuts, _ = split_state(ly, cell)
check(any("via port on the cut" in t for t in cut_problems(ly, cell, st, pieces, cuts, seeds)[0]),
      "a via port on a cut is reported")
cell.shapes(ly.find_layer(via_layer, 0)).clear()

# ---------- stale piece files: back to two pieces ----------
pieces, _ = read_pieces(ly, cell)
p2 = next(p for p in pieces if p.name == "p2")
p3 = next(p for p in pieces if p.name == "p3")
p2.box = pya.Box(p2.box.left, p2.box.bottom, p3.box.right, p2.box.top)
set_pieces(ly, cell, [p for p in pieces if p.name != "p3"])
for layer, port in collect_ports(ly, cell, stackup=st).items():          # the ports at the old cut
    if port.owner and any(s.bbox().transformed(t).left == um(360) for s, t, _ in port.items):
        cell.shapes(ly.find_layer(layer, 0)).clear()
pieces, cuts, _ = split_state(ly, cell)
problems = cut_problems(ly, cell, st, pieces, cuts, seeds)[0]
check(not problems, f"merged back to two pieces without problems: {problems}")
two = export_pieces(ly, cell, st, gds, tech, seeds=seeds)
stale = [os.path.basename(p) for p in stale_piece_folders(two["folder"], two["set"])]
check("p3.gds" in stale and "p3.simcfg" in stale and not any(s.startswith(("p1", "p2")) for s in stale),
      f"p3's files are listed as stale: {stale}")

# ---------- Import Pieces ----------
imported = read_set(os.path.join(OUT, "split_em.simcfg"))
fresh, fcell, _ = make_layout()
fresh.dbu = ly.dbu
ground = apply_set(fresh, fcell, imported)
boxes = sorted((n, p.box.left, p.box.right) for n, p in [(p.name, p) for p in read_pieces(fresh, fcell)[0]])
check(boxes == [("p1", 0, um(240)), ("p2", um(240), um(480))], f"imported boxes with their numbers: {boxes}")
check(sorted((l, p.x, p.y) for l, p in ground) == sorted((l, p.x, p.y) for l, p in seeds), "imported ground marks")
check(import_warnings(fresh, fcell, st, imported) == [], f"no warnings on the same design: "
      f"{import_warnings(fresh, fcell, st, imported)}")
create_cut_ports(fresh, fcell, ground)
fp_pieces, fp_cuts, _ = split_state(fresh, fcell)
check(not cut_problems(fresh, fcell, st, fp_pieces, fp_cuts, ground)[0], "after the import, Create Proposed Ports completes the cut")
shifted, scell, _ = make_layout(dx=50)
apply_set(shifted, scell, imported)
w = import_warnings(shifted, scell, st, imported)
check(any("p1 reaches outside" in t for t in w), f"a design moved along the line: the box reaches outside it: {w}")
shifted, scell, _ = make_layout(dy=20)
apply_set(shifted, scell, imported)
w = import_warnings(shifted, scell, st, imported)
check(any("no longer crosses the TopMetal2 line" in t for t in w),
      f"a design moved across the cut: the line is not where it was (a ground strip is there now): {w}")

other, ocell, _ = make_layout()
ocell.name = "other"
check(any("recorded for cell line" in t for t in import_warnings(other, ocell, st, imported)), "another cell name is noted")
# one box: an export without pieces imports as one unnumbered box
single, scell1, sum1 = make_layout()
scell1.shapes(single.layer(800, 0)).insert(pya.Box(sum1(0), sum1(-55), sum1(480), sum1(55)))
r1 = export_em(single, scell1, st, os.path.join(OUT, "single_em.gds"), tech, box=pya.DBox(0, -55, 480, 55))
one = read_set(r1["simcfg"])
check(len(one["pieces"]) == 1, f"a one-box export imports as one piece: {one['pieces']}")
blank, bcell, _ = make_layout()
apply_set(blank, bcell, one)
pieces, _ = read_pieces(blank, bcell)
check(len(pieces) == 1 and pieces[0].number is None, f"one imported box stays a plain EM region box: {pieces}")
props = [s.property(PIECE_KEY) for s in bcell.shapes(blank.layer(800, 0)).each()]
check(props == [None], f"no piece number written for one box: {props}")

print("FAIL: " + "; ".join(failures) if failures else "all passed")
