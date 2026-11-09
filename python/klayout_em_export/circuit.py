"""Create Circuit: the EM result (.sNp) with the replaced devices put back, as a subcircuit for a circuit simulator.

Runs tools/spice_wrapper.py with a Python that has snp2le (KLayout's own Python has not): by default the one next
to setupEM, which runs in the same environment.
"""
import glob
import json
import os
import re
import shutil
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


def python_of(program):
    """The Python a program runs in: a Python entry script names it in its first line; a wrapper script (e.g.
    ~/scripts/setupEM) activates a venv; else (setupEM.exe of a Windows venv) the Python next to it. '' if none."""
    if not program or not os.path.isfile(program):
        return ""
    names = ("python.exe",) if os.name == "nt" else ("python3", "python")
    bin_dir = "Scripts" if os.name == "nt" else "bin"
    try:
        with open(program, "rb") as f:
            head = f.read(4096).decode("utf-8", "replace")
    except OSError:
        head = ""
    if head.startswith("#!"):
        interpreter = head[2:].splitlines()[0].strip().split(" ")[0]
        if "python" in os.path.basename(interpreter) and os.path.isfile(interpreter):
            return interpreter
    m = re.search(r"([~\w./\\:-]+?)[/\\](?:bin|Scripts)[/\\]activate", head)
    if m:
        venv = os.path.expanduser(m.group(1))
        for name in names:
            if os.path.isfile(os.path.join(venv, bin_dir, name)):
                return os.path.join(venv, bin_dir, name)
    folder = os.path.dirname(os.path.realpath(program))
    for name in names:
        if os.path.isfile(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return ""


def has_snp2le(python):
    """Whether snp2le is installed for this Python (a look into its venv's site-packages, no Python started); None
    when that can't be told (not a venv)."""
    venv = os.path.dirname(os.path.dirname(python))
    sites = (glob.glob(os.path.join(venv, "Lib", "site-packages")) +
             glob.glob(os.path.join(venv, "lib", "python*", "site-packages")))
    if not sites:
        return None
    # the package, or an editable install's link (__editable__...snp2le..., snp2le.egg-link)
    return any(glob.glob(os.path.join(site, "*snp2le*")) for site in sites)


def default_python(settings):
    """(Python, where from) for snp2le: the one chosen before, else the one setupEM runs in (setupEM as the export
    dialog finds it: chosen before, or on the PATH); ('', '') if none."""
    chosen = settings.get("snp2le_python")
    if chosen and os.path.isfile(chosen):
        return chosen, ""
    setupem = settings.get("setupEM") or shutil.which("setupEM") or shutil.which("setupEM.bat")
    python = python_of(setupem) if setupem else ""
    return (python, "setupEM's Python") if python else ("", "")


def find_pdk(circuit_tech, layout_technology=None):
    """(PDK folder, where it was found) for the circuit: KLayout's installed PDK technology (the layout's own first),
    then PDK_ROOT / PDK, IHP_PDK_ROOT, and the usual install places; ("", "") if none is found."""
    folders = getattr(circuit_tech, "PDK_FOLDERS", {})
    normalize = getattr(circuit_tech, "pdk_folder", None)
    if not folders or normalize is None:
        return "", ""
    names = sorted(folders, key=lambda n: n != layout_technology)
    for name in names:
        try:
            tech = pya.Technology.technology_by_name(name) if pya.Technology.has_technology(name) else None
        except Exception:       # noqa: BLE001
            tech = None
        base = tech.base_path() if tech is not None else ""
        found = normalize(os.path.realpath(base)) if base else None
        if found:
            return found, f"KLayout's {name} technology"
    env = []
    if os.environ.get("PDK_ROOT"):
        env.append((os.path.join(os.environ["PDK_ROOT"], os.environ.get("PDK", "")), "PDK_ROOT"))
    if os.environ.get("IHP_PDK_ROOT"):
        env.append((os.environ["IHP_PDK_ROOT"], "IHP_PDK_ROOT"))
    home = os.path.expanduser("~")
    places = [(os.path.join(home, "github", "IHP-Open-PDK"), "the usual place"),
              (os.path.join(home, "IHP-Open-PDK"), "the usual place"), ("/foss/pdks", "the usual place")]
    for path, how in env + places:
        found = normalize(path) if os.path.isdir(path) else None
        if found:
            return found, how
    return "", ""


RESULT_KINDS = ("_dc_deembedded", "_dc", "_deembedded", "")     # preferred first: calibrated, with the 0 Hz point


def default_snp(portmap):
    """(path, kind) of the EM result of the export a port map belongs to, where setupEM puts it:
    <sim_path>/palace_model/<model>_data/output/<model>/<model><kind>.sNp, the model and folder from the export's
    .simcfg (setupEM's model script, if it wrote the file, names the model). The best kind first (RESULT_KINDS);
    ("", "") if there is none. A split region's .simcfg gives the joined result, which is written there too."""
    if not portmap or not portmap.endswith("_portmap.json"):
        return "", ""
    base = portmap[:-len("_portmap.json")]
    simcfg = base + ".simcfg"
    values, written_with = {}, None
    try:
        with open(simcfg, encoding="utf-8") as f:
            data = json.load(f)
        values = data.get("saved_values", {}) or {}
        written_with = data.get("written_with")
    except (OSError, ValueError):
        pass
    folder = values.get("sim_path") or os.path.dirname(os.path.abspath(simcfg))
    names = []
    if written_with:
        names.append(os.path.splitext(written_with)[0])
    if values.get("model_basename"):
        names.append(values["model_basename"])
    names.append(os.path.basename(base))
    for name in dict.fromkeys(names):
        out = os.path.join(folder, "palace_model", f"{name}_data", "output", name)
        if not os.path.isdir(out):
            continue
        files = os.listdir(out)
        for kind in RESULT_KINDS:
            pattern = re.compile(re.escape(name + kind) + r"\.s\d+p$", re.IGNORECASE)
            match = sorted(f for f in files if pattern.match(f))
            if match:
                return os.path.join(out, match[0]).replace("\\", "/"), kind
    return "", ""


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
    def __init__(self, portmap, layout_technology=None):
        super().__init__(pya.Application.instance().main_window())
        self.settings = gui._load_settings()
        self.setWindowTitle("Create Circuit")
        self.resize(720, 0)
        form = pya.QFormLayout(self)
        self.portmap = self._file_row(form, "Port map", portmap, self._browse_portmap)
        self.snp = self._file_row(form, "EM result", "", self._browse_snp)
        self.snp_hint = pya.QLabel()
        self.snp_hint.setWordWrap(True)
        gui.add_form_row(self, form, "", self.snp_hint)
        self._fill_snp()
        self.simulator = pya.QComboBox()
        for label, _, _ in CHOICES:
            self.simulator.addItem(label)
        self.simulator.setCurrentIndex(min(int(self.settings.get("circuit_choice", 0)), len(CHOICES) - 1))
        self.simulator.currentIndexChanged += lambda index: self._update_output()
        gui.add_form_row(self, form, "Simulator", self.simulator)
        self.pdk_label, self.pdk_hint = pya.QLabel(), pya.QLabel()
        self._snp_chosen = False
        self.layout_technology = layout_technology
        self.pdk = self._file_row(form, self.pdk_label, "", self._browse_pdk)
        gui.add_form_row(self, form, "", self.pdk_hint)
        self._update_pdk_labels()
        self._fill_pdk()
        self.output = self._file_row(form, "Output", "", self._browse_output)
        self.output.textEdited += lambda text: setattr(self, "_output_edited", True)
        self._output_edited = False
        self._update_output()
        python, found_by = default_python(self.settings)
        self.python = self._file_row(form, "Python", python, self._browse_python)
        self.python_hint = pya.QLabel()
        self.python_hint.setWordWrap(True)
        gui.add_form_row(self, form, "", self.python_hint)
        self._python_hint(found_by)
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

    SNP_HINT = "The Palace result, preferably the _dc.sNp file (sweep started at 0 Hz)."
    KIND_TEXT = {"_dc_deembedded": "calibrated, with 0 Hz", "_dc": "with 0 Hz, not de-embedded",
                 "_deembedded": "calibrated, without 0 Hz: the DC point is extrapolated by snp2le", "": "raw result"}

    def _fill_snp(self, replace=False):
        """The export's EM result (default_snp), unless one is chosen already."""
        if self.snp.text and not replace:
            return
        path, kind = default_snp(self.portmap.text)
        if path:
            self.snp.setText(path)
            self.snp_hint.setText(f"The model's result, {self.KIND_TEXT[kind]}. " + self.SNP_HINT)
            if hasattr(self, "output"):
                self._update_output()
        else:
            self.snp_hint.setText(self.SNP_HINT + " No result of this export found yet.")

    def _browse_portmap(self):
        path = pya.FileDialog.ask_open_file_name("Port map of the export", self.portmap.text,
                                                 "Port map (*_portmap.json)")
        if path:
            self.portmap.setText(path)
            self._update_pdk_labels()
            self._fill_snp(replace=not self._snp_chosen)

    def _browse_snp(self):
        start = self.snp.text or self.settings.get("circuit_snp_dir", "")
        path = pya.FileDialog.ask_open_file_name("EM result (Touchstone)", start,
                                                 "Touchstone (*.s*p *.S*P);;All files (*)")
        if path:
            self.snp.setText(path)
            self._snp_chosen = True
            self.snp_hint.setText(self.SNP_HINT)
            self._update_output()

    def _update_pdk_labels(self, found_by=None):
        circuit_tech = portmap_technology(self.portmap.text)
        self.pdk_label.setText(circuit_tech.PDK_LABEL)
        self.pdk_hint.setText(circuit_tech.PDK_HINT + (f" Found from {found_by}." if found_by else ""))

    def _fill_pdk(self):
        """The PDK folder: the one chosen last time if it is still a PDK folder, else found (find_pdk)."""
        circuit_tech = portmap_technology(self.portmap.text)
        normalize = getattr(circuit_tech, "pdk_folder", lambda p: p or None)
        last = normalize(self.settings.get("circuit_pdk", ""))
        if last:
            self.pdk.setText(last)
            return
        found, how = find_pdk(circuit_tech, self.layout_technology)
        if found:
            self.pdk.setText(found)
            self._update_pdk_labels(how)

    def _browse_pdk(self):
        circuit_tech = portmap_technology(self.portmap.text)
        path = pya.FileDialog.ask_existing_dir(circuit_tech.PDK_BROWSE_TITLE, self.pdk.text)
        if path:
            # any level will do: IHP-Open-PDK, its ihp-sg13g2 folder, or a folder inside it
            self.pdk.setText(getattr(circuit_tech, "pdk_folder", lambda p: p)(path) or path)

    def _browse_output(self):
        path = pya.FileDialog.ask_save_file_name("Circuit file", self.output.text, "All files (*)")
        if path:
            self.output.setText(path)
            self._output_edited = True

    def _python_hint(self, found_by=""):
        text = "A Python with snp2le, e.g. the one setupEM runs in."
        python = self.python.text
        if python and os.path.isfile(python):
            installed = has_snp2le(python)
            if found_by:
                text = f"Found: {found_by}. " + text
            if installed is False:
                text += f" snp2le is not installed there: {python} -m pip install snp2le"
        self.python_hint.setText(text)

    def _browse_python(self):
        path = pya.FileDialog.ask_open_file_name("Python with snp2le", self.python.text,
                                                 "Python (python*);;All files (*)")
        if path:
            self.python.setText(path)
            self._python_hint()

    def problem(self):
        if not os.path.isfile(self.portmap.text):
            return "Choose the port map of the export (<name>_portmap.json)."
        if not os.path.isfile(self.snp.text):
            return "Choose the EM result (.sNp)."
        if not self.output.text:
            return "Choose the output file."
        if not os.path.isfile(self.python.text):
            return "Choose the Python with snp2le."
        circuit_tech = portmap_technology(self.portmap.text)
        if self.pdk.text and getattr(circuit_tech, "PDK_FOLDERS", {}):
            folder = circuit_tech.pdk_folder(self.pdk.text)
            if folder is None:
                return (f"{self.pdk.text} is not a PDK folder: choose the ihp-sg13g2 (or ihp-sg13cmos5l) folder inside "
                        "IHP-Open-PDK, the one that contains libs.tech, or leave the field empty.")
            self.pdk.setText(folder)
        return None


def create_circuit():
    view, cv = gui._current()
    portmap = ""
    if cv is not None:
        gds = gui.layout_value(cv.layout(), gui.META_OUTPUT)
        candidate = os.path.splitext(gds)[0] + "_portmap.json" if gds else ""
        portmap = candidate if candidate and os.path.isfile(candidate) else ""
    technology = None
    if cv is not None:
        technology = cv.technology() if callable(getattr(cv, "technology", None)) else getattr(cv, "technology", None)
    dialog = CircuitDialog(portmap, technology)
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
