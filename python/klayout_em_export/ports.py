"""Port settings stored as a user property on the port shape, and collected into setupEM's port list.

A port is a shape on layer 201..299 (datatype 0), port number = layer - 200. Its settings are one string property
with an integer key, because GDS keeps only integer keys:
  port:dir=-Z;from=Metal3;to=TopMetal2;z0=50;v=1     via port (Z, -Z)
  port:dir=X;target=Metal5;z0=50;v=1                 in-plane port (X, Y, -X, -Y)
Short on purpose: some GDS tools cut property values after 126 characters.
"""
import pya

from .export import PORT_LAYERS
from .simcfg import port_entry

PROP_KEY = 200
PREFIX = "port:"
DIRECTIONS = ("X", "Y", "Z", "-X", "-Y", "-Z")


class PortSettings:
    def __init__(self, direction="Z", from_layer="", to_layer="", target="", z0=50.0, voltage=1.0):
        self.direction = direction
        self.from_layer = from_layer
        self.to_layer = to_layer
        self.target = target
        self.z0 = float(z0)
        self.voltage = float(voltage)

    @property
    def is_via(self):
        return "Z" in self.direction.upper()

    def encode(self):
        layers = f"from={self.from_layer};to={self.to_layer}" if self.is_via else f"target={self.target}"
        return f"{PREFIX}dir={self.direction};{layers};z0={self.z0:g};v={self.voltage:g}"

    @classmethod
    def decode(cls, text):
        """PortSettings from a property value, or None if it is not one of ours."""
        if not isinstance(text, str) or not text.startswith(PREFIX):
            return None
        values = dict(item.split("=", 1) for item in text[len(PREFIX):].split(";") if "=" in item)
        try:
            return cls(values.get("dir", ""), values.get("from", ""), values.get("to", ""), values.get("target", ""),
                       values.get("z0", 50), values.get("v", 1))
        except ValueError:
            return None

    def problems(self, metal_names):
        out = []
        if self.direction not in DIRECTIONS:
            out.append(f"direction '{self.direction}' is not one of {', '.join(DIRECTIONS)}")
        names = [self.from_layer, self.to_layer] if self.is_via else [self.target]
        for name in names:
            if name not in metal_names:
                out.append(f"layer '{name}' is not a metal of the stackup" if name else "a layer is not set")
        if self.is_via and self.from_layer and self.from_layer == self.to_layer:
            out.append("from and to are the same layer")
        return out

    def __str__(self):
        layers = f"{self.from_layer} -> {self.to_layer}" if self.is_via else f"on {self.target}"
        return f"{self.direction:>2} {layers}, Z0 {self.z0:g} Ohm" + ("" if self.voltage else ", not excited")


def settings_of(shape):
    return PortSettings.decode(shape.property(PROP_KEY))


class Port:
    def __init__(self, layer):
        self.layer = layer
        self.settings = None
        self.shapes = 0
        self.conflict = False       # shapes on this layer carry different settings

    @property
    def number(self):
        return self.layer - 200


def collect_ports(layout, cell, box=None, datatype=0):
    """Ports drawn in cell (recursively), optionally only those touching box (Box in dbu): {layer: Port}."""
    ports = {}
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer not in PORT_LAYERS or info.datatype != datatype:
            continue
        it = cell.begin_shapes_rec(li) if box is None else cell.begin_shapes_rec_overlapping(li, box)
        while not it.at_end():
            shape = it.shape()
            if not shape.is_text():
                port = ports.setdefault(info.layer, Port(info.layer))
                port.shapes += 1
                settings = settings_of(shape)
                if settings is not None:
                    if port.settings is not None and port.settings.encode() != settings.encode():
                        port.conflict = True
                    port.settings = port.settings or settings
            it.next()
    return ports


def check_ports(ports, metal_names):
    """Problems per port, as text lines (empty when all ports are complete)."""
    lines = []
    for layer in sorted(ports):
        port = ports[layer]
        if port.settings is None:
            lines.append(f"port {port.number} (layer {layer}): no port settings")
            continue
        if port.conflict:
            lines.append(f"port {port.number} (layer {layer}): shapes with different settings, the first is used")
        lines += [f"port {port.number} (layer {layer}): {p}" for p in port.settings.problems(metal_names)]
    return lines


def simcfg_ports(ports):
    """setupEM port list. A port without settings is still listed, so setupEM shows it for completion."""
    out = []
    for layer in sorted(ports):
        s = ports[layer].settings or PortSettings(direction="", z0=50.0, voltage=1.0)
        out.append(port_entry(ports[layer].number, layer, s.direction, target_layername=s.target or None,
                              from_layername=s.from_layer or None, to_layername=s.to_layer or None,
                              port_Z0=s.z0, voltage=s.voltage))
    return out
