"""Replace PDK devices by ports: the device model is simulated in the circuit simulator, the EM model gets ports
at the device's terminals instead (reference plane at the pcell's pins).

Supported: SG13_dev pcells with named pins, i.e. pin shapes (datatype 2 on a metal layer) and a TEXT label with the
terminal name inside each: npn13G2, npn13G2L, npn13G2V (C, B on Metal1; E on Metal2) and the rf MOSFETs (S, D, G,
TIE). Plain nmos/pmos have unnamed or no pins and are not supported yet.

Replace adds, in the layout and tagged (GDS property 202):
  - one REF_FOR_TRANSISTOR patch under the device's pins (their bounding box + 0.2 um), shared by all its ports.
    Not the cell's bounding box: it includes implant and buried layers, and the boxes of devices placed side by side
    (a cascode) overlap, which would join their patches into one reference;
  - one via port per terminal, from the pin's metal down to that patch, along the full pin: one port for the whole
    terminal (all emitter fingers of an npn).
The reference plane is at the pins: the export removes the device's own shapes below them (device_shapes) - below
Metal1 everywhere, and under a pin on a higher metal also its wiring down to Metal1 (the npn emitter pin is a Metal2
strip on one Metal1 island per finger, joined by Via1). The device's other metal stays.
"""
import pya

from .connectivity import wiring
from .locate import next_port_layer
from .ports import DEVICE_KEY, PROP_KEY, PortSettings

DEVICE_PCELLS = {"npn13G2", "npn13G2L", "npn13G2V", "rfnmos", "rfpmos", "rfnmosHV", "rfpmosHV"}   # named pins
MOSFET_PCELLS = {"nmos", "pmos", "nmosHV", "pmosHV"}    # unnamed (nmos) or no (pmos) pins: terminals from geometry
RESISTOR_PCELLS = {"rsil", "rppd", "rhigh"}             # two unnamed Metal1 pins (PLUS, MINUS); replaced on request
STATIC_SUFFIX = "_CDNS_"            # a device cell exported from Cadence: <pcell name>_CDNS_<number>, no pcell context
POLY_LAYER = 5                      # SG13G2 GatPoly.drawing (datatype 0)
CONT_NAME = "Cont"
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
        self.terminals = {}         # name -> (GDS layer of the pin metal, [pin Box in the searched cell, ...]):
                                    # several boxes for a terminal on several fingers (multielement port)
        self.gate_trace = {}        # MOSFET: {GDS layer: Region} of the gate poly and contacts up to your gate contact
        self.is_resistor = pcell in RESISTOR_PCELLS
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
        name, params = None, {}
        if qname.startswith(LIBRARY + "."):
            decl = c.pcell_declaration()
            if decl is None:
                key = qname + " (PDK library not loaded)"
                unknown[key] = unknown.get(key, 0) + 1
            else:
                name = decl.name()
                values = c.pcell_parameters_by_name()
                params = {k: values[k] for k in ("model", "Nx", "Ny", "le", "we", "w", "l", "ng", "b") if k in values}
        elif STATIC_SUFFIX in c.name:
            name = c.name.split(STATIC_SUFFIX)[0]           # a device cell from Cadence: same pins, no parameters
            labels = [] if text_li is None else [s.text.string for s in c.shapes(text_li).each() if s.is_text()]
            if labels:
                params = {"label": labels[0]}
        if name in DEVICE_PCELLS or name in MOSFET_PCELLS or name in RESISTOR_PCELLS:
            trans = it.trans() * it.inst_trans()
            device = Device(name, c.cell_index(), trans, c.bbox().transformed(trans), c.name)
            device.params = params
            device.m1 = pya.Region(c.begin_shapes_rec(m1_li)).transformed(trans).merged() if m1_li is not None \
                else pya.Region()
            device.m1_layer = m1
            if name in MOSFET_PCELLS:
                _mosfet_terminals(layout, cell, c, trans, device, m1_li, m1, stackup)
            elif name in RESISTOR_PCELLS:
                _resistor_terminals(layout, c, trans, device, pin_layers, m1)
            else:
                _terminals(layout, c, trans, device, pin_layers, text_li, m1)
            devices.append(device)
        it.next()
    return devices, sorted(unknown.items())


def _terminals(layout, c, trans, device, pin_layers, text_li, m1):
    """Named pins: a pin shape on a metal pin layer, named by the TEXT label nearest to its center inside it."""
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
        device.terminals[names[0]] = (layer, [box])
    if len(device.terminals) < 2:
        device.problems.append("fewer than two named pins")


