"""Port settings stored as a user property on the port shape, and collected into setupEM's port list.

A port is a shape on layer 201..299 (datatype 0), port number = layer - 200. Its settings are one string property
with an integer key, because GDS keeps only integer keys:
  port:dir=-Z;from=Metal3;to=TopMetal2;z0=50;v=1     via port (Z, -Z)
  port:dir=X;target=Metal5;z0=50;v=1                 in-plane port (X, Y, -X, -Y)
Short on purpose: some GDS tools cut property values after 126 characters.
"""
import pya

from .export import port_layer_numbers
from .locate import drawn_metals, metals_at
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

    def layer_names(self):
        return [self.from_layer, self.to_layer] if self.is_via else [self.target]

    def problems(self, metal_names):
        out = []
        if self.direction not in DIRECTIONS:
            out.append(f"direction '{self.direction}' is not one of {', '.join(DIRECTIONS)}")
        for name in self.layer_names():
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
        self.available = None       # stackup metals drawn at every shape of the port (set), None if not checked
        self.items = []             # (shape, trans into the cell, instance path or None) per shape
        self.dbu = 0.001            # of the layout, for messages

    @property
    def number(self):
        return self.layer - 200


def collect_ports(layout, cell, box=None, datatype=0, stackup=None):
    """Ports drawn in cell (recursively), optionally only those touching box (Box in dbu): {layer: Port}.
    With a stackup, port.available is set to the metals drawn at the port, and the stackup's own layers in the
    port layer range (SUBGND, ...) are not ports."""
    items = []
    port_layers = port_layer_numbers(stackup)
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        if info.layer not in port_layers or info.datatype != datatype:
            continue
        it = cell.begin_shapes_rec(li) if box is None else cell.begin_shapes_rec_touching(li, box)
        while not it.at_end():
            items.append(((info.layer, info.datatype), it.shape(), it.trans(), it.path()))
            it.next()
    return ports_of(layout, cell, items, datatype, stackup)


def ports_of(layout, cell, items, datatype=0, stackup=None):
    """{layer: Port} from [((layer, datatype), shape, trans into cell[, instance path])], e.g. a Selection's
    ports. With a stackup, its own layers in the port layer range (SUBGND, ...) are left out."""
    ports = {}
    port_layers = port_layer_numbers(stackup)
    for item in items:
        (layer, dt), shape, trans = item[:3]
        if shape.is_text() or dt != datatype or layer not in port_layers:
            continue
        port = ports.setdefault(layer, Port(layer))
        port.dbu = layout.dbu
        port.shapes += 1
        port.items.append((shape, trans, item[3] if len(item) > 3 else None))
        settings = settings_of(shape)
        if settings is not None:
            if port.settings is not None and port.settings.encode() != settings.encode():
                port.conflict = True
            port.settings = port.settings or settings
        if stackup is not None:
            here = set(metals_at(layout, cell, stackup, shape.bbox().transformed(trans)))
            port.available = here if port.available is None else port.available & here
    return ports


def shape_problems(port):
    """Problems of the port's shapes. Several shapes on one port layer are the elements of one port, in parallel
    (Palace multielement lumped port; needs gds2palace with multielement ports, branch multi-element-ports)."""
    boxes = [shape.bbox().transformed(trans) for shape, trans, _ in port.items if not shape.is_text()]
    out = []
    for b in boxes:
        if b.width() == 0 and b.height() == 0:
            out.append(f"point-size shape at {b.p1.to_dtype(port.dbu)}: delete it")
    s = port.settings
    if s is not None and not s.is_via and any(b.width() == 0 or b.height() == 0 for b in boxes):
        out.append("an in-plane port needs a box with area that bridges the gap")
    return out


def port_problems(port, stackup):
    """Problems of one port, as short texts (empty when it is complete)."""
    if port.settings is None:
        return ["no port settings"] + shape_problems(port)
    out = ["shapes with different settings, the first is used"] if port.conflict else []
    out += shape_problems(port)
    out += port.settings.problems(stackup.metal_names())
    if port.available is not None:
        drawn = {name for name, _ in drawn_metals(stackup)}
        out += [f"{name} is not drawn at the port" for name in port.settings.layer_names()
                if name in drawn and name not in port.available]
    return out


def check_ports(ports, stackup):
    """Problems of all ports, as text lines (empty when all ports are complete)."""
    return [f"port {ports[layer].number} (layer {layer}): {problem}"
            for layer in sorted(ports) for problem in port_problems(ports[layer], stackup)]


def is_complete(port):
    """Settings with a valid direction and its layers set. setupEM (via gds2palace's simulation_port) exits
    when it loads a port without them, so only complete ports go into the .simcfg."""
    s = port.settings
    return s is not None and s.direction in DIRECTIONS and all(s.layer_names())


