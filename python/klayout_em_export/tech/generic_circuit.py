"""Generic technology in the circuit wrapper: no device models. An export of this technology has no replaced devices,
so the wrapper is the EM model alone (with the DC paths of the wiring).
"""
NAME = "generic"
PDK_LABEL = "PDK"
PDK_HINT = "Not needed: the port map's technology has no device models."
PDK_BROWSE_TITLE = "PDK folder"
PDK_FOLDERS = {}


def pdk_folder(path):
    return path or None
LIBRARIES = {}
SPECTRE_NOTE = "PDK model libraries: none (no device models)"
VACASK_HEADER = ()


def pcell_of(device_id):
    return device_id.split("@")[0]


def lib_path(pdk, simulator, lib):
    return lib


def instantiate(k, device_id, pcell, params, term):
    return ([("comment", "  not instantiated: no device models for this technology")],
            [f"{device_id}: no device models for this technology, not instantiated"], None)