def _resistor_terminals(layout, c, trans, device, pin_layers, m1):
    """rsil, rppd, rhigh: two Metal1 pins without names, one per contact head. PLUS is the one with the lower
    coordinate along the resistor in the cell's own coordinates (the pcell draws PLUS at the bottom contact area).
    A resistor of several segments has more pins and is not replaced."""
    pins = [s.bbox() for li in pin_layers if layout.get_info(li).layer == m1 for s in c.shapes(li).each()
            if not s.is_text()]
    if len(pins) != 2:
        device.problems.append(f"{len(pins)} Metal1 pins, expected 2 (a resistor of several segments?)")
        return
    a, b = pins
    along_y = abs(a.center().y - b.center().y) >= abs(a.center().x - b.center().x)
    plus, minus = sorted(pins, key=lambda box: box.center().y if along_y else box.center().x)
    device.terminals["PLUS"] = (m1, [plus.transformed(trans)])
    device.terminals["MINUS"] = (m1, [minus.transformed(trans)])


def _mosfet_terminals(layout, top, c, trans, device, m1_li, m1, stackup):
    """nmos/pmos (feasibility tests T3-T5): source and drain are the device's Metal1 strips along the gate fingers,
    alternating S, D, S, ... from the left in the cell's own coordinates (the nmos pins mark only the first finger,
    the pmos has none). The gate pin is poly: the gate port goes on your Metal1 gate contact(s), found by tracing the
    poly from the first gate finger through Cont; that poly and those contacts are removed at the export (their
    resistance belongs to the device side). One port per terminal; several fingers = several elements."""
    strips = [] if m1_li is None else sorted(
        (p.bbox() for p in pya.Region(c.begin_shapes_rec(m1_li)).merged().each() if p.bbox().height() > p.bbox().width()),
        key=lambda b: b.left)
    if len(strips) < 2:
        device.problems.append("fewer than two Metal1 source/drain strips")
        return
    device.terminals["S"] = (m1, [b.transformed(trans) for b in strips[0::2]])
    device.terminals["D"] = (m1, [b.transformed(trans) for b in strips[1::2]])

    cont = next((l.layer for l in stackup.layers if l.name == CONT_NAME), None)
    poly_li = layout.find_layer(POLY_LAYER, 0)
    cont_li = None if cont is None else layout.find_layer(cont, 0)
    poly = [] if poly_li is None else sorted(
        (p.dup() for p in pya.Region(c.begin_shapes_rec(poly_li)).merged().each()), key=lambda p: p.bbox().left)
    if not poly or cont_li is None:
        device.problems.append("no gate poly or no Cont layer")
        return
    start = trans * poly[0].decompose_trapezoids()[0].bbox().center()     # inside the first gate finger
    connectivity = pya.NetTracerConnectivity()
    connectivity.connection(f"{POLY_LAYER}/0", f"{cont}/0")              # stops at Cont: not along your Metal1 wiring
    tracer = pya.NetTracer()
    tracer.trace(connectivity, layout, top, start, poly_li)
    traced = {POLY_LAYER: pya.Region(), cont: pya.Region()}
    for element in tracer.each_element():
        info = layout.get_info(element.layer())
        if info.layer in traced and not element.shape().is_text():
            traced[info.layer].insert(element.shape().polygon.transformed(element.trans()))
    contacts = traced[cont].merged()
    if contacts.is_empty():
        device.problems.append("gate poly has no contact")
        return
    pads = pya.Region(top.begin_shapes_rec_touching(m1_li, contacts.bbox())).merged().interacting(contacts)
    if pads.is_empty():
        device.problems.append("no Metal1 on the gate contacts")
        return
    device.terminals["G"] = (m1, [p.bbox() for p in pads.each()])
    device.gate_trace = {layer: region.merged() for layer, region in traced.items()}


def port_lines(device, terminal):
    """Boxes (zero width) of the via port lines of a terminal, one per pin box: along the pin, through its center,
    over its full length - all emitter fingers of an npn in one line, one line per source finger of a MOSFET."""
    lines = []
    for pin in device.terminals[terminal][1]:
        c = pin.center()
        lines.append(pya.Box(c.x, pin.bottom, c.x, pin.top) if pin.height() >= pin.width() else
                     pya.Box(pin.left, c.y, pin.right, c.y))
    return lines


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


