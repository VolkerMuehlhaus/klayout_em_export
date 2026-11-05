# Test layouts

Inputs of the batch tests, found through `tests/testpaths.py`.

| File | What it is | Used by |
| --- | --- | --- |
| `1_St_Core_v1.gds` | Cascode core: two npn13G2 and three resistors | device, resistor and technology tests |
| `1_St_Core_v1_forEM.gds` | The same cascode, prepared for the EM export; the source of the guide's example | CLI, thermal, unconnected-terminal tests, guide capture |
| `1_St_Core_v1_em.gds`, `.py`, `.simcfg` | An export of the cascode and the setupEM model script made from it | `test_modelcheck.py` |
| `cascode.gds` | The cascode as saved by the guide's capture script | `test_replaced_devices.py`, `tests/resistor_palace` |
| `lvs_cascode/` | KLayout LVS databases and netlists of the cascode (flat and with a subcircuit) | `test_thermal.py`, `test_panel_thermal.py`, `test_cli.py` |
| `50_ghz_mpa_core.gds` | Power amplifier core with npn devices | `test_devices.py`, `test_reopen.py`, `test_unconnected.py` |
| `OctaDiffTap_0n50_ports3.gds` | Octagon inductor with ports | export, ground, boundary and locate tests |
| `BM_Ardavan_Rahimian_with_ports_partial.gds` | Part of the W-band Butler matrix by Ardavan Rahimian, with ports and an EM region box. From [IHP-GmbH/TO_July2025](https://github.com/IHP-GmbH/TO_July2025/tree/main/W_Band_Butler_Matrix_IC) (Apache-2.0) | `test_numbering.py`, `test_panel.py` |
| `t1_test.gds` | Six MOSFET variants with gate contacts and Metal2 straps, built from the PDK pcells | `test_mosfets.py` |

The large-layout parts of `test_density.py` and `test_dummyfill.py` need layouts that are not in the repo. They skip
without them (see `tests/testpaths.py`).
