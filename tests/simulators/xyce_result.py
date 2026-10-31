import sys
import numpy as np
x = sys.argv[1]
try:
    op = np.genfromtxt(f"{x}_op.csv", delimiter=",", names=True)
    n = op.dtype.names
    line = f"RESULT {x} Icc {-float(op[n[0]]) * 1e3:.2f} mA Ibias {-float(op[n[1]]) * 1e6:.1f} uA"
    ac = np.genfromtxt(f"{x}_ac.csv", delimiter=",", names=True)
    m = ac.dtype.names
    s21 = 20 * np.log10(np.abs(2 * (ac[m[1]] + 1j * ac[m[2]])))
    line += "  S21 10 GHz %.2f dB, 100 GHz %.2f dB" % tuple(np.interp([10e9, 100e9], ac[m[0]], s21))
    print(line)
except Exception as e:
    print("RESULT", x, "failed:", e)
