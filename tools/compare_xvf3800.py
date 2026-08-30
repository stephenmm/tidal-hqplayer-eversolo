#!/usr/bin/env python3
"""Compare this design against the Seeed reSpeaker XVF3800 USB 4-Mic Array.

Element coordinates are the ones Seeed publish for the XVF3800: four PDM MEMS on
a 66 mm square. Both arrays are evaluated identically - a talker in the array
plane, averaged over azimuth, superdirective weights with white-noise gain held
at the same floor - so the comparison is like for like rather than one design's
best case against another's worst.

    python3 tools/compare_xvf3800.py
"""
import itertools
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import numpy as np
import mic_line_array_design as d
from mic_line_array_design import C128, F64

C = 343.0
XVF = np.array([(0.033, -0.033), (0.033, 0.033), (-0.033, 0.033), (-0.033, -0.033)])
geo = d.build_geometry()
LINE = np.stack([geo.positions_m, np.zeros(geo.n_mic)], axis=1)

def dists(p: F64) -> F64:
    n = len(p)
    m = np.zeros((n, n))
    for i, j in itertools.product(range(n), range(n)):
        m[i, j] = float(np.linalg.norm(p[i] - p[j]))
    return np.asarray(m, dtype=np.float64)

def _w(g: C128, dv: C128, eps: float) -> C128:
    x = np.linalg.solve(g + eps*np.eye(g.shape[0]), dv)
    return np.asarray(x / np.vdot(dv, x), dtype=np.complex128)

def _wng(w: C128) -> float:
    return -10*math.log10(max(float(np.real(np.vdot(w, w))), 1e-30))

def robust(g: C128, dv: C128, floor: float) -> C128:
    lo, hi = 1e-9, 1e4
    if _wng(_w(g, dv, lo)) >= floor: return _w(g, dv, lo)
    if _wng(_w(g, dv, hi)) <= floor: return _w(g, dv, hi)
    for _ in range(60):
        m = math.sqrt(lo*hi)
        if _wng(_w(g, dv, m)) < floor: lo = m
        else: hi = m
    return _w(g, dv, math.sqrt(lo*hi))

def di_at(p: F64, dist: F64, f: float, az_deg: float, floor: float) -> float:
    """Talker in the array plane at azimuth az."""
    k = np.array([math.cos(math.radians(az_deg)), math.sin(math.radians(az_deg))])
    tau = p @ k / C
    dv = np.exp(2j*np.pi*f*tau)
    g = np.sinc(2*f*dist/C).astype(np.complex128)
    w = robust(g, dv, floor)
    return 10.0 * math.log10(max(float(1.0 / np.real(np.vdot(w, g @ w))), 1e-12))

def curve(p: F64, freqs: F64, azs: list[float], floor: float) -> F64:
    dist = dists(p)
    return np.asarray([float(np.mean([di_at(p, dist, f, a, floor) for a in azs]))
                       for f in freqs], dtype=np.float64)

freqs = np.array([125., 250., 500., 1000., 2000., 4000., 6300.])
FLOOR = 0.0
xd = curve(XVF, freqs, [0., 22.5, 45.], FLOOR)         # square has 90 deg symmetry
ld = curve(LINE, freqs, [0., 30., 60.], FLOOR)          # line: broadside to near-endfire
print("In-plane talker, averaged over azimuth, WNG floor 0 dB")
print(f"  {'f (Hz)':>8}{'XVF3800':>10}{'15-el':>9}{'delta':>9}")
for f, a, b in zip(freqs, xd, ld):
    print(f"  {f:>8.0f}{a:>10.2f}{b:>9.2f}{b-a:>9.2f}")
s = (freqs >= 200) & (freqs <= 7000)
print(f"  {'mean':>8}{xd[s].mean():>10.2f}{ld[s].mean():>9.2f}{ld[s].mean()-xd[s].mean():>9.2f}\n")

# single A-weighted room-noise number over the output band
ff = np.linspace(60., 8000., 260)
aw = 10**(d.a_weighting_db(ff)/10)
shape = d.band_shape(ff, 120., 8000.)**2
room = 10**((-5.0*np.log2(np.maximum(ff, 20.)/1000.))/10)
def a_wtd(p: F64, azs: list[float]) -> float:
    dist = dists(p)
    di = np.asarray([float(np.mean([di_at(p, dist, f, a, FLOOR) for a in azs]))
                     for f in ff], dtype=np.float64)
    lin = 10**(di/10)
    num = float(np.trapezoid(aw*room*shape, ff))
    den = float(np.trapezoid(aw*room*shape/lin, ff))
    return 10.0 * math.log10(num / den)
print(f"A-weighted gain against diffuse room noise, 120 Hz - 8 kHz:")
print(f"  XVF3800 4-mic square : {a_wtd(XVF, [0.,22.5,45.]):+.2f} dBA")
print(f"  15-element line array: {a_wtd(LINE, [0.,30.,60.]):+.2f} dBA")
