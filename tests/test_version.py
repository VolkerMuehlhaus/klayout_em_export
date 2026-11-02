# Plain Python test: the plug-in's version is the same in grain.xml (KLayout's package manager) and in the package
# (__version__, shown in the EM panel's title and given by the CLI's status), and the user's guide names it.
#   python tests/test_version.py
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "python"))
from klayout_em_export import __version__        # noqa: E402 (the package's __init__ imports nothing)

grain = re.search(r"<version>([^<]+)</version>", open(os.path.join(ROOT, "grain.xml"), encoding="utf-8").read())
guide = open(os.path.join(ROOT, "doc", "userguide", "klayout_em_export_userguide.md"), encoding="utf-8").read()
failed = []
for ok, text in ((grain is not None and grain.group(1) == __version__,
                  f"grain.xml {grain.group(1) if grain else None} == __version__ {__version__}"),
                 (f"plug-in version {__version__}" in guide, f"the user's guide names plug-in version {__version__}")):
    print("ok   " if ok else "FAIL ", text)
    if not ok:
        failed.append(text)
print("all passed" if not failed else f"FAILED: {'; '.join(failed)}")
sys.exit(1 if failed else 0)
