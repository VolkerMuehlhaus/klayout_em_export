#!/bin/bash
# Run inside the IIC-OSIC-TOOLS image (see README.md): the cascode wrapped for ngspice, Xyce and VACASK.
# PM and SNP: the port map and the _dc.sNp, in this folder; W: tools/spice_wrapper.py.
set -u
export PDK=ihp-sg13g2
P=$PDK_ROOT/ihp-sg13g2
W=${W:-/wrapper/spice_wrapper.py}
PM=${PM:-cascode_em_portmap.json}
SNP=${SNP:-cascode_dc.s15p}
python3 $W $PM $SNP -o cascode_ngspice.cir --simulator ngspice --pdk $P | tail -1
python3 $W $PM $SNP -o cascode_xyce.cir --simulator xyce --em snp --pdk $P | tail -1
python3 $W $PM $SNP -o cascode_xycefit.cir --simulator xyce --em fit --pdk $P | tail -1
python3 $W $PM $SNP -o cascode_vacask.inc --simulator vacask | tail -1
python3 $W $PM $SNP -o cascode_spectre.scs --simulator spectre | tail -1
echo "== ngspice"; ngspice -b tb_ngspice.cir 2>&1 | grep -E "^-i\(|s21_|rror" | head
for x in xyce xycefit; do
  for part in op ac; do sed -e "s/cascode_xyce.cir/cascode_$x.cir/; s/SUBCKTNAME/cascode_$x/; s/xyce_$part.csv/${x}_$part.csv/" tb_xyce_$part.tpl > tb_${x}_$part.cir; done
  echo "== $x"; rm -f ${x}_op.csv ${x}_ac.csv
  Xyce tb_${x}_op.cir > ${x}_op.log 2>&1; Xyce tb_${x}_ac.cir > ${x}_ac.log 2>&1
  grep -i -E "error|fatal" ${x}_op.log ${x}_ac.log | head -5
  python3 xyce_result.py $x
done
echo "== vacask"; cp /foss/tools/vacask/share/doc/vacask/demo/ihp-sg13g2/.vacaskrc.toml . 2>/dev/null; vacask tb_vacask.sim > vacask.log 2>&1; grep -E "RESULT|rror" vacask.log | head
