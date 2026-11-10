# AGENTS.md

Rules for AI agents developing klayout_em_export. Read [doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) first: module map,
data formats, and the design decisions with their reasons. The user-facing behaviour is in
[doc/REFERENCE.md](doc/REFERENCE.md) and the [user's guide](doc/userguide/klayout_em_export_userguide.md).

## Repository and git

- Original repo `VolkerMuehlhaus/klayout_em_export` (private), remote `upstream` with its push URL set to `DISABLED`.
  All work goes to the fork `volkermuehlhaus-claude/klayout_em_export`, remote `origin`; a PR from the fork to the
  original only when the user asks for it.
- Local git identity: `volkermuehlhaus-claude`, `claude@muehlhaus.com`. Commit or push only when the user asks.
- Working copies have CRLF line endings (`core.autocrlf`). `*.sh` files stay LF (`.gitattributes`), because
  `tests/simulators/run.sh` runs on Linux.

## Where the code runs

- `python/klayout_em_export/` runs inside KLayout's Python: `pya` and the standard library only. Do not import
  gdspy, numpy, shapely or anything else that KLayout's Python lacks.
- `tools/spice_wrapper.py` runs outside KLayout, in a Python with snp2le.
- For development, link this repo into KLayout's `salt` folder (see the README). An
  edit takes effect when KLayout restarts (autorun macro at startup); batch tests import the current files.
- Keep core modules free of GUI code, so batch tests can drive them. Dialogs and the panel only collect input and
  call the core (see the module map).

## Testing

There is no linter. Verify a change by running the batch tests that cover it, and say which ones you ran.

```bash
python tests/run_all.py                 # all tests, one table (about 3 minutes)
python tests/run_all.py thermal panel   # the tests whose name contains one of the words
```

- `run_all.py` runs each test in KLayout batch mode with an empty KLayout home, so a user-installed sg13g2 technology
  does not collide, and with the repo's `python/` and `tests/` on the path. A missing input file is SKIP.
- The tests print `ok`/`FAIL` lines or plain results; there are few asserts. Compare the output with an earlier run
  when a test prints plain results.
- The tests that recognize devices need the PDK: `tests/setup_pdk.sh` makes a sparse checkout in `tests/pdk`, or
  `IHP_PDK_ROOT` names a folder that contains `ihp-sg13g2`.
- Layouts are in `tests/data`. Two large ones are not in the repo; `KLAYOUT_EM_EXPORT_TESTDATA` names
  a folder with `Palace_testcases/klayout_export/` that holds them. `GDS2PALACE` names the gds2palace repo (default:
  next to this repo), `OUT` the output folder (default: a temp folder). New tests use the helpers in
  `tests/testpaths.py`, never a fixed path.
- `examples/` is for users, not for the tests: the guide's cascode (`tests/data/1_St_Core_v1_forEM.gds` without the
  plug-in's path meta info) with the port map and Palace result of the guide's export, and a prepared split region
  (two inductors, from the split region validation) with reference results. No machine paths in the layouts' meta
  info (stackup, last export). If the guide's port numbering changes, the cascode's `em_result/` no longer fits.
  Its README reuses the guide's images for the cascode; the split region images come from
  `doc/userguide/capture/capture_examples.py` (KLayout, -r), `capture_setupem_set.py` (setupEM, on that export) and
  `plot_examples.py` (plot_snp).
- The headless interface (`cli.py`, `tools/em_cli.py`): `test_cli.py` drives every command in batch mode. After a
  change to the export, the ports or the devices, also run one command end to end through the launcher
  (`python tools/em_cli.py status gds=... stackup=...`), which starts KLayout with `-zz -nc -rx`. New workflow logic
  goes into `pipeline.py` or the core modules, not into `gui.py`, so the GUI and the CLI stay the same.
- Anything with mouse, dialogs or the panel in the real window: run the guide capture
  (`klayout_app.exe -r doc/userguide/capture/capture.py`, without `-z`/`-rx`) and look at the screenshots, or
  write a small GUI script that sends Qt events to the canvas (`pya.QApplication.widgetAt` finds it). Batch mode
  cannot test them: `select_from` selects nothing and there is no main window.
- The capture backs up and restores `~/.klayout_em_export.json`. Any script of your own that calls
  `gui.set_stackup` or other setters writes to that file: back it up and restore it, or set
  `KLAYOUT_EM_EXPORT_SETTINGS` to a file of its own (`tests/run_all.py` gives every test a fresh one, so the user's
  remembered choices, such as the panel left in thermal mode, can't change a test).
- Physics claims (resistances, S-parameters, DC points) need a simulation, not an estimate. Circuit simulators run
  in the IIC-OSIC-TOOLS Docker image (`tests/simulators/README.md`).

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
- KLayout 0.30.12 deletes a widget or layout handed to `QFormLayout.addRow` once Python no longer refers to it
  (0.30.5 kept it): rows vanished and a combo box covered the whole Export dialog. Add form rows with
  `gui.add_form_row(dialog, form, ...)`, which keeps them in the dialog. `addWidget` / `addLayout` of box layouts
  keep their arguments (the panel is fine).
- Undo steps in KLayout 0.29.4 (0.30.12 is fine):
  - `view.add_missing_layers()` after `view.commit()` clears the whole undo list when the step created a layer:
    Replace All, boundary ports and Mark Region could not be undone. Call it before `commit()`.
  - After Undo and Redo of a step that created a layer, the next new layer gets the same layer index: Mark Region
    then cleared the REF patches. Create new layers before the step opens (`locate.create_layers`).
  - Do not nest undo steps: a function that opens its own step must not run inside another one.
- KLayout 0.30.12's `Region.each()` yields `PolygonWithProperties`, whose `str()` ends in ` props={}`: a
  `str(polygon)` key never matches the plain `Polygon` it came from (Remove Dummy Fill removed nothing). Use
  `dummyfill._key`.

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

- Behaviour changes go into doc/REFERENCE.md and, where a designer sees them, the user's guide. The README stays
  short: what it is, status, install, limits. Design decisions with
  their reasons go into doc/ARCHITECTURE.md.
- User's guide: written for RFIC designers who never used the plug-in. Each chapter starts with "In this chapter"
  and "Why it matters"; short sentences; physical reason first; designer vocabulary, not solver jargon.
- After a GUI change, recapture the screenshots and rebuild the PDF:

  ```bash
  klayout_app -r doc/userguide/capture/capture.py      # writes doc/userguide/images
  python doc/userguide/capture/set_dpi.py              # a Python with Pillow
  python doc/userguide/capture/build_pdf.py            # the PDF, with this repo's figure sizes; a Python with typst
  ```

  Check the result as rendered pages, not only the Markdown. `build_pdf.py` runs the shared
  `doc/pdf_build/build_userguide_pdf.py` on a copy of the Markdown with explicit figure widths: 70% of the builder's
  size, except the layout views and the first main window shot. Don't call the builder directly.
- Layout screenshots for docs: `gds_viewer --screenshot` (sibling repo), not ad-hoc matplotlib.
- Never invent a number or a physical property: trace it to the PDK, a simulation or a citation, or leave it out.
- No results from commercial EM tools in this repo, its docs or commit messages.
