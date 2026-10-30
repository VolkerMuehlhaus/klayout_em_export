"""Replace PDK devices by ports: the device model is simulated in the circuit simulator, the EM model gets ports
at the device's terminals instead (reference plane at the pcell's pins).

Supported: SG13_dev pcells with named pins, i.e. pin shapes (datatype 2 on a metal layer) and a TEXT label with the
terminal name inside each: npn13G2, npn13G2L, npn13G2V (C, B on Metal1; E on Metal2) and the rf MOSFETs (S, D, G,
TIE). Plain nmos/pmos have unnamed or no pins and are not supported yet.

Replace adds, in the layout and tagged (GDS property 202):
  - one REF_FOR_TRANSISTOR patch over the device (bounding box + 0.2 um), shared by all its ports;
  - one via port per terminal, from the lowest wiring metal (Metal1) down to that patch: along the pin if the pin is
    on Metal1, else along the device's Metal1 piece under the pin that is closest to the pin's center (the npn
    emitter: a Metal2 strip on one Metal1 island per finger, joined by Via1).
The export removes the device's own shapes below Metal1 (device_level_layers); its Metal1 and above stay.
"""
import pya

from .connectivity import wiring
from .locate import next_port_layer
from .ports import DEVICE_KEY, PROP_KEY, PortSettings

DEVICE_PCELLS = {"npn13G2", "npn13G2L", "npn13G2V", "rfnmos", "rfpmos", "rfnmosHV", "rfpmosHV"}
NOT_SUPPORTED = {"nmos", "pmos", "nmosHV", "pmosHV"}     # pins without names (nmos) or none (pmos): later
LIBRARY = "SG13_dev"
PIN_DATATYPE = 2                    # SG13G2 pin purpose, e.g. Metal1.pin = 8/2
TEXT_LAYER = (63, 0)                # SG13G2 TEXT.drawing: the pin names
REF_NAME = "REF_FOR_TRANSISTOR"
REF_MARGIN_UM = 0.2


class Device:
    def __init__(self, pcell, cell_index, trans, bbox, name):
        self.pcell = pcell          # pcell name, e.g. npn13G2
        self.cell_index = cell_index
        self.trans = trans          # ICplxTrans of the device cell into the searched cell
        self.bbox = bbox            # Box in the searched cell
        self.id = f"{name}@{trans.disp.x},{trans.disp.y}"      # stable as long as the device is not moved
        self.params = {}
        self.terminals = {}         # name -> (GDS layer of the pin metal, pin Box in the searched cell)
        self.problems = []
        self.ports = {}             # terminal -> port number, if replaced
        self.replaced = False


def _lowest_wiring_metal(stackup):
    """(GDS layer, name) of the lowest traced metal (Metal1): the ports start there."""
    metals = wiring(stackup)[0]
    z = {l.layer: stackup.z_range(l) for l in stackup.layers}
    layer = min(metals, key=lambda l: z[l][1] if z.get(l) else 1e9)
    return layer, metals[layer]


def device_level_layers(stackup):
    """GDS layers below the lowest wiring metal (Activ, Cont, the gate poly and resistor sources, ...): their device
    shapes are removed when a device is replaced. Derived layers count by their source layers."""
    m1, _ = _lowest_wiring_metal(stackup)
    m1_zmin = stackup.z_range(next(l for l in stackup.layers if l.layer == m1))[1]
    out = set()

    def add(number):
        if number in stackup.derived:
            for operand in stackup.derived[number][2]:
                add(operand)
        else:
            out.add(number)

    for l in stackup.layers:
        if l.name == REF_NAME:
            continue
        z = stackup.z_range(l)
        if z is not None and z[2] <= m1_zmin + 1e-6:
            add(l.layer)
    return out


def find_devices(layout, cell, stackup):
    """(devices, unknown): the supported devices in cell (recursively) and [(qualified name, count)] of SG13_dev
    pcells that are not supported or cannot be evaluated (PDK library not loaded)."""
    metal_layers = {l.layer for l in stackup.layers if l.is_metal}
    m1, _ = _lowest_wiring_metal(stackup)
    pin_layers = [li for li in layout.layer_indexes()
                  if layout.get_info(li).datatype == PIN_DATATYPE and layout.get_info(li).layer in metal_layers]
    text_li = layout.find_layer(*TEXT_LAYER)
    m1_li = layout.find_layer(m1, 0)
    devices, unknown = [], {}
    it = cell.begin_instances_rec()
    while not it.at_end():
        c = it.inst_cell()
        qname = c.qname()
        if qname.startswith(LIBRARY + "."):
            decl = c.pcell_declaration()
            name = decl.name() if decl is not None else qname.split(".", 1)[1]
            if decl is None or name not in DEVICE_PCELLS:
                if name in NOT_SUPPORTED or decl is None:
                    key = qname + ("" if decl is not None else " (PDK library not loaded)")
                    unknown[key] = unknown.get(key, 0) + 1
            else:
                trans = it.trans() * it.inst_trans()
                device = Device(name, c.cell_index(), trans, c.bbox().transformed(trans), c.name)
                params = c.pcell_parameters_by_name()
                device.params = {k: params[k] for k in ("model", "Nx", "Ny", "le", "we", "w", "l", "ng") if k in params}
                _terminals(layout, c, trans, device, pin_layers, text_li, m1_li, m1)
                devices.append(device)
        it.next()
    return devices, sorted(unknown.items())


