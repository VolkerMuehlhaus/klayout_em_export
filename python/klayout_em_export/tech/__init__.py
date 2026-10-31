"""Technologies: what the plug-in knows about one fab's PDK, apart from the stackup.

The generic modules (ports, export, connectivity, devices.py's replace and undo, the panel) work with any gds2palace
stackup. A technology module adds the PDK specifics: which cells are devices and where their terminals are
(<name>.py, needs pya), and how the circuit wrapper instantiates them (<name>_circuit.py, plain Python: it is also
imported by tools/spice_wrapper.py outside KLayout).

This package imports no technology at import time, so that tools/spice_wrapper.py can import a _circuit module
without pya.
"""


def active():
    """The technology module in use. For now always IHP SG13G2."""
    from . import ihp_sg13g2
    return ihp_sg13g2
