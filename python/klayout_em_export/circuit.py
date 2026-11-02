"""Create Circuit: the EM result (.sNp) with the replaced devices put back, as a subcircuit for a circuit simulator.

Runs tools/spice_wrapper.py with a Python that has snp2le (KLayout's own Python has not): by default the one next
to setupEM, which runs in the same environment.
"""
import json
import os
import subprocess

import pya

from . import gui
from . import tech

WRAPPER = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools",
                                        "spice_wrapper.py"))
# (label, simulator, EM model as snp2le fit or the .sNp file)
CHOICES = (("ngspice, EM model by snp2le", "ngspice", "fit"),
           ("VACASK, EM model by snp2le", "vacask", "fit"),
           ("Xyce, EM model by snp2le", "xyce", "fit"),
           ("Xyce, the .sNp file (YLIN: harmonic balance only)", "xyce", "snp"),
           ("Spectre, the .sNp file (nport)", "spectre", "snp"))
EXTENSION = {"ngspice": ".cir", "vacask": ".inc", "xyce": ".cir", "spectre": ".scs"}


def default_python(settings):
    """The Python with snp2le: the one chosen before, else the one next to setupEM, else ''."""
    chosen = settings.get("snp2le_python")
    if chosen and os.path.isfile(chosen):
        return chosen
    setupem = settings.get("setupEM")
    if setupem:
        candidate = os.path.join(os.path.dirname(setupem), "python.exe" if os.name == "nt" else "python")
        if os.path.isfile(candidate):
            return candidate
    return ""


def default_output(snp, simulator, em):
    if not snp:
        return ""
    base = os.path.splitext(snp)[0]
    suffix = f"_{simulator}" + ("_snp" if simulator == "xyce" and em == "snp" else "")
    return base + suffix + EXTENSION[simulator]


def portmap_technology(path):
    """The circuit module of the port map's technology (tech/<technology>_circuit.py); IHP for old port maps."""
    try:
        with open(path) as f:
            name = json.load(f).get("technology")
        return tech.load_circuit(name or tech.PORTMAP_DEFAULT)
    except (OSError, ValueError):
        return tech.load_circuit(tech.PORTMAP_DEFAULT)


def run_wrapper(python, portmap, snp, output, simulator, em, pdk):
    """(ok, report) of tools/spice_wrapper.py."""
    command = [python, WRAPPER, portmap, snp, "-o", output, "--simulator", simulator, "--em", em]
    if pdk:
        command += ["--pdk", pdk]
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)      # KLayout's own Python must not leak into the other environment
    env.pop("PYTHONPATH", None)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=900, creationflags=flags)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"Failed to run {python}:\n{e}"
    report = (result.stdout + result.stderr).strip()
    return result.returncode == 0 and os.path.isfile(output), report


