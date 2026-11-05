"""Where the batch tests find their inputs and write their outputs, on Windows and Linux.

Layouts are in tests/data (see its README). A few large or third-party layouts are not in the repo: the tests that
read them skip without them.

Environment:
  KLAYOUT_EM_EXPORT_TESTDATA  optional: a folder with Palace_testcases/klayout_export/, for those other layouts.
  GDS2PALACE                  the gds2palace_ihp_sg13g2 repo (stackups, examples). Unset: next to this repo.
  IHP_PDK_ROOT                the folder that contains ihp-sg13g2. Unset: tests/pdk (made by tests/setup_pdk.sh).
  OUT                         output folder. Unset: <temp>/klayout_em_export_tests/<test name>.

A test imports it after putting its own folder on sys.path (KLayout's -r does not):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from testpaths import STACKUP, layout_file, out_dir
"""
import os
import tempfile

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(TESTS_DIR, ".."))
DATA_DIR = os.path.join(TESTS_DIR, "data")
OTHER_LAYOUTS = os.environ.get("KLAYOUT_EM_EXPORT_TESTDATA")
PDK_ROOT = os.environ.get("IHP_PDK_ROOT") or os.path.join(TESTS_DIR, "pdk")
GDS2PALACE = os.environ.get("GDS2PALACE") or os.path.normpath(os.path.join(REPO, "..", "gds2palace_ihp_sg13g2"))
STACKUP = os.path.join(GDS2PALACE, "XML_stackup", "latest", "IHP", "SG13G2_FEM_200um.xml")
EXAMPLE_BCE = os.path.join(GDS2PALACE, "more_examples", "core_transistor_3port_bce")


def layout_file(name):
    """A file in tests/data, else in the other layouts' folder. Not found: the tests/data path, whose read then fails
    with a missing file, or which the test checks itself (run_all.py reports a missing input as SKIP)."""
    path = os.path.join(DATA_DIR, name)
    if OTHER_LAYOUTS and not os.path.isfile(path):
        other = os.path.join(OTHER_LAYOUTS, "Palace_testcases", "klayout_export", name)
        if os.path.isfile(other):
            return other
    return path


def out_dir(name):
    """The output folder: OUT, else a folder for this test under the system temp folder."""
    path = os.environ.get("OUT") or os.path.join(tempfile.gettempdir(), "klayout_em_export_tests", name)
    os.makedirs(path, exist_ok=True)
    return path
