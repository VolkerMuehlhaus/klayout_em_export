"""Split region workflow without the GUI: the ports of each piece, the checks of the cuts, Export All and Import
Pieces (regions.py has the boxes). pya and the standard library only, like pipeline.py; nothing here reads or writes
the settings file or the layout's meta info.

Export All writes the whole region as today (<export>.gds, .simcfg, _portmap.json: the outer ports, which are the
ports of the joined result) and every piece into <export>_pieces/ (p1.gds, p1.simcfg, p1_portmap.json, ...). The
"pieces" section of <export>.simcfg tells setupEM which pieces to run and how to join them:

  {"version": 1, "folder": "<export>_pieces", "cell": ..., "stackup": ...,
   "pieces": [{"name": "p1", "box": [x1, y1, x2, y2], "gds": "<export>_pieces/p1.gds", "simcfg": ..., "portmap": ...,
               "fingerprint": sha256, "ports": {"<exported port>": <layout port>}}],
   "links": [{"ports": [["p1", 2], ["p2", 1]], "cut": [x1, y1, x2, y2], "line": [layer, v0, v1]}],
   "external": [{"port": 1, "piece": "p1", "piece_port": 1, "layout_port": 1}],
   "ground": [[layer, x, y]]}

Coordinates in µm in the cell; a link's line: the GDS layer of the cut conductor and its extent along the cut. A
piece's .simcfg gets "piece_of" (the set's .simcfg name) and "piece" (its name), and the frequency settings of the
set's .simcfg, so that all pieces have one frequency grid.
"""
import hashlib
import json
import os

import pya

from .boundary import INWARD, find_crossings
from .connectivity import check_ground
from .ports import collect_ports
from .export import EM_REGION
from .simcfg import write_simcfg
from .regions import Piece, cuts_of, find_cuts, piece_number, read_pieces, set_pieces, union_box

SET_VERSION = 1
FREQUENCY_KEYS = ("fstart", "fstop", "fstep", "fpoint", "fdump")    # one grid for all pieces: the join needs it


def _um(layout, box):
    d = box.to_dtype(layout.dbu)
    return [round(d.left, 6), round(d.bottom, 6), round(d.right, 6), round(d.top, 6)]


def _on_cut(shape_box, cut):
    """Whether a port shape (Box, dbu) is a zero-width line on the cut."""
    if cut.vertical:
        return shape_box.width() == 0 and shape_box.left == cut.edge.x1 and \
            cut.edge.y1 <= shape_box.bottom and shape_box.top <= cut.edge.y2
    return shape_box.height() == 0 and shape_box.bottom == cut.edge.y1 and \
        cut.edge.x1 <= shape_box.left and shape_box.right <= cut.edge.x2


def _port_boxes(port):
    return [shape.bbox().transformed(trans) for shape, trans, _ in port.items if not shape.is_text()]


def _port_cut(port, cuts):
    """The cut a port lies on (all its shapes), else None."""
    boxes = _port_boxes(port)
    for cut in cuts:
        if boxes and all(_on_cut(b, cut) for b in boxes):
            return cut
    return None


def piece_ports(layout, cell, stackup, piece, cuts):
    """{layer: Port} of one piece: the ports touching its box, without the other pieces' ports at its cuts. A port at
    a cut belongs to the piece named in it (OWNER_KEY); one without a name (drawn by hand) to the piece it points
    into; a via port on a cut stays in (export_problems reports it)."""
    mine = cuts_of(cuts, piece.name)
    out = {}
    for layer, port in collect_ports(layout, cell, piece.box, stackup=stackup).items():
        if port.owner is not None:
            if port.owner == piece.name:
                out[layer] = port
            continue
        cut = _port_cut(port, mine)
        if cut is None:
            out[layer] = port
        elif port.settings is None or port.settings.is_via or port.settings.direction == INWARD[cut.side_of(piece.name)]:
            out[layer] = port
    return out


