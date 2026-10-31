# klayout_em_export

KLayout plug-in that exports part of a layout for EM simulation with
[gds2palace](https://github.com/VolkerMuehlhaus/gds2palace_ihp_sg13g2) and hands it to setupEM. Work in progress.

**User's guide** for RFIC designers, step by step with screenshots: [doc/userguide](doc/userguide/klayout_em_export_userguide.md) ([PDF](doc/userguide/klayout_em_export_userguide.pdf)).

## Installation (development)

Link the repo into KLayout's package folder, then restart KLayout (Windows, PowerShell):

```powershell
New-Item -ItemType Junction -Path "$HOME\KLayout\salt\klayout_em_export" -Target <path to this repo>
```

KLayout adds `python/` to its module path and runs `pymacros/em_export_menu.lym` at startup.

## Usage: EM panel and EM menu

The **EM panel** is docked at the right of the main window (opens at startup; menu **EM > EM Panel** brings it
back). It is a checklist in workflow order: each step is one line with a status mark (OK, warning, error) and a
summary; the arrow shows its details and buttons.

- **Stackup** of the current layout (details: Change...).
- **Region**: what the export uses right now, following the selection: the bounding box of the selection, else
  the EM region box (layer 800/0), else the whole cell. A selection of port shapes only does not count (details:
  Mark Region from Selection).
- **Ground**: the ground net, traced through the vias in the EM region box (or the whole cell). It is checked on
  every refresh (a very large region: Run Checks in the details).
  - The ground is found from the via ports: of the nets at both ends of the via ports, the one most ports reach (on
    a tie, the larger one). Which end is from and which is to does not matter.
  - Details: **Mark Selected** marks the selected metal shapes as ground instead (stored in the layout), **Use
    Ports** forgets the marks, **Show in Layout** outlines the ground net.
  - Only wiring is traced: the stackup's conductors above the device level, connected by the vias between
    vertically adjacent metals (from the stackup's z positions). Activ, Cont, resistors and the PEC sheets are left
    out, so a transistor or resistor is an open circuit here. Ground that is joined only outside the region shows
    up as separate pieces.
- **Devices**: PDK transistors (npn13G2, npn13G2L, npn13G2V, nmos, pmos and their HV and rf variants) and resistors
  (rsil, rppd, rhigh) found in the cell, and whether they are replaced by ports. Recognized as SG13_dev pcells, or
  as static device cells exported from Cadence (`<device>_CDNS_<number>`, same pins, no parameters: the resistor
  value label is shown instead). The reference plane is at the pcell's pins: the device model
  (circuit simulator) covers the device up to its pins, the EM model everything from there on.
  - **Replace All** adds, in the layout and tagged (GDS property 202): one `REF_FOR_TRANSISTOR` patch per device,
    under its pins (their bounding box + 0.2 um; separate for devices side by side, the Devices step warns if two
    patches touch), and one via port per terminal from the pin's metal down to that patch, along
    the full pin: one port for the whole terminal (e.g. all emitter fingers). **Undo Replace** removes them again.
  - The export removes the replaced devices' own shapes below their pins: below Metal1 everywhere (Activ, Cont,
    poly, implants), and under a pin on a higher metal also the wiring down to Metal1 (the npn emitter pin is a
    Metal2 strip on one Metal1 island per finger, joined by Via1: islands and Via1 go, the emitter port runs from
    Metal2). The device's other metal stays; your own shapes are not touched.
  - nmos/pmos: their pins are unnamed (nmos) or missing (pmos), so source and drain are the device's Metal1 strips
    along the gate fingers, alternating S, D, S, ... from the left in the cell's own coordinates. A terminal on
    several fingers is one port with one line per finger: the elements of one port, in parallel. The gate pin is
    poly, below Metal1: the gate port goes on your Metal1 gate contact, found by tracing the poly from the gate
    through Cont, and the export removes that traced poly and those contacts (their resistance belongs to the
    device side).
  - Ports with several lines (multielement ports) need gds2palace 0.9.3 (branch `multi-element-ports`): it makes
    them one Palace lumped port with parallel elements. Older gds2palace versions use only one of the lines.
  - Resistors are optional: **Replace All** replaces them only with **include resistors** ticked. A replaced
    resistor gets two via ports, PLUS and MINUS, from its Metal1 heads down to its own REF patch; the export removes
    its body, contacts and implants. PLUS is the head with the lower coordinate along the resistor in the cell's own
    coordinates (the pins have no names). A resistor of several segments is not replaced. Unreplaced resistors stay
    layout: the stackup models them as sheet resistors. Capacitors (cmim) and inductors are never replaced.
  - The port map names the device and terminal of these ports, for connecting the `.snp` to the device models.
  - A terminal whose net (traced through the vias from its pin) holds only the device's own metal is reported as
    not connected to any wiring, in the Devices step and in the export dialog: it floats in the EM model, e.g. when
    the wiring to the device was cut.
  - Recognition needs the SG13G2 PDK library loaded in KLayout.
- **Ports**: one table with the ports of the cell and the ports proposed where the EM region box cuts conductors.
  - Columns: number and layer in the layout, the port, its number in the export (and the `.snp`; "outside" if it
    is not in the region), and its status: ok, its problems (incomplete, layers not drawn at the port, short
    circuit: both ends on one net), "proposed" or "cut without ground".
  - Click a row to highlight it in the layout (a marker, not a selection: a selected port would become the
    export region); double-click to edit a port or create a proposed one; right-click for Settings, Delete or
    Create.
  - **EM Port tool** starts the tool. **Create Proposed Ports** adds a via port on each signal conductor the EM
    region box cuts: a zero-width line on the box edge, from the signal metal to the ground metal at the cut (the
    closest in height), from = lower, to = upper, direction Z, Z0 50 Ohm. The export cuts the metal there, so the
    port sits exactly on the cut. These ports are tagged (GDS property 201 = "boundary"); if the box is moved,
    they are reported as no longer on the edge. Proposals need the EM region box, since the ports are drawn in
    the layout.
  - Ports drawn with KLayout's own tools appear on **Refresh**.
- **Export for EM...** and **Open in setupEM** (the last export of this layout, without exporting again).

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
   - Ports are numbered without gaps in the export: the complete ports 1..N in layout order, then the incomplete
     ones. The `.simcfg` and so the `.snp` use these numbers, the exported GDS the port layers 201.. in that order
     (without the stackup's own layers in that range, e.g. SUBGND on 210 or 250); `<name>_portmap.json` maps them
     back to the layout's port numbers (the dialog shows the map when numbers change). Reason: after Palace,
     `combine_extend_snp` takes the highest port number as the port count and fills missing ports with |S| = 1.
   - Exporting again updates an existing `.simcfg`: the GDS file, stackup, cell and ports are set, everything
     else (frequencies, mesh, ... saved with setupEM's Save Config) is kept. The ports always come from the
     layout, where they are defined.
7. **Create Circuit (EM Result with Devices)...**: after the Palace run, the EM result with the PDK devices put
   back, for ngspice, VACASK, Xyce or Spectre; see [Circuit wrapper](#circuit-wrapper-ngspice-vacask-xyce-spectre).

Remembered in `~/.klayout_em_export.json`: the last stackup, the last port settings, the setupEM program and the
setupEM option, the Create Circuit choices (Python with snp2le, PDK folder, simulator); and per layout file its stackup, last export and ground marks. These are also stored in the layout
itself (saved with it), but storing them does not mark the layout as modified, so the settings file keeps them
when the layout is closed without saving. If `setupEM` is not on the `PATH` that KLayout sees, the plug-in asks once for the program (e.g.
`<venv>\Scripts\setupEM.exe`).

## Circuit wrapper (ngspice, VACASK, Xyce, Spectre)

After the Palace run, **EM > Create Circuit (EM Result with Devices)...** turns the result into a circuit with the
PDK devices put back. Choose the port map (the last export's is preselected), the EM result (`<model>_dc.sNp`), the
simulator, optionally the IHP PDK folder, and the Python with snp2le (by default the one next to setupEM). The
dialog runs `tools/spice_wrapper.py`, which also works on its own:

```bash
python tools/spice_wrapper.py <export>_portmap.json <model>_dc.sNp -o <name>.cir --simulator ngspice --pdk <IHP-Open-PDK>/ihp-sg13g2
```

| Simulator | EM model | Device models | Tested (cascode, `tests/simulators`) |
| --- | --- | --- | --- |
| ngspice | snp2le equivalent circuit | PDK `libs.tech/ngspice` | yes |
| VACASK | snp2le equivalent circuit (VACASK format) | PDK `libs.tech/vacask`, found through its `.vacaskrc.toml` | yes, same as ngspice |
| Xyce | snp2le equivalent circuit | PDK `libs.tech/xyce` | yes; S21 0.5 dB higher at 100 GHz, from Xyce's npn13G2 model |
| Xyce | the .sNp file (`YLIN`) | PDK `libs.tech/xyce` | harmonic balance only: in AC and DC, Xyce 7.10 treats `YLIN` as open |
| Spectre | the .sNp file (`nport`) | your PDK's includes (commented placeholders) | no |

ngspice cannot use the .sNp file itself (its Touchstone support is a transfer-function element for AC, not an
N-port), and VACASK cannot yet (Touchstone import is planned).

- Start the Palace sweep at 0 Hz in gds2palace: it then simulates 10 MHz and 20 MHz and writes `<model>_dc.sNp`
  with a 0 Hz point extrapolated from them. Give the wrapper that file.
- The EM model becomes a lumped-element equivalent circuit (snp2le universal mode: vector fitted, passive, pinned
  to the 0 Hz point).
- Subcircuit `<name>`: its pins are the ports that belong to no device (pads, bias inputs); each replaced device is
  an instance of its PDK model (npn13G2 with Nx, le, we; MOSFETs with w, l, ng; resistors with w, l), its substrate or
  bulk pin to ground (pmos: to its source). A resistor from a static Cadence cell has no parameters: an ideal resistor
  of its label value, noted in the header.
- Each device terminal is wired straight to its port's pin. This grounds the device's REF patch, which floats in the
  EM model, and adds the patch's capacitance (about 7 fF per npn13G2 Nx=8). Cascode test: S21 0.06 dB lower at
  10 GHz, 0.4 dB at 200 GHz, than with the patches floating.
- DC: a port measures a voltage difference, so the EM model does not fix a device's absolute potential. The ports of
  each net (from the port map, traced through the layout's vias at the export) are tied together, and to ground on
  the ground net, by 1 mH. The wires' DC resistance is not modelled. Without a 0 Hz point in the .sNp, the equivalent
  circuit's DC is a guess of the fit, and every port gets a 1 uF DC block as well.
- The export sets each via port's direction (`Z` or `-Z`) so that every via port has its signal metal on the same
  end; the port map records it with each port's net and signal layer. Export again if the port map lacks them.
- Test report: [doc/test_cascode_wrapper](doc/test_cascode_wrapper/README.md).

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
