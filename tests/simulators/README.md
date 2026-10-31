# The circuit wrapper in ngspice, Xyce and VACASK

`run.sh` wraps the cascode test's EM result with `tools/spice_wrapper.py` for each simulator and runs the same
testbench in each: operating point and S21 from the Cas_in pad to the Cas_out pad. Spectre is written too, but not
run (no license).

It runs in the [IIC-OSIC-TOOLS](https://github.com/iic-jku/IIC-OSIC-TOOLS) image, which has ngspice, Xyce, VACASK,
snp2le and the IHP SG13G2 PDK with models for all three. Put the export's port map and the Palace `_dc` file in
this folder, then:

```bash
docker run --rm --user $(id -u):$(id -g) -e HOME=/w -v $PWD:/w -v <repo>/tools:/wrapper -w /w \
    --entrypoint bash hpretl/iic-osic-tools:latest -lc \
    "PM=cascode_em_portmap.json SNP=cascode_dc.s15p ./run.sh"
```

Result on 2026-10-31 (image of mid-October 2026: ngspice-47, Xyce 7.10, VACASK fb8cc20, snp2le 0.1.17):

| | Icc | Cas_Bias | S21 at 10 GHz | S21 at 100 GHz |
| --- | --- | --- | --- | --- |
| ngspice, snp2le model | 11.34 mA | 127.4 µA | 21.62 dB | 7.89 dB |
| VACASK, snp2le model | 11.33 mA | 127.5 µA | 21.62 dB | 7.88 dB |
| Xyce, snp2le model | 11.33 mA | 127.5 µA | 21.63 dB | 8.38 dB |
| Xyce, the .sNp (YLIN) | 11.33 mA | 127.4 µA | — | — |

- **Xyce at 100 GHz:** the snp2le model alone reproduces the S-parameters in Xyce within 0.001. The 0.5 dB comes
  from Xyce's npn13G2 model in the PDK (VBIC 4T, some parameters ignored), not from the wrapper.
- **Xyce's YLIN element** reads the .sNp and works in harmonic balance (checked: S11 and S21 of the EM model at
  1 GHz equal the file), but in the AC and DC analyses of Xyce 7.10 it is an open circuit. The bias still works,
  through the 1 mH ties.
