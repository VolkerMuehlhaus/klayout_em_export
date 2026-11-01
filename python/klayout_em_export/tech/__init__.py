"""Technologies: what the plug-in knows about one fab's PDK, apart from the stackup.

The generic modules (ports, export, connectivity, devices.py's replace and undo, the panel) work with any gds2palace
stackup. A technology module adds the PDK specifics: which cells are devices and where their terminals are
(<name>.py, needs pya), and how the circuit wrapper instantiates them (<name>_circuit.py, plain Python: it is also
imported by tools/spice_wrapper.py outside KLayout). generic.py / generic_circuit.py: no device support, used when
no technology matches the layout.

This package imports no technology at import time, so that tools/spice_wrapper.py can import a _circuit module
without pya.
"""
import importlib

TECHNOLOGIES = ("ihp_sg13",)        # tried in this order
GENERIC = "generic"
PORTMAP_DEFAULT = "ihp_sg13"        # port maps written before the technology was recorded


def names():
    return TECHNOLOGIES + (GENERIC,)


def load(name):
    """The technology module (needs pya)."""
    if name not in names():
        raise ValueError(f"unknown technology {name!r} (known: {', '.join(names())})")
    return importlib.import_module(f".{name}", __name__)


def load_circuit(name):
    """The technology's circuit module (plain Python)."""
    if name not in names():
        raise ValueError(f"unknown technology {name!r} (known: {', '.join(names())})")
    return importlib.import_module(f".{name}_circuit", __name__)


def for_layout(layout, override=None):
    """(technology module, reason) for a layout: the override (a technology name from the settings) if given, else
    the first technology whose devices are in the layout, else the first whose KLayout technology name the layout
    has, else generic."""
    if override:
        return load(override), "chosen in the settings file"
    for name in TECHNOLOGIES:
        reason = load(name).devices_in(layout)
        if reason:
            return load(name), reason
    for name in TECHNOLOGIES:
        technology = load(name)
        if layout.technology_name in technology.KLAYOUT_TECHNOLOGIES:
            return technology, f"KLayout technology {layout.technology_name}"
    return load(GENERIC), "no devices or KLayout technology of a known PDK in the layout"


def device_level_names():
    """Names of the stackup layers below the wiring in any known technology (SG13G2: Activ): the ground check does
    not trace them (see connectivity.py). The union over all technologies, so that it needs no layout."""
    out = set()
    for name in names():
        out |= set(load(name).DEVICE_LEVEL)
    return out