class CircuitDialog(pya.QDialog):
    def __init__(self, portmap):
        super().__init__(pya.Application.instance().main_window())
        self.settings = gui._load_settings()
        self.setWindowTitle("Create Circuit")
        self.resize(720, 0)
        form = pya.QFormLayout(self)
        self.portmap = self._file_row(form, "Port map", portmap, self._browse_portmap)
        self.snp = self._file_row(form, "EM result", "", self._browse_snp)
        gui.add_form_row(self, form, "",
                         pya.QLabel("The Palace result, preferably the _dc.sNp file (sweep started at 0 Hz)."))
        self.simulator = pya.QComboBox()
        for label, _, _ in CHOICES:
            self.simulator.addItem(label)
        self.simulator.setCurrentIndex(min(int(self.settings.get("circuit_choice", 0)), len(CHOICES) - 1))
        self.simulator.currentIndexChanged += lambda index: self._update_output()
        gui.add_form_row(self, form, "Simulator", self.simulator)
        self.pdk_label, self.pdk_hint = pya.QLabel(), pya.QLabel()
        self.pdk = self._file_row(form, self.pdk_label, self.settings.get("circuit_pdk", ""), self._browse_pdk)
        gui.add_form_row(self, form, "", self.pdk_hint)
        self._update_pdk_labels()
        self.output = self._file_row(form, "Output", "", self._browse_output)
        self.output.textEdited += lambda text: setattr(self, "_output_edited", True)
        self._output_edited = False
        self.python = self._file_row(form, "Python", default_python(self.settings), self._browse_python)
        gui.add_form_row(self, form, "", pya.QLabel("A Python with snp2le, e.g. the one of the setupEM environment."))
        buttons = pya.QDialogButtonBox(self)
        buttons.addButton("Create", pya.QDialogButtonBox.AcceptRole)
        buttons.addButton(pya.QDialogButtonBox.Cancel)
        buttons.accepted += self.accept
        buttons.rejected += self.reject
        gui.add_form_row(self, form, buttons)

    def _file_row(self, form, label, value, browse_handler):
        edit = pya.QLineEdit(value)
        browse = pya.QPushButton("Browse...")
        browse.clicked += browse_handler
        row = pya.QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(browse)
        gui.add_form_row(self, form, label, row)
        return edit

    def choice(self):
        return CHOICES[self.simulator.currentIndex]

    def _update_output(self):
        if not self._output_edited:
            _, simulator, em = self.choice()
            self.output.setText(default_output(self.snp.text, simulator, em))

    def _browse_portmap(self):
        path = pya.FileDialog.ask_open_file_name("Port map of the export", self.portmap.text,
                                                 "Port map (*_portmap.json)")
        if path:
            self.portmap.setText(path)
            self._update_pdk_labels()

    def _browse_snp(self):
        start = self.snp.text or self.settings.get("circuit_snp_dir", "")
        path = pya.FileDialog.ask_open_file_name("EM result (Touchstone)", start,
                                                 "Touchstone (*.s*p *.S*P);;All files (*)")
        if path:
            self.snp.setText(path)
            self._update_output()

    def _update_pdk_labels(self):
        circuit_tech = portmap_technology(self.portmap.text)
        self.pdk_label.setText(circuit_tech.PDK_LABEL)
        self.pdk_hint.setText(circuit_tech.PDK_HINT)

    def _browse_pdk(self):
        path = pya.FileDialog.ask_existing_dir(portmap_technology(self.portmap.text).PDK_BROWSE_TITLE, self.pdk.text)
        if path:
            self.pdk.setText(path)

    def _browse_output(self):
        path = pya.FileDialog.ask_save_file_name("Circuit file", self.output.text, "All files (*)")
        if path:
            self.output.setText(path)
            self._output_edited = True

    def _browse_python(self):
        path = pya.FileDialog.ask_open_file_name("Python with snp2le", self.python.text,
                                                 "Python (python*);;All files (*)")
        if path:
            self.python.setText(path)

    def problem(self):
        if not os.path.isfile(self.portmap.text):
            return "Choose the port map of the export (<name>_portmap.json)."
        if not os.path.isfile(self.snp.text):
            return "Choose the EM result (.sNp)."
        if not self.output.text:
            return "Choose the output file."
        if not os.path.isfile(self.python.text):
            return "Choose the Python with snp2le."
        return None


def create_circuit():
    view, cv = gui._current()
    portmap = ""
    if cv is not None:
        gds = gui.layout_value(cv.layout(), gui.META_OUTPUT)
        candidate = os.path.splitext(gds)[0] + "_portmap.json" if gds else ""
        portmap = candidate if candidate and os.path.isfile(candidate) else ""
    dialog = CircuitDialog(portmap)
    while True:
        if not dialog.exec_():
            return
        problem = dialog.problem()
        if problem is None:
            break
        pya.MessageBox.warning("Create Circuit", problem, pya.MessageBox.Ok)
    label, simulator, em = dialog.choice()
    settings = gui._load_settings()
    settings.update(snp2le_python=dialog.python.text, circuit_pdk=dialog.pdk.text,
                    circuit_snp_dir=os.path.dirname(dialog.snp.text),
                    circuit_choice=dialog.simulator.currentIndex)
    gui._save_settings(settings)
    ok, report = run_wrapper(dialog.python.text, dialog.portmap.text, dialog.snp.text, dialog.output.text,
                             simulator, em, dialog.pdk.text)
    if ok:
        gui._status(f"Circuit for {simulator}: {dialog.output.text}", 10)
        pya.MessageBox.info("Create Circuit", f"Wrote {dialog.output.text} ({label}).\n\n{report}", pya.MessageBox.Ok)
    else:
        pya.MessageBox.critical("Create Circuit", f"The circuit was not created.\n\n{report}", pya.MessageBox.Ok)