def outer_ports(layout, cell, stackup, pieces, cuts):
    """{layer: Port} of the whole region without the ports at the cuts: the ports of the joined result."""
    out = {}
    for layer, port in collect_ports(layout, cell, union_box(pieces), stackup=stackup).items():
        if port.owner is None and _port_cut(port, cuts) is None:
            out[layer] = port
    return out


def split_state(layout, cell):
    """(pieces, cuts, problems) of the EM region boxes: problems from read_pieces, plus unnumbered boxes."""
    pieces, problems = read_pieces(layout, cell)
    if any(p.number is None for p in pieces):
        problems.append("some EM region boxes have no piece number yet (the panel numbers them)")
    return pieces, find_cuts(pieces), problems


def cut_problems(layout, cell, stackup, pieces, cuts, seeds=()):
    """(problems, warnings) of the cuts, as texts: a signal crossing a cut without its port in one of the pieces, a
    cut without ground, a via port on a cut, a cut port left behind by a moved box, a cut port without its partner;
    warnings: metal close to both sides of a cut (coupling across the cut is not in the joined result)."""
    problems, warnings = [], []
    names = {p.name for p in pieces}
    dbu = layout.dbu
    for piece in pieces:
        if piece.name is None:
            continue
        mine = cuts_of(cuts, piece.name)
        ports = piece_ports(layout, cell, stackup, piece, cuts)
        for port in ports.values():
            cut = _port_cut(port, mine)
            if port.owner is not None and cut is None:
                problems.append(f"port {port.number} of {port.owner} is no longer on a cut of {port.owner} (a box was "
                                "moved): delete it, then Create Proposed Ports")
            if cut is not None and port.settings is not None and port.settings.is_via:
                problems.append(f"port {port.number} is a via port on the cut {cut.a}|{cut.b}: a cut needs port wall "
                                "ports (delete it, then Create Proposed Ports)")
        if not mine:
            continue
        ground = check_ground(layout, cell, stackup, piece.box, seeds, ports)
        for c in find_crossings(layout, cell, stackup, piece.box, ground, piece.name, mine):
            if c.cut is None or c.ground or c.plane or c.port is not None:
                continue
            at = c.edge.bbox().center().to_dtype(dbu)
            if not c.wall_ground:
                problems.append(f"{c.name} crosses the cut {c.cut.a}|{c.cut.b} at {at}, but no ground metal reaches "
                                "the cut: mark the ground")
            else:
                problems.append(f"{c.name} crosses the cut {c.cut.a}|{c.cut.b} at {at} without a port in "
                                f"{piece.name}: Create Proposed Ports")
    for layer, port in collect_ports(layout, cell, union_box(pieces), stackup=stackup).items():
        if port.owner is not None and port.owner not in names:
            problems.append(f"port {port.number} belongs to {port.owner}, which is no longer there: delete it")
    links, unpaired = link_pairs(layout, cell, stackup, pieces, cuts)
    problems += [f"port {n} of {owner} at the cut has no partner in the other piece: Create Proposed Ports"
                 for owner, n in unpaired]
    warnings += coupling_warnings(layout, cell, stackup, pieces, cuts, seeds)
    return problems, warnings


def link_pairs(layout, cell, stackup, pieces, cuts):
    """([(cut, (piece, Port), (piece, Port))], unpaired [(piece, port number)]): the two ports of each line
    crossing a cut, matched by their shape."""
    by_piece = {p.name: piece_ports(layout, cell, stackup, p, cuts) for p in pieces if p.name}
    pairs, unpaired = [], []
    for cut in cuts:
        a_ports = [p for p in by_piece.get(cut.a, {}).values() if _port_cut(p, [cut]) is not None]
        b_ports = [p for p in by_piece.get(cut.b, {}).values() if _port_cut(p, [cut]) is not None]
        used = set()
        for pa in a_ports:
            key = sorted((b.left, b.bottom, b.right, b.top) for b in _port_boxes(pa))
            pb = next((p for p in b_ports if id(p) not in used and
                       sorted((b.left, b.bottom, b.right, b.top) for b in _port_boxes(p)) == key), None)
            if pb is None:
                unpaired.append((cut.a, pa.number))
                continue
            used.add(id(pb))
            pairs.append((cut, (cut.a, pa), (cut.b, pb)))
        unpaired += [(cut.b, p.number) for p in b_ports if id(p) not in used]
    return pairs, unpaired


