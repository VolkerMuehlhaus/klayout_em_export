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


class StackupLayer:
    def __init__(self, name, kind, layer, material):
        self.name = name
        self.kind = kind            # conductor, via, sheet or dielectric
        self.layer = layer
        self.material = material

    @property
    def is_metal(self):
        return self.kind in ("conductor", "sheet")

    def __repr__(self):
        return f"StackupLayer({self.name!r}, {self.kind!r}, {self.layer})"


class Stackup:
    def __init__(self, path):
        self.path = path
        root = ET.parse(path).getroot()
        self.layers = [StackupLayer(e.get("Name"), e.get("Type"), _layer_number(e, path), e.get("Material"))
                       for e in root.iter("Layer")]
        # derived layer number -> (name, operation, operand layer numbers)
        self.derived = {_layer_number(e, path): (e.get("Name"), e.get("Operation"),
                                                 [_layer_number(o, path) for o in e.iter("Operand")])
                        for e in root.iter("DerivedLayer")}
        # dielectrics with a Boundary= layer: their outline is drawn in the GDS
        self.boundary_layers = sorted({int(e.get("Boundary")) for e in root.iter("Dielectric")
                                       if (e.get("Boundary") or "").lstrip("-").isdigit()})

    def layer(self, name):
        return next((l for l in self.layers if l.name == name), None)

    def metal_names(self):
        """Conductor and sheet layers, top to bottom as in the file: the choices for port layers."""
        return [l.name for l in self.layers if l.is_metal]

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