def ref_patch(device, margin):
    """The REF_FOR_TRANSISTOR patch of a device: bounding box of its pins, grown by margin (dbu)."""
    pins = pya.Box()
    for _, boxes in device.terminals.values():
        for box in boxes:
            pins += box
    return pins.enlarged(margin, margin)


def touching_patches(layout, cell, stackup):
    """[(device id, device id)] of REF patches made by replace that touch or overlap: one shared reference."""
    ref = next((l for l in stackup.layers if l.name == REF_NAME), None)
    li = None if ref is None else layout.find_layer(ref.layer, 0)
    if li is None:
        return []
    patches = []
    for shape in cell.shapes(li).each():
        value = shape.property(DEVICE_KEY)
        if isinstance(value, str) and value.startswith("device:"):
            patches.append((value.split(":", 1)[1], shape.bbox()))
    return [(a, b) for i, (a, box_a) in enumerate(patches) for b, box_b in patches[i + 1:] if box_a.touches(box_b)]


def replace(view, cell, stackup, devices, include_resistors=False):
    """Add the REF patch and the via ports for each device (not yet replaced, without problems); resistors only
    with include_resistors (replacing them is optional: unreplaced, the stackup models them as sheet resistors).
    Returns {device id: {terminal: port number}}."""
    layout = cell.layout()
    ref = next((l for l in stackup.layers if l.name == REF_NAME), None)
    if ref is None:
        raise ValueError(f"the stackup has no {REF_NAME} layer")
    names = {l.layer: l.name for l in stackup.layers}
    margin = round(REF_MARGIN_UM / layout.dbu)
    done = {}
    view.transaction("Replace devices by ports")
    try:
        for device in devices:
            if device.replaced or device.problems or (device.is_resistor and not include_resistors):
                continue
            # properties set at insertion: a set_property after insert can move the shape (crash in KLayout 0.29.4)
            cell.shapes(layout.layer(ref.layer, 0)).insert(
                ref_patch(device, margin), layout.properties_id([[DEVICE_KEY, f"device:{device.id}"]]))
            for terminal in sorted(device.terminals):
                layer = next_port_layer(layout, cell)
                if layer is None:
                    continue
                settings = PortSettings("Z", names[device.terminals[terminal][0]], REF_NAME)   # from the pin metal
                properties = layout.properties_id([[PROP_KEY, settings.encode()],
                                                   [DEVICE_KEY, f"device:{device.id}:{terminal}"]])
                for line in port_lines(device, terminal):      # several lines: elements of one port
                    cell.shapes(layout.layer(layer, 0)).insert(line, properties)
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


def device_shapes(layout, devices, stackup):
    """{GDS layer: Region} of the replaced devices' own shapes that belong to the device model, in the cell the
    devices were found in: the export removes them. These are all its shapes below Metal1 (device_level_layers),
    and under a pin on a higher metal also its wiring between Metal1 and that metal (the npn emitter: one Metal1
    island per finger and the Via1 under the Metal2 emitter pin) - the reference plane is at the pin."""
    z = {l.layer: stackup.z_range(l) for l in stackup.layers}
    wiring_layers = [l.layer for l in stackup.layers if l.kind in ("conductor", "via") and l.layer not in stackup.derived]
    device_level = device_level_layers(stackup)
    out = {}

    def add(layer, region):
        if not region.is_empty():
            out[layer] = (out[layer] + region) if layer in out else region

    for device in devices:
        if not device.replaced:
            continue
        c = layout.cell(device.cell_index)

        def shapes(layer):
            li = layout.find_layer(layer, 0)
            return pya.Region() if li is None else pya.Region(c.begin_shapes_rec(li)).transformed(device.trans)

        for layer in device_level:
            add(layer, shapes(layer))
        for layer, region in device.gate_trace.items():        # MOSFET: gate poly and contacts up to your contact
            add(layer, region)
        for pin_layer, pins in device.terminals.values():
            if pin_layer == device.m1_layer or not z.get(pin_layer):
                continue
            below = [l for l in wiring_layers if l not in device_level and z.get(l) and z[l][0] == z[pin_layer][0]
                     and z[l][2] <= z[pin_layer][1] + 1e-6]
            for layer in below:
                for pin in pins:
                    add(layer, shapes(layer) & pya.Region(pin))
    return out