def export_numbering(ports, stackup=None):
    """{layout port layer: exported port layer}: the complete ports numbered 1..N in layout order, then the
    incomplete ones. Port numbers without gaps, because the .snp conversion after Palace (combine_extend_snp)
    takes the highest port number as the port count and fills missing ports with |S| = 1."""
    order = ([l for l in sorted(ports) if is_complete(ports[l])] +
             [l for l in sorted(ports) if not is_complete(ports[l])])
    targets = port_layer_numbers(stackup)          # with a stackup: skips its layers (SUBGND on 210, ...)
    if len(order) > len(targets):
        raise ValueError(f"{len(order)} ports, but only {len(targets)} port layers (201..299)")
    return {layer: targets[i] for i, layer in enumerate(order)}


def export_directions(ports, nets, stackup):
    """{port layer: direction} for the via ports whose signal layer is known (nets from connectivity.port_nets):
    'Z' if the signal metal is the upper end, '-Z' if it is the lower one. gds2palace hands 'Z' to Palace as +z, so
    all 'Z' via ports have the same orientation and '-Z' reverses one; with these directions every via port has its
    signal metal on the same end, as a circuit wrapper connecting the EM model expects."""
    out = {}
    for layer, port in ports.items():
        s = port.settings
        signal = (nets or {}).get(layer, (None, None, None))[2]
        if s is None or not s.is_via or signal not in (s.from_layer, s.to_layer):
            continue
        other = s.to_layer if signal == s.from_layer else s.from_layer
        above = stackup.is_above(signal, other)
        if above is not None:
            out[layer] = "Z" if above else "-Z"
    return out


def export_port_numbers(numbering):
    """{layout port layer: exported port number}: 1..N in the order of the exported layers (numbering from
    export_numbering). Equal to layer - 200, unless a stackup layer in the port layer range (SUBGND on 210, ...) is
    skipped: the port numbers stay without gaps, and gds2palace takes the port number and its layer separately."""
    return {old: i + 1 for i, (old, new) in enumerate(sorted(numbering.items(), key=lambda item: item[1]))}


def simcfg_ports(ports, numbering=None, directions=None):
    """setupEM port list of the complete ports (see is_complete), numbered by numbering (export_numbering) if
    given, else by their layout numbers; directions (export_directions) replace the ports' own."""
    out = []
    numbers = export_port_numbers(numbering) if numbering else {}
    for layer in sorted(ports, key=lambda l: (numbering or {}).get(l, l)):
        if not is_complete(ports[layer]):
            continue
        s = ports[layer].settings
        new_layer = (numbering or {}).get(layer, layer)
        direction = (directions or {}).get(layer, s.direction)
        out.append(port_entry(numbers.get(layer, new_layer - 200), new_layer, direction,
                              target_layername=s.target or None,
                              from_layername=s.from_layer or None, to_layername=s.to_layer or None,
                              port_Z0=s.z0, voltage=s.voltage))
    return out


DEVICE_KEY = 202                    # set by devices.replace on the ports it makes: "device:<id>:<terminal>"


def device_of(port):
    """(device id, terminal) of a port made by devices.replace, else None."""
    for shape, _, _ in port.items:
        value = shape.property(DEVICE_KEY)
        if isinstance(value, str) and value.count(":") == 2:
            return tuple(value.split(":")[1:])
    return None


def port_map(ports, numbering, devices=(), nets=None, directions=None, technology=None):
    """The port map file's content: per exported port its layout number and layer, and whether it is simulated;
    with devices (devices.Device), also the replaced devices' pcell and parameters, with nets
    (connectivity.port_nets) the net and layer of each port's signal end, for a circuit wrapper, and with
    directions (export_directions) the direction exported for the ports it covers."""
    rows = []
    numbers = export_port_numbers(numbering)
    for layer, new_layer in sorted(numbering.items(), key=lambda item: item[1]):
        port = ports[layer]
        row = {"port": numbers[layer], "layer": new_layer, "layout_port": port.number, "layout_layer": layer,
               "in_simcfg": is_complete(port), "settings": str(port.settings) if port.settings else None}
        if port.settings and layer in (directions or {}):
            row["direction"] = directions[layer]
        device = device_of(port)
        if device is not None:
            row["device"], row["terminal"] = device
        if nets and layer in nets:
            row["net"], row["ground_net"], row["signal_layer"] = nets[layer]
        rows.append(row)
    out = {"note": "port = number in the .simcfg and .snp, layer = its layer in the exported GDS; layout_port = "
                    "number in the layout (layer - 200). Ports not in the .simcfg are exported as shapes only. "
                    "device/terminal: the port replaces that terminal of a PDK device (to be connected to the "
                    "device model). direction: as exported, chosen so that every via port has its signal metal "
                    "(signal_layer) on the same end.",
            "ports": rows,
            "devices": {d.id: {"pcell": d.pcell, "params": {k: str(v) for k, v in d.params.items()}}
                        for d in devices if d.replaced}}
    if technology is not None:
        out["technology"] = technology      # the circuit wrapper's device models (tech/<technology>_circuit.py)
    return out
