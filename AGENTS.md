# AGENTS.md

Rules for AI agents developing klayout_em_export. Read [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) first: module map,
data formats, and the design decisions with their reasons. The user-facing behaviour is in the
[README](README.md) and the [user's guide](doc/userguide/klayout_em_export_userguide.md).

## Repository and git

- Private repo `volkermuehlhaus-claude/klayout_em_export`, remote `origin`. There is no upstream original: this
  repo is not a fork, so there is nothing to open a PR against.
- Local git identity: `volkermuehlhaus-claude`, `claude@muehlhaus.com`. Commit or push only when the user asks.
- Working copies have CRLF line endings (`core.autocrlf`). `*.sh` files stay LF (`.gitattributes`), because
  `tests/simulators/run.sh` runs on Linux.

## Where the code runs

- `python/klayout_em_export/` runs inside KLayout's Python: `pya` and the standard library only. Do not import
  gdspy, numpy, shapely or anything else that KLayout's Python lacks.
- `tools/spice_wrapper.py` runs outside KLayout, in a Python with snp2le (e.g. `d:\venv\palace`).
- The plug-in is installed as a junction: `%USERPROFILE%\KLayout\salt\klayout_em_export` points at this repo. An
  edit takes effect when KLayout restarts (autorun macro at startup); batch tests import the current files.
- Keep core modules free of GUI code, so batch tests can drive them. Dialogs and the panel only collect input and
  call the core (see the module map).

## Testing

There is no test runner and no linter. Verify a change by running the batch tests that cover it, and say which
ones you ran.

```bash
# batch test (Git Bash); most tests take inputs and OUT from the environment, see the header of each script
OUT=/d/tmp/out /d/KLayout/klayout_app.exe -z -nc -rx -r tests/test_export.py
```

- Two kinds of tests, run differently:
  - Tests that add the repo's `python/` to `sys.path` (all that need the PDK, plus `test_export`, `test_simcfg`,
    `test_portlayers`, `test_circuit`, `test_open_with`): run them with `KLAYOUT_PATH` and `KLAYOUT_HOME` pointing to an empty
    folder, so a user-installed sg13g2 technology does not collide (see `klayout_em_export_tests/run_all.sh`). The
    PDK comes from `../klayout_em_export_tests/pdk_env.py`, a sparse checkout made by its `setup_pdk.sh`.
  - The others (`test_boundary`, `test_ground`, `test_locate`, `test_numbering`, `test_panel`, `test_ports`,
    `test_reopen`, `test_selection`) import the plug-in from KLayout's salt folder: run them with the normal
    KLayout home. With an empty home they fail with `No module named 'klayout_em_export'`.
  - The tests print `ok`/`FAIL` lines or plain results; there are few asserts. Compare the output with an earlier
    run rather than relying on the exit code.
- Several tests read layouts outside the repo. `tests/testpaths.py` finds them: `KLAYOUT_EM_EXPORT_TESTDATA` names a
  folder with `Palace_testcases/` and `klayout_em_export_tests/` (on hpz2: `~/klayout_em_export_testdata`), unset
  it is `D:\Palace_testcases` and the `klayout_em_export_tests` folder next to this repo. `GDS2PALACE` names the
  gds2palace repo (default: next to this repo), `OUT` the output folder (default: a temp folder). New tests use
  these helpers, never a fixed path.
- Anything with mouse, dialogs or the panel in the real window: run the guide capture
  (`klayout_app.exe -r doc/userguide/capture/capture.py`, without `-z`/`-rx`) and look at the screenshots, or
  write a small GUI script that sends Qt events to the canvas (`pya.QApplication.widgetAt` finds it). Batch mode
  cannot test them: `select_from` selects nothing and there is no main window.
- The capture backs up and restores `~/.klayout_em_export.json`. Any script of your own that calls
  `gui.set_stackup` or other setters writes to that file: back it up and restore it.
- Physics claims (resistances, S-parameters, DC points) need a simulation, not an estimate. Palace runs on the
  Linux host `hpz2`: at most 16 MPI processes in total, runs under `~/palace_runs/<study>/`. Circuit simulators run
  in the IIC-OSIC-TOOLS Docker image there (`tests/simulators/README.md`).

## KLayout 0.29 pitfalls

