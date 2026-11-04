"""Generic technology: no device support. Used when no known PDK is found in the layout (see tech.for_layout).

Ports, the export, the ground and boundary checks work as with any other technology; devices stay in the EM model
as drawn layout. The ground check traces every conductor of the stackup (apart from the device levels of the known
technologies): a stackup with a diffusion layer of another process needs a technology module of its own, see
"Adding a technology" in doc/ARCHITECTURE.md.
"""
NAME = "generic"
LABEL = "generic (no device support)"
KLAYOUT_TECHNOLOGIES = ()
DEVICE_LEVEL = set()
HEAT_TARGET = None                  # no devices, so no heat sources (see ihp_sg13.HEAT_TARGET)
THERMAL_PURPOSES = (0,)             # datatypes the thermal export always keeps (see ihp_sg13.THERMAL_PURPOSES)
NO_DEVICES = "no device support for this layout's technology: devices are simulated as drawn layout"


def devices_in(layout):
    return None


def context(layout, stackup):
    return {}


def identify(c, ctx):
    return None, {}, None


def is_device(name):
    return False


def is_resistor(name):
    return False


def terminals(layout, top, c, trans, device, ctx, m1_li, m1, stackup):
    pass


def describe(device):
    return ""


def resistor_note(device):
    return "simulated as drawn layout"


def heat_area(layout, device):
    """No device support, so no heat sources (HEAT_TARGET is None); the bounding box, should a device ever reach here."""
    import pya
    return pya.Region(device.bbox), "bbox"


def lvs_classes(device):
    return set()


def lvs_element(device):
    return "X"
