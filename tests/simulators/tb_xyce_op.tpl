* cascode testbench (Xyce, operating point)
.include cascode_xyce.cir
Vcc vcc 0 2.5
Lc vcc port1 1u
Cout port1 out 10p
Rl out 0 50
Vb vb 0 0.9
Lb vb port2 1u
Vin src 0 dc 0 ac 1
Rs src in 50
Cin in port2 10p
Vbias port15 0 1.9
X1 port1 port2 port15 SUBCKTNAME
.dc Vcc 2.5 2.5 1
.print dc format=csv file=xyce_op.csv i(Vcc) i(Vbias)
.end
