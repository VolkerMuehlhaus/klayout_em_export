# klayout_em_export

KLayout plug-in that exports part of a layout for EM simulation with
[gds2palace](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2) and hands it to setupEM. Work in progress.

## Installation (development)

Link the repo into KLayout's package folder, then restart KLayout (Windows, PowerShell):

```powershell
New-Item -ItemType Junction -Path "$HOME\KLayout\salt\klayout_em_export" -Target <path to this repo>
```

KLayout adds `python/` to its module path and runs `pymacros/em_export_menu.lym` at startup.

## Usage: EM panel and EM menu

The **EM panel** is docked at the right of the main window (opens at startup; menu **EM > EM Panel** brings it
back). It shows the whole workflow in one place:

- **Stackup** of the current layout, with Change....
- **Ports** of the current cell: number, layer, direction, layers, Z0 and status ("ok", the problems, or "not in
  .simcfg" for incomplete ports). Click a row to select the port in the layout (and bring it into view),
  double-click or **Settings...** to edit it, **Delete** to remove its shapes. **EM Port tool** starts the tool.
  Ports drawn with KLayout's own tools appear on **Refresh**.
- **Ground**: the ground net, traced through the vias in the EM region box (or the whole cell). **Check** outlines
  it in the layout and reports which via ports reach it and how many other separate nets there are.
  - The ground is found from the via ports: of the nets at both ends of the via ports, the one most ports reach (on
    a tie, the larger one). Which end is from and which is to does not matter.
  - **Mark Selected** marks the selected metal shapes as ground instead (stored in the layout); **Use Ports**
    forgets the marks.
  - Only wiring is traced: the stackup's conductors above the device level, connected by the vias between
    vertically adjacent metals (from the stackup's z positions). Activ, Cont, resistors and the PEC sheets are left
    out, so a transistor or resistor is an open circuit here. Ground that is joined only outside the region shows
    up as separate pieces.
- **Export**: what the export will use right now (the selection, the EM region box, or the whole cell), with
  **Mark Region**, **Export for EM...** and **Open in setupEM** (the last export of this layout, without exporting
  again).

The same steps are in the **EM** menu in the menu bar, top to bottom in workflow order:

1. **Choose Stackup...**: the gds2palace stackup XML for this layout. It is chosen once and used by every step. It
   is stored in the layout (meta info, saved with it) and as the default for other layouts. The port dialog and the
   export dialog show it and can change it too.
2. **EM Port Tool** (also in the toolbar as "EM Port"): click a metal edge to create a via port, a zero-width line
   along that edge; Shift+click into the gap between two shapes of one metal to create an in-plane port, a box that
   bridges the gap. The edge or gap under the cursor is highlighted first. The shape goes on the next free port
   layer (port number = layer - 200), then the port dialog opens; Cancel removes the shape again.
3. **Port Settings...**: the same dialog for selected port shapes (layers 201..299, datatype 0; from the tool or
   drawn with KLayout's own tools): direction, from/to layer (via port, Z/-Z) or target layer (in-plane port), Z0
   and excitation.
   - Shows which stackup metals are drawn at the port and offers only those, unless "offer all stackup metals" is
     ticked. New via ports default to from = lowest, to = highest metal at the port.
   - The settings are stored on the shape as GDS property 200, e.g. `port:dir=-Z;from=Metal3;to=TopMetal2;z0=50;v=1`,
     so they are saved with the layout.
4. **Port Overview**: all ports of the current cell with their settings and problems.
5. **Mark EM Region from Selection**: draws the bounding box of the selected shapes on layer **800/0**, replacing an
   earlier box. Saved with the layout, it gives the same region on the next export.
6. **Export for EM...**: one dialog with everything about the export, then one click.
   - With a selection: "Selected shapes only (+ connecting vias and ports)", the default, exports just the selected
     shapes, uncut. It adds what is easy to miss when selecting: the vias that land on two selected metals, and the
     port shapes that touch selected metal; the dialog lists what was added. "Everything inside the selection's
     bounding box" exports all stackup layers inside that box, cut at the box. Selected instances count with all
     their shapes.
   - Without a selection: everything inside the box on layer 800/0, else the whole cell.
   - Stackup (Change...), output GDS (Browse...; default `<layout>_em.gds`, then the last output of this layout).
   - The ports with their problems. Ports without complete settings are exported as shapes but left out of the
     `.simcfg`, because setupEM cannot load them. Only the stackup's layers are exported; the others are dropped.
   - "Open in setupEM after the export". The `.simcfg` is written next to the GDS.
   - Exporting again updates an existing `.simcfg`: the GDS file, stackup, cell and ports are set, everything
     else (frequencies, mesh, ... saved with setupEM's Save Config) is kept. The ports always come from the
     layout, where they are defined.

Remembered in `~/.klayout_em_export.json`: the last stackup, the last port settings, the setupEM program and the
setupEM option; and per layout file its stackup, last export and ground marks. These are also stored in the layout
itself (saved with it), but storing them does not mark the layout as modified, so the settings file keeps them
when the layout is closed without saving. If `setupEM` is not on the `PATH` that KLayout sees, the plug-in asks once for the program (e.g.
`<venv>\Scripts\setupEM.exe`).

## Modules

- `stackup.py`: reads a gds2palace stackup XML. It finds the GDS layers the EM model reads, with derived layers (such
  as the SG13G2 resistors) replaced by their source layers. It also lists the metal names for port dialogs.
- `export.py`: writes one flat cell with only those layers and the port layers 201..299, optionally clipped to a box.
  Metal is merged per layer. Port shapes are copied unchanged, so zero-width via-port lines survive. Every layer or
  purpose that is left out is reported.
- `simcfg.py`: writes a setupEM settings file (`.simcfg`) with the GDS file, stackup, cell and ports. setupEM takes
  all other settings from its preferences.

## Tests

KLayout batch mode (`klayout_app.exe -z -nc -rx -r tests/test_export.py`), environment `GDS`, `STACKUP`, `OUT` and
optionally `BOX="x1,y1,x2,y2"` (um).
