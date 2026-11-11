# What's new

## 0.3.1 (11 November 2026)

Split regions with port walls need gds2palace 0.10.1 and setupEM 0.18.1 or newer (both on PyPI): with older
versions, a side of the region made a port wall in setupEM after the export was a plain PEC wall in every piece
and in the full model, and a wide cut across many lines got long standards and a low frequency limit.

**Fix:** stackups that write the layer type in another case, e.g. `Type="Conductor"` in a PCB stackup, now work:
the plug-in read only `conductor`, found no metals, and the panel failed on every refresh with
"min() iterable argument is empty" (the Devices and Ports lines showed "no layout loaded"). The layer type and
`ReferenceEdge` are now read in any case, as gds2palace does. A stackup without any conductor lists no devices
instead of failing.

## 0.3.0 (10 November 2026)

First version in KLayout's package manager (Tools > Manage Packages).

**Split a large region into pieces.** Several EM region boxes on 800/0 that share edges form one region in pieces.
Each piece is simulated as its own model, and setupEM joins the results into one result of the whole region; after
a change, only the changed pieces are simulated again. **Split Region** cuts a box at a click, **Import Pieces...**
takes the boxes and ground marks from an earlier export. Needs gds2palace 0.10.0 and setupEM 0.18.

**Port walls.** **Create Proposed Ports** with **as port walls** puts in-plane ports where lines cross the region
edge; gds2palace calibrates them with the reference plane on the wall. The ports at a cut between pieces are always
port walls.

**Draw Region tool:** drag a rectangle as the EM region box; Shift+drag adds a piece.

**Ground tool:** a click on a metal marks it as ground, through the cell hierarchy, every part of it inside the box.

**Devices:** only the devices in the EM region box are listed and replaced. The device table's right-click menu
replaces or puts back the selected devices only, e.g. to leave a device off the EM signal path as drawn. Static
MOSFETs (drawn without a pcell) get their size from the drawn gates.

**Ports:** the ports table's right-click menu moves a port up or down in the numbering or gives it another number.

**EM menu by workflow step** (Clean Up Layout, Region, Ground, Ports, Thermal). The EM tool icons are in the toolbar
only while the EM panel is open.

**Create Circuit** presets the PDK folder, the EM result (the calibrated one with port walls, the joined one for a
split region) and the Python with snp2le.

**Thermal export (experimental)** for setupThermal: transistors and resistors as heat sources, with schematic
instance names from an LVS database; the panel switches between **EM** and **Thermal**. The export keeps the
layout's datatypes, not only 0.

**Examples:** `examples/` has the user's guide's cascode, with its EM result to try Create Circuit, and a split
region with port walls and reference results. New: an FAQ for designers.

**Removed:** opening an export in EMStudio, until EMStudio has the `.simcfg` import; the Linux edition of the user's
guide.