def coupling_warnings(layout, cell, stackup, pieces, cuts, seeds=()):
    """Metal within D of a cut on both sides that does not cross it (D: span of the lines at the cut plus twice their
    distance to the ground there): it couples across the cut in the layout, but not in the joined result."""
    from .connectivity import layer_regions, wiring
    out = []
    metal_names = wiring(stackup)[0]
    for cut in cuts:
        a = next(p for p in pieces if p.name == cut.a)
        b = next(p for p in pieces if p.name == cut.b)
        box = a.box + b.box
        metals = layer_regions(layout, cell, metal_names, box)
        line = pya.Region(cut.edge.bbox().enlarged(1, 1))
        crossing = pya.Region()
        for region in metals.values():
            crossing += region.interacting(line)
        if crossing.is_empty():
            continue
        along = [(e.bbox().bottom, e.bbox().top) if cut.vertical else (e.bbox().left, e.bbox().right)
                 for e in (crossing & line).each()]
        span = max(hi for _, hi in along) - min(lo for lo, _ in along)
        d = max(span, 1)
        e = cut.edge
        if cut.vertical:
            band_a = pya.Box(e.x1 - d, e.y1, e.x1, e.y2)
            band_b = pya.Box(e.x1, e.y1, e.x1 + d, e.y2)
        else:
            band_a = pya.Box(e.x1, e.y1 - d, e.x2, e.y1)
            band_b = pya.Box(e.x1, e.y1, e.x2, e.y1 + d)
        near = {}
        for name, band in (("a", band_a), ("b", band_b)):
            found = pya.Region()
            for region in metals.values():
                found += region.interacting(pya.Region(band)).not_interacting(line)
            near[name] = found
        if not near["a"].is_empty() and not near["b"].is_empty():
            dist = d * layout.dbu
            out.append(f"metal lies close to both sides of the cut {cut.a}|{cut.b} (within {dist:g} µm) without "
                       "crossing it: coupling across the cut is not in the joined result; move the cut if it matters")
    return out


def _gds_text(path, origin):
    """The geometry of a written GDS as sorted text per layer, moved so that origin (Point, dbu) is 0,0 (piece-local):
    independent of shape order and of the file's timestamps."""
    ly = pya.Layout()
    ly.read(path)
    lines = []
    for top in ly.top_cells():
        for li in ly.layer_indexes():
            info = ly.get_info(li)
            items = []
            for shape in top.shapes(li).each():
                if shape.is_text():
                    continue
                if shape.is_box():
                    items.append("B" + str(shape.box.moved(-origin.x, -origin.y)))
                elif shape.polygon is not None:
                    items.append("P" + str(shape.polygon.moved(-origin.x, -origin.y)))
            if items:
                lines.append(f"{info.layer}/{info.datatype}:" + ";".join(sorted(items)))
    return "\n".join(sorted(lines))


def fingerprint(gds_path, port_list, stackup_path, origin):
    """SHA-256 of a piece: its geometry as written (piece-local), its ports and the stackup file's content."""
    h = hashlib.sha256()
    h.update(_gds_text(gds_path, origin).encode())
    h.update(json.dumps(port_list, sort_keys=True).encode())
    try:
        with open(stackup_path, "rb") as f:
            h.update(f.read())
    except OSError:
        h.update(str(stackup_path).encode())
    return h.hexdigest()


def _update_json(path, update):
    with open(path) as f:
        data = json.load(f)
    update(data)
    with open(path, "w") as f:
        json.dump(data, f, indent=4)
    return data