def _terminals(layout, c, trans, device, pin_layers, text_li, m1_li, m1):
    labels = []
    if text_li is not None:
        for s in c.shapes(text_li).each():
            if s.is_text():
                labels.append((s.text.string, trans * pya.Point(s.text.x, s.text.y)))
    pins = []
    for li in pin_layers:
        for s in c.shapes(li).each():
            if not s.is_text():
                pins.append((layout.get_info(li).layer, s.bbox().transformed(trans)))
    for layer, box in pins:
        # the label nearest to the pin center (other texts, e.g. the device name, may fall into a pin box too)
        names = [n for n, p in sorted(labels, key=lambda item: item[1].distance(box.center())) if box.contains(p)]
        if not names:
            device.problems.append(f"pin on layer {layer} at {box.to_dtype(layout.dbu)} has no name")
            continue
        device.terminals[names[0]] = (layer, box)
    if len(device.terminals) < 2:
        device.problems.append("fewer than two named pins")
    device.m1 = pya.Region(c.begin_shapes_rec(m1_li)).transformed(trans).merged() if m1_li is not None else pya.Region()
    device.m1_layer = m1


def port_line(device, terminal):
    """Box (zero width) of the via port line for a terminal, or None: along the pin if it is on the lowest wiring
    metal, else along the device's Metal1 piece under the pin closest to the pin's center."""
    layer, pin = device.terminals[terminal]
    if layer == device.m1_layer:
        piece = pin
    else:
        under = [p.bbox() for p in device.m1.each() if p.bbox().overlaps(pin)]
        if not under:
            return None
        center = pin.center()
        piece = min(under, key=lambda b: b.center().distance(center))
    c = piece.center()
    if piece.height() >= piece.width():
        return pya.Box(c.x, piece.bottom, c.x, piece.top)
    return pya.Box(piece.left, c.y, piece.right, c.y)


def mark_replaced(layout, cell, devices):
    """Set device.replaced/.ports from the tagged ports and patches in cell."""
    tags = {}
    for li in layout.layer_indexes():
        info = layout.get_info(li)
        it = cell.begin_shapes_rec(li)
        while not it.at_end():
            value = it.shape().property(DEVICE_KEY)
            if isinstance(value, str) and value.startswith("device:"):
                parts = value.split(":")
                if len(parts) == 3 and 201 <= info.layer <= 299:
                    tags.setdefault(parts[1], {})[parts[2]] = info.layer - 200
                elif len(parts) == 2:
                    tags.setdefault(parts[1], {})
            it.next()
    for device in devices:
        if device.id in tags:
            device.replaced = True
            device.ports = tags[device.id]
    return devices


def replace(view, cell, stackup, devices):
    """Add the REF patch and the via ports for each device (not yet replaced, without problems). Returns
    {device id: {terminal: port number}}."""
    layout = cell.layout()
    ref = next((l for l in stackup.layers if l.name == REF_NAME), None)
    if ref is None:
        raise ValueError(f"the stackup has no {REF_NAME} layer")
    _, m1_name = _lowest_wiring_metal(stackup)
    margin = round(REF_MARGIN_UM / layout.dbu)
    done = {}
    view.transaction("Replace devices by ports")
    try:
        for device in devices:
            if device.replaced or device.problems:
                continue
            # properties set at insertion: a set_property after insert can move the shape (crash in KLayout 0.29.4)
            cell.shapes(layout.layer(ref.layer, 0)).insert(
                device.bbox.enlarged(margin, margin), layout.properties_id([[DEVICE_KEY, f"device:{device.id}"]]))
            for terminal in sorted(device.terminals):
                line = port_line(device, terminal)
                layer = next_port_layer(layout, cell)
                if line is None or layer is None:
                    continue
                settings = PortSettings("Z", m1_name, REF_NAME)
                cell.shapes(layout.layer(layer, 0)).insert(line, layout.properties_id(
                    [[PROP_KEY, settings.encode()], [DEVICE_KEY, f"device:{device.id}:{terminal}"]]))
                device.ports[terminal] = layer - 200
            device.replaced = True
            done[device.id] = dict(device.ports)
    finally:
        view.commit()
    view.add_missing_layers()
    return done


def unreplace(view, cell):
    """Remove all REF patches and ports made by replace (tagged with DEVICE_KEY). Returns the number of shapes."""
    layout = cell.layout()
    tagged = []
    for li in layout.layer_indexes():
        for shape in cell.shapes(li).each():
            value = shape.property(DEVICE_KEY)
            if isinstance(value, str) and value.startswith("device:"):
                tagged.append(shape)
    view.transaction("Undo device replacement")
    try:
        for shape in tagged:
            shape.delete()
    finally:
        view.commit()
    return len(tagged)


def device_shapes(layout, devices, layers):
    """{GDS layer: Region} of the replaced devices' own shapes on the given layers (datatype 0), in the cell the
    devices were found in: the export removes them."""
    out = {}
    for device in devices:
        if not device.replaced:
            continue
        c = layout.cell(device.cell_index)
        for layer in layers:
            li = layout.find_layer(layer, 0)
            if li is None:
                continue
            region = pya.Region(c.begin_shapes_rec(li)).transformed(device.trans)
            if not region.is_empty():
                out[layer] = (out[layer] + region) if layer in out else region
    return out
