# What's new

## Next release

**Faster with large layouts:** after a layout was opened, the EM panel's checks could take much longer than reading
the file (a 10 MB PA layout with fill: 0.1 s to read, 9 to 13 s of checks), and they ran for every layout opened
after an EM export, because the last stackup used applies to every layout. Now:

- **Closing the EM panel switches EM off**: no checks at all, and the panel stays closed at the next KLayout start
  until EM > EM Panel opens it.
- **A layout opened for other work is not checked**: no region box, no ports in its cell, no ground marks, and its
  stackup only the last one used. Ground and Devices say "not checked: no EM setup in this layout yet"; choosing the
  stackup, drawing a region or port, or Run Checks start the checks.
- **The checks themselves are faster**, with the same results: each cell is identified as a device once, not each
  of its instances (681,000 instances of 74 cells in the PA layout); the scan for the tags of replaced devices reads
  only shapes with properties; tracing a device terminal copies the metal of a layer only when it gets there. The
  PA layout: 3.5 s instead of 12.9 s, a 14 MB layout with fill 2.2 s instead of 5.0 s, a 65 MB RF front end
  15 s instead of 20 s (most of it the ground tracing of the large region).

**Fix: an exported EM model opened in KLayout.** The export removes the replaced devices and keeps their ports, with
the tags that name the device. Opened in KLayout, such a file showed "ports of N device(s) no longer there" and
advised Undo Replace, which would have deleted the device ports from the model. A layout that is the GDS file of its
own `.simcfg` and has device ports but none of their devices is now recognised as an exported model: the Devices step
says "exported EM model: N device(s) replaced by M port(s)", and Replace All and Undo Replace are off.

**Fix:** relative paths in a `.simcfg` or `.tsimcfg` (GdsFile, SubstrateFile; the export writes them relative) are
now read relative to that file, as setupEM reads them. Before, they were relative to KLayout's working directory, so
the layout's own setup file and its stackup were only found when KLayout was started in that folder.

**Documentation:** gds2palace 0.10.7 changed the frequencies that replace DC in a sweep from 0 Hz: still 10 MHz and
20 MHz for most models, higher for a mesh finer than 0.5 µm (5 MHz·µm divided by the smallest cell size). The user's
guide, `REFERENCE.md`, `ARCHITECTURE.md` and the description at the top of `tools/spice_wrapper.py` said 10 MHz and
20 MHz as a fixed fact and now say "normally". The cascode test report notes that gds2palace 0.10.7 no longer resamples the `_dc`
file.

## 0.3.2 (13 November 2026)

**Fix:** a short circuit at a via port, and ground at a cut of the EM region box, are now judged near the port
(within 10 µm, or the port's own length if that is longer). Before, any connection through the layout counted: a
balun or inductor winding grounded at its other end was "ground" at the cut and got no proposed port, and a port
drawn on it was reported as a short circuit. At RF the winding is an inductance; such a cut now gets a proposed port
("signal (grounded only away from the cut)"), a port on it is not reported, and its signal end (port map, direction)
is the winding, not the ground plane.

**Fix:** a side of the region that was a port wall in the `.simcfg` but has no in-plane port any more (the ports
were changed to via ports) stayed a port wall after the export, and gds2palace stopped with "port wall ... has no
port". The export now takes the port wall off: the side gets the boundary, dielectric margin and air of the other
sides again, and its port wall extension and reference plane shift are removed.

Related fixes outside the plug-in: port walls with the conformal passivation stackup
(`SG13G2_FEM_200um_passi3D.xml`) need gds2palace 0.10.5 (the passivation reached past the cut and moved the wall
away from the ports); a model script opened on another machine (Windows and Linux in turn) keeps the paths
setupEM shows, from setupEM 0.18.2.

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
