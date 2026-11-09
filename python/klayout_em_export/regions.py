"""Several EM region boxes: the pieces of a split region. Each piece is exported and simulated as its own model, and
setupEM joins the results into one .sNp of the whole region (pipeline.export_pieces, setupEM join_pieces).

A piece is a box on the EM region layer (800/0) in the cell. Its name, p1, p2, ..., is a user property on the box
(PIECE_KEY), so moving or resizing a box, or adding one, renumbers nothing: the model folders stay where they are,
and setupEM can reuse the result of a piece that has not changed. Boxes without a name get the lowest free numbers
in reading order (top to bottom, left to right).

Two pieces whose boxes share an edge segment meet at a cut. A signal line crossing a cut gets one port wall port in
each piece, pointing into it, with the piece's name in OWNER_KEY: the reference planes of both ports lie on the cut
(gds2palace's port wall calibration), so the two results join there directly.

With one box nothing here applies: the region works as before, and no number is written.
"""
import pya

from .export import EM_REGION

PIECE_KEY = 203     # property on a box on the EM region layer: its piece name, "p1", "p2", ...
OWNER_KEY = 204     # property on a port made at a cut between two pieces: the name of the piece it belongs to


def piece_name(number):
    return f"p{number}"


def piece_number(name):
    """12 for 'p12', else None."""
    if isinstance(name, str) and len(name) > 1 and name[0] == "p" and name[1:].isdigit():
        return int(name[1:])
    return None


class Piece:
    def __init__(self, number, box):
        self.number = number        # int, or None for a box not numbered yet
        self.box = box              # pya.Box (dbu)

    @property
    def name(self):
        return piece_name(self.number) if self.number is not None else None

    def dbox(self, dbu):
        return self.box.to_dtype(dbu)

    def __repr__(self):
        return f"Piece({self.name}, {self.box})"


class Cut:
    """The shared edge segment of two pieces: a is left of (or below) b."""

    def __init__(self, a, b, edge, vertical):
        self.a = a                  # piece name, left or lower
        self.b = b                  # piece name, right or upper
        self.edge = edge            # pya.Edge (dbu), from low to high coordinate
        self.vertical = vertical    # True: a vertical cut (x = const), a's right side, b's left side

    def side_of(self, name):
        """The side of piece name that lies on the cut: right / left / top / bottom."""
        if self.vertical:
            return "right" if name == self.a else "left"
        return "top" if name == self.a else "bottom"

    def other(self, name):
        return self.b if name == self.a else self.a

    def contains(self, edge):
        """Whether edge (pya.Edge, dbu) lies on the cut segment."""
        return _on_segment(edge, self.edge)

    def __repr__(self):
        return f"Cut({self.a}|{self.b}, {self.edge})"


def _on_segment(edge, segment):
    """Whether edge lies on segment (both axis-parallel, dbu)."""
    if segment.x1 == segment.x2:
        lo, hi = min(segment.y1, segment.y2), max(segment.y1, segment.y2)
        return edge.x1 == edge.x2 == segment.x1 and lo <= min(edge.y1, edge.y2) and max(edge.y1, edge.y2) <= hi
    lo, hi = min(segment.x1, segment.x2), max(segment.x1, segment.x2)
    return edge.y1 == edge.y2 == segment.y1 and lo <= min(edge.x1, edge.x2) and max(edge.x1, edge.x2) <= hi


def _reading_order(box):
    return (-box.top, box.left, -box.bottom, box.right)


def _layer(layout, create=False):
    if create:
        return layout.layer(*EM_REGION)
    return layout.find_layer(*EM_REGION)


def region_shapes(layout, cell):
    """[(Box or None, number or None)] of the shapes on the EM region layer in cell itself (not in subcells): Box for
    a rectangle, None for any other shape; the number from its PIECE_KEY property."""
    li = _layer(layout)
    if li is None:
        return []
    out = []
    for shape in cell.shapes(li).each():
        if shape.is_text():
            continue
        polygon = shape.polygon
        box = polygon.bbox() if polygon is not None and polygon.is_box() else None
        out.append((box, piece_number(shape.property(PIECE_KEY))))
    return out


def read_pieces(layout, cell):
    """(pieces, problems): the boxes on the EM region layer as Pieces in reading order, and what is wrong with them
    (texts). A number used twice keeps it on the first box in reading order; the other boxes come back unnumbered
    (number_pieces gives them one)."""
    problems = []
    found = []
    for box, number in region_shapes(layout, cell):
        if box is None:
            problems.append("a shape on the EM region layer is not a rectangle (only boxes are pieces)")
            continue
        found.append(Piece(number, box))
    found.sort(key=lambda p: _reading_order(p.box))
    seen = set()
    for piece in found:
        if piece.number is not None:
            if piece.number in seen:
                piece.number = None
            else:
                seen.add(piece.number)
    for i, a in enumerate(found):
        for b in found[i + 1:]:
            overlap = a.box & b.box
            if not overlap.empty() and overlap.width() > 0 and overlap.height() > 0:
                problems.append(f"the EM region boxes {a.name or '(new)'} and {b.name or '(new)'} overlap: pieces "
                                "must only touch")
    return found, problems