These crash KLayout without a Python error, or behave differently in the GUI:

- An object from `Region.each()` or `Edges.each()` points into the collection. Use it inside the loop or copy it
  with `.dup()`; `next(region.each())` kept for later crashes.
- Two `shape.set_property()` calls in a row work on a stale shape. Set all properties at insertion:
  `shapes.insert(box, layout.properties_id([[k1, v1], [k2, v2]]))`.
- `view.transaction()` on a standalone `pya.LayoutView` in batch mode crashes (no undo manager): tests use a
  stand-in object with `transaction`, `commit`, `add_missing_layers`.
- A standalone `LayoutView()` is read-only; use `LayoutView(True)` to edit.
- For an instance selected in the GUI, `ObjectInstPath.trans()` leaves out the instance's own transformation;
  build the placement from `each_inst()` (`selection.instance_trans`).
- `pya.Plugin` callbacks must have KLayout's exact names (`mouse_moved_event`, `mouse_click_event`, ...). A
  misspelled one is never called and raises no error: the hover preview was dead for that reason. Mouse moves
  reach the active tool twice, with `prio=True` and then `prio=False`.
- Qt getters are sometimes properties, sometimes methods (`panel._get` accepts both). `self.layout` in a
  `QDialog` subclass clashes with `QWidget.layout`. `LayoutView.message` does not exist: use
  `MainWindow.message(text, ms)`.
- GDS keeps only integer property keys. Persisted meta info does not mark the layout as modified, so it is mirrored
  into the settings file (`gui.set_layout_value`).

## Rules that protect design decisions

The reasons are in ARCHITECTURE.md section 7. Do not change these without asking the user:

- Port settings format (property 200) and the property keys 200, 201, 202: saved layouts depend on them.
- Port layers 201..299 minus the stackup's own layers; exported ports numbered 1..N without gaps.
- Via port direction chosen at the export so every signal metal is on the same end; the port map fields
  (`direction`, `net`, `signal_layer`, `device`, `terminal`) that `tools/spice_wrapper.py` reads.
- One REF patch per device, sized to its pins; the reference plane at the pcell's pins.
- Wrapper: devices wired directly to the EM pins, 1 mH ties per net, DC blocks only without a 0 Hz point.
- Resistors replaced by default.
- The `.simcfg` is setupEM's format: re-export must keep setupEM's own settings.

If you change the port map or `.simcfg` content, check setupEM and `tools/spice_wrapper.py` together, and the
cascode test (`tests/run_cascode_export.py`, `tests/simulators/`).

## Documentation

- Behaviour changes go into the README and, where a designer sees them, the user's guide. Design decisions with
  their reasons go into doc/ARCHITECTURE.md.
- User's guide: written for RFIC designers who never used the plug-in. Each chapter starts with "In this chapter"
  and "Why it matters"; short sentences; physical reason first; designer vocabulary, not solver jargon.
- After a GUI change, recapture the screenshots and rebuild the PDF:

  ```bash
  /d/KLayout/klayout_app.exe -r doc/userguide/capture/capture.py      # writes doc/userguide/images
  /d/venv/palace/Scripts/python doc/userguide/capture/set_dpi.py
  /d/venv/openems/Scripts/python doc/userguide/capture/build_pdf.py   # the PDF, with this repo's figure sizes
  ```

  Check the result as rendered pages, not only the Markdown. `build_pdf.py` runs the shared
  `doc/pdf_build/build_userguide_pdf.py` on a copy of the Markdown with explicit figure widths: 70% of the builder's
  size, except the layout views and the first main window shot. Don't call the builder directly.
- Linux edition (`klayout_em_export_userguide_linux.md`/`.pdf`): generated from the main guide by
  `doc/userguide/capture/linux_guide.py --pdf`, with the screenshots in `images_linux/` (capture.py and
  capture_setupem.py run on Linux with `SHOTS`/output folder `images_linux`, paths from the environment, see the
  header of capture.py). Never edit the Linux .md by hand; rerun the script after editing the main guide.
- Layout screenshots for docs: `gds_viewer --screenshot` (sibling repo), not ad-hoc matplotlib.
- Never invent a number or a physical property: trace it to the PDK, a simulation or a citation, or leave it out.
- No results from commercial EM tools (e.g. ADS) in this repo, its docs or commit messages.
