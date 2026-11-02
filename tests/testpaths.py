"""Where the batch tests find their inputs and write their outputs, on Windows and Linux.

Environment:
  KLAYOUT_EM_EXPORT_TESTDATA  folder with Palace_testcases/ and klayout_em_export_tests/ (e.g. on hpz2:
                              ~/claude/klayout_em_export_testdata). Unset: D:\\Palace_testcases and the
                              klayout_em_export_tests folder next to this repo (the Windows development machine).
  GDS2PALACE                  the gds2palace_ihp_sg13g2 repo (stackups, examples). Unset: next to this repo.
  OUT                         output folder. Unset: <temp>/klayout_em_export_tests/<test name>.

A test imports it after putting its own folder on sys.path (KLayout's -r does not):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from testpaths import STACKUP, palace_testcases, out_dir
"""
import os
import tempfile

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.environ.get("KLAYOUT_EM_EXPORT_TESTDATA")
TESTS_DIR = (os.path.join(DATA, "klayout_em_export_tests") if DATA else
             os.path.normpath(os.path.join(REPO, "..", "klayout_em_export_tests")))
GDS2PALACE = os.environ.get("GDS2PALACE") or os.path.normpath(os.path.join(REPO, "..", "gds2palace_ihp_sg13g2"))
STACKUP = os.path.join(GDS2PALACE, "XML_stackup", "latest", "IHP", "SG13G2_FEM_200um.xml")
EXAMPLE_BCE = os.path.join(GDS2PALACE, "more_examples", "core_transistor_3port_bce")


def palace_testcases(*parts):
    """A file under Palace_testcases (user layouts, not in any repo)."""
    return os.path.join(DATA if DATA else "D:\\", "Palace_testcases", *parts)


def tests_data(*parts):
    """A file under klayout_em_export_tests (feasibility tests: testcases/, work/, pdk_env.py)."""
    return os.path.join(TESTS_DIR, *parts)


def out_dir(name):
    """The output folder: OUT, else a folder for this test under the system temp folder."""
    path = os.environ.get("OUT") or os.path.join(tempfile.gettempdir(), "klayout_em_export_tests", name)
    os.makedirs(path, exist_ok=True)
    return path