def export_pieces(layout, cell, stackup, gds_path, technology, seeds=(), layout_file=None):
    """Export All: the whole region (outer ports) to gds_path, and every piece into <export>_pieces/. Returns a dict:
    whole (export_em result), pieces ({name: export_em result}), set (the "pieces" section written into the
    .simcfg), problems (texts; nothing is written when there are any), warnings."""
    from .pipeline import export_em
    pieces, cuts, problems = split_state(layout, cell)
    problems = list(problems)
    if len(pieces) < 2:
        problems.append("Export All needs several EM region boxes")
    more, warnings = cut_problems(layout, cell, stackup, pieces, cuts, seeds) if not problems else ([], [])
    problems += more
    if problems:
        return {"problems": problems, "warnings": warnings}
    base = os.path.splitext(gds_path)[0]
    folder_name = os.path.basename(base) + "_pieces"
    folder = os.path.join(os.path.dirname(os.path.abspath(gds_path)), folder_name)
    os.makedirs(folder, exist_ok=True)
    whole_box = union_box(pieces).to_dtype(layout.dbu)
    outer = outer_ports(layout, cell, stackup, pieces, cuts)
    whole = export_em(layout, cell, stackup, gds_path, technology, box=whole_box, seeds=seeds,
                      layout_file=layout_file, ports=outer)
    with open(whole["simcfg"]) as f:
        main_values = json.load(f).get("saved_values", {})
    frequency = {k: main_values[k] for k in FREQUENCY_KEYS if k in main_values}
    stackup_path = stackup.path
    results, records = {}, []
    by_layer = {}                  # layout port layer -> (piece, exported number)
    for piece in sorted(pieces, key=lambda p: p.number):
        ports = piece_ports(layout, cell, stackup, piece, cuts)
        path = os.path.join(folder, piece.name + ".gds")
        r = export_em(layout, cell, stackup, path, technology, box=piece.dbox(layout.dbu), seeds=seeds,
                      layout_file=layout_file, ports=ports)
        results[piece.name] = r
        numbers = {row["layout_layer"]: row["port"] for row in _portmap(r["portmap"])["ports"]}
        for layer, number in numbers.items():
            by_layer.setdefault(layer, (piece.name, number))
        fp = fingerprint(path, r["port_list"], stackup_path, piece.box.p1)

        def update(data, piece=piece, fp=fp):
            data["saved_values"].update(frequency)
            # the model folder and name: in the pieces folder, named after the piece (setupEM's default would be
            # the GDS file's, the same here, but stated so that nothing depends on it)
            data["saved_values"]["sim_path"] = folder.replace("\\", "/")
            data["saved_values"]["model_basename"] = piece.name
            data["piece_of"] = os.path.basename(whole["simcfg"])
            data["piece"] = piece.name
            data["fingerprint"] = fp
        _update_json(r["simcfg"], update)
        records.append({"name": piece.name, "box": _um(layout, piece.box),
                        "gds": f"{folder_name}/{piece.name}.gds", "simcfg": f"{folder_name}/{piece.name}.simcfg",
                        "portmap": f"{folder_name}/{piece.name}_portmap.json", "fingerprint": fp,
                        "ports": {str(number): layer - 200 for layer, number in sorted(numbers.items())}})
    links = []
    pairs, _ = link_pairs(layout, cell, stackup, pieces, cuts)
    for cut, (a, pa), (b, pb) in pairs:
        box = _port_boxes(pa)[0]
        lo, hi = (box.bottom, box.top) if cut.vertical else (box.left, box.right)
        target = pa.settings.target if pa.settings else ""
        gds_layer = next((l.layer for l in stackup.layers if l.name == target), None)
        links.append({"ports": [[a, by_layer[pa.layer][1]], [b, by_layer[pb.layer][1]]],
                      "cut": _um(layout, cut.edge.bbox()),
                      "line": [gds_layer, round(lo * layout.dbu, 6), round(hi * layout.dbu, 6)], "layer": target})
    external = []
    for row in _portmap(whole["portmap"])["ports"]:
        if not row.get("in_simcfg"):
            continue
        piece, number = by_layer.get(row["layout_layer"], (None, None))
        external.append({"port": row["port"], "piece": piece, "piece_port": number, "layout_port": row["layout_port"]})
    section = {"version": SET_VERSION, "folder": folder_name, "cell": cell.name,
               "stackup": stackup_path.replace("\\", "/"), "pieces": records, "links": links, "external": external,
               "ground": [[layer, round(p.x * layout.dbu, 6), round(p.y * layout.dbu, 6)] for layer, p in seeds]}
    _update_json(whole["simcfg"], lambda data: data.__setitem__("pieces", section))
    # the whole region as one model, to check the joined result: in the pieces folder under its own name, so that
    # its result never takes the joined result's place (<export>_deembedded.sNp of <export>.simcfg)
    full = os.path.join(folder, "full.simcfg")
    write_simcfg(full, gds_path, stackup_path, whole["cellname"], ports=whole["port_list"], purpose=whole["purposes"],
                 port_walls=whole["port_walls"])

    def update_full(data):
        data["saved_values"].update(frequency)
        data["saved_values"]["sim_path"] = folder.replace("\\", "/")
        data["saved_values"]["model_basename"] = "full"
        data.pop("written_with", None)
        data["piece_of"] = os.path.basename(whole["simcfg"])
        data["piece"] = "full"
    _update_json(full, update_full)
    section["full"] = f"{folder_name}/full.simcfg"
    _update_json(whole["simcfg"], lambda data: data.__setitem__("pieces", section))
    return {"whole": whole, "pieces": results, "set": section, "problems": [], "warnings": warnings,
            "folder": folder}