def lowest_free(used, count=1):
    """The count lowest numbers from 1 that are not in used."""
    out, n = [], 1
    while len(out) < count:
        if n not in used:
            out.append(n)
        n += 1
    return out


def needs_numbers(layout, cell):
    """Whether there are several boxes and some have no number (or share one)."""
    pieces, _ = read_pieces(layout, cell)
    return len(pieces) > 1 and any(p.number is None for p in pieces)


def number_pieces(layout, cell):
    """Give every box on the EM region layer without a number the lowest free one, in reading order. Only with more
    than one box. Rewrites the layer's shapes once (all of them, with their properties): changing a shape's
    properties in place twice crashes KLayout 0.29.4. Returns the names given."""
    pieces, _ = read_pieces(layout, cell)
    if len(pieces) < 2 or all(p.number is not None for p in pieces):
        return []
    free = lowest_free({p.number for p in pieces if p.number is not None},
                       sum(1 for p in pieces if p.number is None))
    given = []
    for piece in pieces:
        if piece.number is None:
            piece.number = free.pop(0)
            given.append(piece.name)
    _rewrite(layout, cell, pieces)
    return given


def _rewrite(layout, cell, pieces):
    """Replace the boxes on the EM region layer by pieces (with their numbers); other shapes there are kept."""
    li = _layer(layout, create=True)
    shapes = cell.shapes(li)
    keep = []
    for shape in shapes.each():
        polygon = None if shape.is_text() else shape.polygon
        if shape.is_text() or polygon is None or not polygon.is_box():
            keep.append((shape.text if shape.is_text() else polygon, shape.prop_id))
    shapes.clear()
    for obj, prop_id in keep:
        shapes.insert(obj, prop_id)
    for piece in pieces:
        if piece.number is None:
            shapes.insert(piece.box)
        else:
            shapes.insert(piece.box, layout.properties_id([[PIECE_KEY, piece.name]]))


def set_pieces(layout, cell, pieces):
    """Replace all boxes on the EM region layer by pieces ([Piece]), e.g. from an import."""
    _rewrite(layout, cell, pieces)


def split_piece(layout, cell, point, vertical=True):
    """Split the box containing point (Point, dbu) at point: vertical=True along x = point.x (a left and a right
    half), else along y. The left (or lower) half keeps the number, the other half gets the lowest free one; a box
    without a number (the only box, before the first split) becomes p1 and p2. Returns (left/lower, right/upper)
    Pieces, or None when no box contains the point well inside."""
    pieces, _ = read_pieces(layout, cell)
    hit = next((p for p in pieces if p.box.left < point.x < p.box.right and p.box.bottom < point.y < p.box.top), None)
    if hit is None:
        return None
    b = hit.box
    if vertical:
        first, second = pya.Box(b.left, b.bottom, point.x, b.top), pya.Box(point.x, b.bottom, b.right, b.top)
    else:
        first, second = pya.Box(b.left, b.bottom, b.right, point.y), pya.Box(b.left, point.y, b.right, b.top)
    used = {p.number for p in pieces if p.number is not None}
    if hit.number is None:
        hit.number = lowest_free(used)[0]
        used.add(hit.number)
    low, high = Piece(hit.number, first), Piece(lowest_free(used)[0], second)
    others = [p for p in pieces if p is not hit]
    # number the other unnumbered boxes too: after a split every box has a name
    free = lowest_free(used | {high.number}, sum(1 for p in others if p.number is None))
    for p in others:
        if p.number is None:
            p.number = free.pop(0)
    _rewrite(layout, cell, others + [low, high])
    return low, high


def find_cuts(pieces):
    """[Cut] between the pieces whose boxes share an edge segment of positive length."""
    cuts = []
    named = [p for p in pieces if p.number is not None]
    for i, a in enumerate(named):
        for b in named[i + 1:]:
            for left, right in ((a, b), (b, a)):
                if left.box.right == right.box.left:
                    lo, hi = max(left.box.bottom, right.box.bottom), min(left.box.top, right.box.top)
                    if hi > lo:
                        x = left.box.right
                        cuts.append(Cut(left.name, right.name, pya.Edge(x, lo, x, hi), True))
                if left.box.top == right.box.bottom:
                    lo, hi = max(left.box.left, right.box.left), min(left.box.right, right.box.right)
                    if hi > lo:
                        y = left.box.top
                        cuts.append(Cut(left.name, right.name, pya.Edge(lo, y, hi, y), False))
    return cuts


def cuts_of(cuts, name):
    return [c for c in cuts if name in (c.a, c.b)]


def piece_at(pieces, point):
    """The piece whose box contains point (Point, dbu), else None."""
    return next((p for p in pieces if p.box.contains(point)), None)


def union_box(pieces):
    """Bounding box (Box, dbu) of all pieces."""
    box = pya.Box()
    for p in pieces:
        box += p.box
    return box


def is_split(layout, cell):
    """More than one box on the EM region layer."""
    return len([b for b, _ in region_shapes(layout, cell) if b is not None]) > 1
