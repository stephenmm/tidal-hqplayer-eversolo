#!/usr/bin/env python3
"""Indicative BOM and factory-cost roll-up for the microphone line array.

Prices are order-of-magnitude distributor figures, NOT quotes. They are good
enough to see which lines dominate and whether the product is viable; they are
not good enough to commit money against. Re-quote before you do.

See docs/mic-line-array-design.md section 12 for what the numbers mean.

    python3 tools/mic_array_bom.py
"""
from dataclasses import dataclass

@dataclass
class Line:
    group: str; item: str; qty: int
    p1: float; p100: float; p1k: float          # unit price at qty 1 / 100 / 1000

L = [
 Line("Acoustic",  "Analog MEMS microphone, bottom port",        16, 2.60, 1.85, 1.25),
 Line("Acoustic",  "Port gasket + mesh",                         16, 0.18, 0.09, 0.05),
 Line("Preamp",    "Quad low-noise op-amp",                       4, 2.40, 1.65, 1.20),
 Line("Preamp",    "Gain resistors, 0.1% 0402",                  32, 0.09, 0.03, 0.016),
 Line("Preamp",    "Signal-path caps, C0G/film",                 32, 0.14, 0.07, 0.045),
 Line("Preamp",    "Bias + decoupling passives",                 56, 0.03, 0.012, 0.006),
 Line("Convert",   "4-channel 24-bit TDM ADC",                    4, 6.20, 4.60, 3.60),
 Line("Convert",   "ADC support passives + AA filters",          88, 0.03, 0.012, 0.006),
 Line("Convert",   "Low-jitter 24.576 MHz oscillator",            1, 3.40, 2.30, 1.70),
 Line("Convert",   "Stereo 24-bit DAC",                           1, 5.60, 4.10, 3.20),
 Line("DSP",       "SHARC+ / xcore.ai class DSP",                 1, 28.00, 20.00, 14.50),
 Line("DSP",       "QSPI boot flash, 16 Mb",                      1, 1.10, 0.72, 0.52),
 Line("DSP",       "I2C EEPROM 64 kB (calibration)",              1, 0.60, 0.40, 0.28),
 Line("DSP",       "DSP support passives",                       64, 0.03, 0.012, 0.006),
 Line("Output",    "Balanced line driver",                        1, 4.80, 3.40, 2.60),
 Line("Output",    "DC-block film caps + output network",        16, 0.22, 0.12, 0.08),
 Line("Output",    "Phantom protection (TVS, series R, clamps)", 12, 0.11, 0.05, 0.03),
 Line("Power",     "Isolated +/-12 V DC-DC, 2 W",                 1, 11.00, 8.20, 6.30),
 Line("Power",     "Low-noise analogue LDO",                      4, 1.00, 0.68, 0.48),
 Line("Power",     "Digital buck converter",                      1, 1.80, 1.20, 0.85),
 Line("Power",     "Digital LDO",                                 1, 0.45, 0.28, 0.19),
 Line("Power",     "Bulk caps, inductors, ferrites",             62, 0.06, 0.03, 0.018),
 Line("Connector", "XLR male panel connector",                    1, 3.60, 2.60, 1.95),
 Line("Connector", "RCA jack",                                    1, 0.90, 0.58, 0.40),
 Line("Connector", "DC input jack",                               1, 1.10, 0.70, 0.48),
 Line("Connector", "Debug / programming header",                  1, 0.55, 0.30, 0.20),
 Line("PCB",       "545 x 45 mm 4-layer ENIG (245 cm^2)",         1, 62.00, 19.00, 11.50),
 Line("Mech",      "Extruded alu enclosure, machined ports",      1, 78.00, 41.00, 26.00),
 Line("Mech",      "End caps, mounts, fasteners, damping",        1, 14.00, 7.50, 4.80),
]

def roll(attr):
    tot = {}
    for l in L:
        tot[l.group] = tot.get(l.group, 0.0) + l.qty * getattr(l, attr)
    return tot

print(f"{'GROUP':<11}{'qty 1':>10}{'qty 100':>10}{'qty 1000':>10}")
print("-" * 41)
t1, t100, t1k = roll("p1"), roll("p100"), roll("p1k")
for g in dict.fromkeys(l.group for l in L):
    print(f"{g:<11}{t1[g]:>10.2f}{t100[g]:>10.2f}{t1k[g]:>10.2f}")
print("-" * 41)
s1, s100, s1k = sum(t1.values()), sum(t100.values()), sum(t1k.values())
print(f"{'BOM total':<11}{s1:>10.2f}{s100:>10.2f}{s1k:>10.2f}")
print(f"{'parts':<11}{sum(l.qty for l in L):>10d}   placements (excl. enclosure/PCB): "
      f"{sum(l.qty for l in L if l.group not in ('PCB','Mech','Acoustic') or l.item.startswith('Analog')):d}")
print()
# assembly + test adders
for name, qty, asm, test in (("qty 1", 1, 0.0, 0.0), ("qty 100", 100, 9.50, 7.00),
                             ("qty 1000", 1000, 5.80, 4.20)):
    base = {"qty 1": s1, "qty 100": s100, "qty 1000": s1k}[name]
    print(f"{name:<9} BOM {base:7.2f} + assembly {asm:5.2f} + test/cal {test:5.2f} "
          f"= factory cost {base+asm+test:7.2f}")