def _portmap(path):
    with open(path) as f:
        return json.load(f)


def stale_piece_folders(folder, section):
    """Files in the pieces folder of pieces that are no longer in the set: [path] (p7.gds, p7.simcfg, ...) and model
    folders (palace_model/p7_data). Export All offers to remove them; until then a result there can still be reused."""
    current = {p["name"] for p in section.get("pieces", [])}
    out = []
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        stem = name.split(".")[0].split("_")[0]
        if piece_number(stem) is not None and stem not in current:
            out.append(os.path.join(folder, name))
    model = os.path.join(folder, "palace_model")
    if os.path.isdir(model):
        for name in sorted(os.listdir(model)):
            stem = name.split("_")[0]
            if piece_number(stem) is not None and stem not in current:
                out.append(os.path.join(model, name))
    return out


# ---------- Import Pieces ----------

def read_set(simcfg_path):
    """The import data of an export's .simcfg: {pieces: [(number, [x1, y1, x2, y2] µm)], ground: [[layer, x, y]],
    stackup, cell, links}. A .simcfg without a pieces section (one EM region box) gives one piece p1, the box being
    the layout extent recorded by the export (the GDS file's bounding box) when available."""
    with open(simcfg_path) as f:
        data = json.load(f)
    section = data.get("pieces")
    if isinstance(section, dict) and section.get("pieces"):
        return {"pieces": [(piece_number(p["name"]), p["box"]) for p in section["pieces"]],
                "ground": section.get("ground", []), "stackup": section.get("stackup"), "cell": section.get("cell"),
                "links": section.get("links", [])}
    values = data.get("saved_values", {})
    gds = values.get("GdsFile")
    box = None
    if gds and os.path.isfile(gds):
        ly = pya.Layout()
        ly.read(gds)
        top = ly.top_cells()[0] if ly.top_cells() else None
        if top is not None:
            b = top.dbbox()
            box = [b.left, b.bottom, b.right, b.top]
    if box is None:
        raise ValueError(f"{os.path.basename(simcfg_path)} has no pieces and its GDS file is not there to take the "
                         "region from")
    return {"pieces": [(1, box)], "ground": data.get("ground", []), "stackup": values.get("SubstrateFile"),
            "cell": values.get("cellname"), "links": []}


