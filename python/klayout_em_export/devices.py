"""Replace PDK devices by ports: the device model is simulated in the circuit simulator, the EM model gets ports
at the device's terminals instead (reference plane at the device's pins).

Which cells are devices and where their terminals are is the technology's part (tech/, e.g. tech/ihp_sg13.py);
the rest is generic. Replace adds, in the layout and tagged (GDS property 202):
  - one REF_FOR_TRANSISTOR patch under the device's pins (their bounding box + 0.2 um), shared by all its ports.
    Not the cell's bounding box: it includes implant and buried layers, and the boxes of devices placed side by side
    (a cascode) overlap, which would join their patches into one reference;
  - one via port per terminal, from the pin's metal down to that patch, along the full pin: one port for the whole
    terminal (all emitter fingers of an npn).
The reference plane is at the pins: the export removes the device's own shapes below them (device_shapes) - below
the lowest wiring metal everywhere, and under a pin on a higher metal also its wiring down to that metal (the SG13G2
npn emitter pin is a Metal2 strip on one Metal1 island per finger, joined by Via1). The device's other metal stays.
"""
import pya

from .connectivity import wiring
from .locate import next_port_layer
from .ports import DEVICE_KEY, PROP_KEY, PortSettings
from .tech import for_layout

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
        self.is_resistor = False    # set by find_devices (technology); replaced only on request
        self.problems = []
        self.ports = {}             # terminal -> port number, if replaced
        self.replaced = False


def _lowest_wiring_metal(stackup):
    """(GDS layer, name) of the lowest metal that a via connects to another metal (Metal1): the ports start there.
    Not simply the lowest conductor: a stackup can define ground planes (SUBGND, BACKSIDEGND) as PEC conductors
    below it, which no via connects."""
    metals, connections = wiring(stackup)
    connected = {layer for _, below, above in connections for layer in (below, above)} or set(metals)
    z = {l.layer: stackup.z_range(l) for l in stackup.layers}
    layer = min(connected, key=lambda l: z[l][1] if z.get(l) else 1e9)
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


def find_devices(layout, cell, stackup, technology=None):
    """(devices, unknown): the supported devices in cell (recursively) and [(qualified name, count)] of PDK library
    cells that cannot be evaluated (PDK library not loaded). technology: a tech module, else found from the layout."""
    tech = technology or for_layout(layout)[0]
    m1, _ = _lowest_wiring_metal(stackup)
    m1_li = layout.find_layer(m1, 0)
    ctx = tech.context(layout, stackup)
    devices, unknown = [], {}
    it = cell.begin_instances_rec()
    while not it.at_end():
        c = it.inst_cell()
        name, params, problem = tech.identify(c, ctx)
        if problem is not None:
            unknown[problem] = unknown.get(problem, 0) + 1
        if name is not None and tech.is_device(name):
            trans = it.trans() * it.inst_trans()
            device = Device(name, c.cell_index(), trans, c.bbox().transformed(trans), c.name)
            device.params = params
            device.is_resistor = tech.is_resistor(name)
            device.m1 = pya.Region(c.begin_shapes_rec(m1_li)).transformed(trans).merged() if m1_li is not None \
                else pya.Region()
            device.m1_layer = m1
            tech.terminals(layout, cell, c, trans, device, ctx, m1_li, m1, stackup)
            devices.append(device)
        it.next()
    return devices, sorted(unknown.items())


def port_lines(device, terminal):
    """Boxes (zero width) of the via port lines of a terminal, one per pin box: along the pin, through its center,
    over its full length - all emitter fingers of an npn in one line, one line per source finger of a MOSFET."""
    lines = []
    for pin in device.terminals[terminal][1]:
        c = pin.center()
        lines.append(pya.Box(c.x, pin.bottom, c.x, pin.top) if pin.height() >= pin.width() else
                     pya.Box(pin.left, c.y, pin.right, c.y))
    return lines


def _device_tags(layout, cell):
    """{device id: {terminal: port number}} of the ports and patches tagged by replace in cell."""
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
    return tags


def mark_replaced(layout, cell, devices):
    """Set device.replaced/.ports from the tagged ports and patches in cell."""
    tags = _device_tags(layout, cell)
    for device in devices:
        if device.id in tags:
            device.replaced = True
            device.ports = tags[device.id]
    return devices


def orphaned_tags(layout, cell, devices):
    """{device id: {terminal: port number}} of tagged ports and patches whose device is not found in cell: the device
    was moved (its id holds its position) or deleted. Undo Replace removes them, Replace All makes new ones."""
    ids = {device.id for device in devices}
    return {i: ports for i, ports in _device_tags(layout, cell).items() if i not in ids}


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
                layer = next_port_layer(layout, cell, stackup=stackup)
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


def unconnected_terminals(layout, devices, check):
    """[(device, terminal)] of the terminals that connect to no wiring: the net traced from the pin (check: a
    connectivity.GroundCheck of the region, for its metal and via regions) holds only the device's own metal. Such a
    terminal floats in the EM model, e.g. when the wiring to the device was cut."""
    from .connectivity import flood
    out = []
    for device in devices:
        c = layout.cell(device.cell_index)
        own = {}
        for layer in check.metals:
            li = layout.find_layer(layer, 0)
            own[layer] = pya.Region() if li is None else pya.Region(c.begin_shapes_rec(li)).transformed(device.trans)
        for terminal, (pin_layer, pins) in sorted(device.terminals.items()):
            if pin_layer not in check.metals:
                continue
            seed = pya.Region()
            for pin in pins:
                seed += check.metals[pin_layer].interacting(pya.Region(pin))
            if seed.is_empty():
                continue                # pin outside the checked region: not checked
            def foreign(net):           # the net holds metal that is not the device's own: connected
                return any(not (region - own.get(layer, pya.Region())).is_empty() for layer, region in net.items())
            if not foreign(flood(check.metals, check.vias, check.connections, {pin_layer: seed}, stop=foreign)):
                out.append((device, terminal))
    return out


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
