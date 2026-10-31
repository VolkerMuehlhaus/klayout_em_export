"""Read a gds2palace stackup XML: which GDS layers matter for EM, and the metal names.

Plain XML, no gds2palace import: KLayout's Python has no gds2palace. Only the parts the export needs are read.
"""
import xml.etree.ElementTree as ET


class StackupError(Exception):
    pass


def _layer_number(element, path):
    value = element.get("Layer")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise StackupError(f"{path}: Layer=\"{value}\" of {element.get('Name')} is not a plain number "
                           "(expressions in layer numbers are not supported)") from None


def _number(value):
    """float of a plain number attribute; None for a missing value or a "=expression" (variables)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class StackupLayer:
    def __init__(self, name, kind, layer, material, element=None):
        self.name = name
        self.kind = kind            # conductor, via, sheet or dielectric
        self.layer = layer
        self.material = material
        get = element.get if element is not None else (lambda key: None)
        self.reference, self.reference_edge = get("Reference"), get("ReferenceEdge") or "Top"
        self.zmin_attr, self.zmax_attr = get("Zmin"), get("Zmax")

    @property
    def is_metal(self):
        return self.kind in ("conductor", "sheet")

    def __repr__(self):
        return f"StackupLayer({self.name!r}, {self.kind!r}, {self.layer})"


class Stackup:
    def __init__(self, path):
        self.path = path
        root = ET.parse(path).getroot()
        self.layers = [StackupLayer(e.get("Name"), e.get("Type"), _layer_number(e, path), e.get("Material"), e)
                       for e in root.iter("Layer")]
        # dielectric name -> (Reference, ReferenceEdge, Thickness), for the z positions of the layers
        self.dielectrics = {e.get("Name"): (e.get("Reference"), e.get("ReferenceEdge") or "Top", e.get("Thickness"))
                            for e in root.iter("Dielectric")}
        # derived layer number -> (name, operation, operand layer numbers)
        self.derived = {_layer_number(e, path): (e.get("Name"), e.get("Operation"),
                                                 [_layer_number(o, path) for o in e.iter("Operand")])
                        for e in root.iter("DerivedLayer")}
        # dielectrics with a Boundary= layer: their outline is drawn in the GDS
        self.boundary_layers = sorted({int(e.get("Boundary")) for e in root.iter("Dielectric")
                                       if (e.get("Boundary") or "").lstrip("-").isdigit()})
        # <Substrate Offset="..."> (schema 2.0): shifts every Layer that has no Reference. None: given by a variable,
        # then those layers compare only among themselves (z_range anchor "offset")
        offsets = [e.get("Offset") for e in root.iter("Substrate")]
        offset = 0.0 if not offsets else _number(offsets[-1])
        self.offset = offset if offset is None or offset > 0 else 0.0     # as gds2palace: only a positive offset counts

    def layer(self, name):
        return next((l for l in self.layers if l.name == name), None)

    def metal_names(self):
        """Conductor and sheet layers, top to bottom as in the file: the choices for port layers."""
        return [l.name for l in self.layers if l.is_metal]

    def _edge(self, name, edge, seen=()):
        """z of the Top or Bottom edge of a layer or dielectric, as (anchor, offset), or None if unknown.
        A thickness given by a variable starts a new anchor, so z values compare only within one anchor; the
        metal stack hangs off one anchor (e.g. the bottom of SiO2) and needs no variable."""
        if name in seen:
            raise StackupError(f"{self.path}: Reference loop at {name}")
        layer = self.layer(name)
        if layer is not None:
            z = self.z_range(layer, seen + (name,))
            return None if z is None else (z[0], z[2] if edge == "Top" else z[1])
        if name in self.dielectrics:
            reference, reference_edge, thickness = self.dielectrics[name]
            bottom = ("bottom", 0.0) if not reference else self._edge(reference, reference_edge, seen + (name,))
            if edge == "Bottom" or bottom is None:
                return bottom
            t = _number(thickness)
            return (bottom[0], bottom[1] + t) if t is not None else (f"{name}.top", 0.0)
        return None

    def z_range(self, layer, seen=()):
        """(anchor, zmin, zmax) of a stackup layer, or None if its position cannot be resolved.
        With a Reference, Zmin/Zmax are offsets from that edge; without, they are absolute, plus the stackup's
        <Substrate Offset>."""
        zmin, zmax = _number(layer.zmin_attr), _number(layer.zmax_attr)
        if zmin is None or zmax is None:
            return None
        if not layer.reference:
            # an offset given by a variable shifts all these layers alike: an anchor of their own, like a thickness
            return ("offset", zmin, zmax) if self.offset is None else ("bottom", zmin + self.offset, zmax + self.offset)
        base = self._edge(layer.reference, layer.reference_edge, seen)
        return None if base is None else (base[0], base[1] + zmin, base[1] + zmax)

    def unresolved(self):
        """Names of the metals and vias drawn in the GDS whose z position cannot be resolved (a position given by
        a variable or expression, or an unknown Reference). Such a layer is left out of everything that needs
        heights: via connections, ground and nets, port direction. Dielectric layers (e.g. LBE) do not count."""
        return [l.name for l in self.layers
                if l.kind in ("conductor", "sheet", "via") and l.layer not in self.derived and self.z_range(l) is None]

    def is_above(self, upper, lower):
        """True if the layer named upper lies above the layer named lower (by their bottom), False if below, None
        if their positions cannot be compared."""
        a, b = self.layer(upper), self.layer(lower)
        za, zb = (self.z_range(a) if a else None), (self.z_range(b) if b else None)
        if za is None or zb is None or za[0] != zb[0]:
            return None
        return za[1] > zb[1]

    def via_neighbors(self, delta=1e-5):
        """{via layer number: ([metals directly below], [metals directly above])} as StackupLayers, for the vias
        drawn in the GDS that have drawn metals on both sides (z within delta, as gds2palace). Lists, because
        a via can sit on more than one layer (Cont: on Activ and on the REF_FOR_TRANSISTOR sheet)."""
        metals = [(l, self.z_range(l)) for l in self.layers if l.is_metal and l.layer not in self.derived]
        out = {}
        for via in (l for l in self.layers if l.kind == "via" and l.layer not in self.derived):
            z = self.z_range(via)
            if z is None:
                continue
            below = [m for m, mz in metals if mz and mz[0] == z[0] and abs(mz[2] - z[1]) < delta]
            above = [m for m, mz in metals if mz and mz[0] == z[0] and abs(mz[1] - z[2]) < delta]
            if below and above:
                out[via.layer] = (below, above)
        return out

    def gds_layers(self):
        """GDS layer numbers the EM model reads: stackup layers and dielectric boundaries, with derived layers
        replaced by their (recursive) source layers, since derived layers are computed by gds2palace."""
        needed = set()

        def add(number, seen=()):
            if number in self.derived:
                if number in seen:
                    raise StackupError(f"{self.path}: derived layer {number} refers to itself")
                for operand in self.derived[number][2]:
                    add(operand, seen + (number,))
            else:
                needed.add(number)

        for l in self.layers:
            add(l.layer)
        for number in self.boundary_layers:
            add(number)
        return sorted(needed)