def apply_set(layout, cell, imported, single_unnumbered=True):
    """Draw the imported boxes on the EM region layer (replacing the boxes there) with their numbers. One box is
    drawn without a number (a plain EM region box). Returns the ground marks as [(layer, Point dbu)]."""
    dbu = layout.dbu
    boxes = imported["pieces"]
    pieces = [Piece(None if (single_unnumbered and len(boxes) == 1) else number,
                    pya.DBox(*box).to_itype(dbu)) for number, box in boxes]
    set_pieces(layout, cell, pieces)
    return [(int(l), pya.Point(round(x / dbu), round(y / dbu))) for l, x, y in imported.get("ground", [])]


def import_warnings(layout, cell, stackup, imported, devices=()):
    """Texts: what no longer fits after an import: a cut whose recorded line is not there (design moved or
    rerouted), a cut through a device (devices: pipeline.layout_devices), a box outside the cell, a ground mark on no
    metal, another cell name."""
    out = []
    dbu = layout.dbu
    if imported.get("cell") and imported["cell"] != cell.name:
        out.append(f"recorded for cell {imported['cell']}, imported into {cell.name}")
    extent = pya.Box()                      # the design, without the EM region boxes just drawn
    region_li = layout.find_layer(*EM_REGION)
    for li in layout.layer_indexes():
        if li != region_li:
            extent += cell.bbox(li)
    for number, box in imported["pieces"]:
        b = pya.DBox(*box).to_itype(dbu)
        if not extent.contains(b.p1) or not extent.contains(b.p2):
            out.append(f"p{number} reaches outside the cell's extent")
    for link in imported.get("links", []):
        layer, lo, hi = link["line"]
        cut = pya.DBox(*link["cut"]).to_itype(dbu)
        vertical = cut.width() == 0
        li = layout.find_layer(layer, 0) if layer is not None else None
        probe_lo, probe_hi = round(lo / dbu), round(hi / dbu)
        # the line is still there if the metal of its layer meets the cut over the same extent (not just some metal
        # there: a shifted ground strip would cover the old position too)
        found = False
        if li is not None:
            line = pya.Region(cut.enlarged(1, 1))
            on_cut = pya.Region(cell.begin_shapes_rec_touching(li, cut.enlarged(1, 1))) & line
            on_cut.merge()
            tol = max(2, round(0.01 / dbu))
            for part in on_cut.each():
                pb = part.bbox()
                a0, a1 = (pb.bottom, pb.top) if vertical else (pb.left, pb.right)
                if abs(a0 - probe_lo) <= tol and abs(a1 - probe_hi) <= tol:
                    found = True
                    break
        if not found:
            a, b = link["ports"][0][0], link["ports"][1][0]
            out.append(f"the cut {a}|{b} no longer crosses the {link.get('layer') or layer} line it crossed at "
                       f"{lo:g}..{hi:g} µm: the design moved or was rerouted")
        for d in devices:
            if d.bbox.overlaps(cut.enlarged(1, 1)):
                a, b = link["ports"][0][0], link["ports"][1][0]
                out.append(f"the cut {a}|{b} runs through device {d.pcell} {d.id.split('@')[0]}")
    for layer, x, y in imported.get("ground", []):
        li = layout.find_layer(int(layer), 0)
        p = pya.Point(round(x / dbu), round(y / dbu))
        hit = False
        if li is not None:
            it = cell.begin_shapes_rec_touching(li, pya.Box(p, p))
            while not it.at_end() and not hit:
                shape = it.shape()
                hit = not shape.is_text() and shape.polygon is not None and shape.polygon.transformed(it.trans()).inside(p)
                it.next()
        if not hit:
            name = next((l.name for l in stackup.layers if l.layer == int(layer)), str(layer)) if stackup else str(layer)
            out.append(f"the ground mark on {name} at ({x:g}, {y:g}) hits no metal")
    return out
