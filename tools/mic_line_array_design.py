#!/usr/bin/env python3
"""Design and verification tool for a low-latency talker-tracking microphone line array.

Numpy is the only dependency.  Nothing here is asserted without being measured:
every figure the design document quotes is printed by this script, and the
beamformer metrics are computed from the *truncated* FIR bank that would actually
run on the DSP, not from the idealised frequency-domain weights.

Contents
    1  Geometry        15-element harmonically-nested line array (3 octave sub-arrays).
    2  Beamformer      Broadband filter-and-sum designed as one least-squares problem
                       in the FIR-coefficient domain: minimise diffuse-field noise
                       subject to a flat on-axis response with a prescribed,
                       frequency-dependent group delay, regularised by a white-noise
                       penalty.  The normal-equation matrix is block-Toeplitz, so it
                       is assembled from 1-D lag kernels rather than a triple loop.
    3  Beam grid       How finely beams must be spaced to keep scallop loss small.
    4  Robustness      Monte-Carlo over microphone gain / phase / position tolerance.
    5  Localisation    SRP-PHAT DOA accuracy, and a talker-tracking state machine
                       exercised on a two-talker turn-taking scenario.
    6  Latency         End-to-end budget; the beamformer term is measured, not assumed.
    7  Gain staging    SPL -> mic -> ADC dBFS -> DAC -> balanced line level.
    8  Compute         MMAC/s for every block.

Usage
    python3 tools/mic_line_array_design.py            # full report (~2 min)
    python3 tools/mic_line_array_design.py --quick    # fewer Monte-Carlo trials
    python3 tools/mic_line_array_design.py --json     # machine-readable summary too
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from typing import Final, Iterator, Literal

import numpy as np
import numpy.typing as npt

F64 = npt.NDArray[np.float64]
C128 = npt.NDArray[np.complex128]
Bool = npt.NDArray[np.bool_]

C_SOUND: Final[float] = 343.0
"""Speed of sound in air at 20 degC, m/s."""


# --------------------------------------------------------------------------- #
# 1. Geometry
# --------------------------------------------------------------------------- #

GRID_M: Final[float] = 21.4e-3
"""Base grid pitch: lambda/2 at 8 kHz.  Sets the top alias-free frequency."""

HALF_GRID: Final[tuple[float, ...]] = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0)
"""Half-array element positions in grid units; mirrored about a centre element.

Chosen so three *uniform* octave sub-arrays share elements:

    HF  pitch 1x grid   0 +-1 +-2 +-3     aperture  6 grid   alias-free to 8 kHz
    MF  pitch 2x grid   0 +-2 +-4 +-6     aperture 12 grid   alias-free to 4 kHz
    LF  pitch 4x grid   0 +-4 +-8 +-12    aperture 24 grid   alias-free to 2 kHz

Union = {0, +-1, +-2, +-3, +-4, +-6, +-8, +-12} = 15 microphones.  The 16th ADC
channel is a rear-facing reference microphone (front/back disambiguation and
noise reference); it is not part of the line array and is not modelled here.
"""

SubBand = Literal["LF", "MF", "HF"]

SUBARRAY_HALF: Final[dict[SubBand, tuple[float, ...]]] = {
    "LF": (4.0, 8.0, 12.0),
    "MF": (2.0, 4.0, 6.0),
    "HF": (1.0, 2.0, 3.0),
}


@dataclass(frozen=True)
class Geometry:
    """Microphone positions along the array axis, in metres, sorted ascending."""

    positions_m: F64
    masks: dict[SubBand, Bool]

    @property
    def n_mic(self) -> int:
        return int(self.positions_m.size)

    @property
    def aperture_m(self) -> float:
        return float(self.positions_m[-1] - self.positions_m[0])

    def sub_aperture_m(self, band: SubBand) -> float:
        p = self.positions_m[self.masks[band]]
        return float(p[-1] - p[0])

    def sub_pitch_m(self, band: SubBand) -> float:
        p = np.sort(self.positions_m[self.masks[band]])
        return float(np.min(np.diff(p)))


def build_geometry() -> Geometry:
    half = np.asarray(HALF_GRID, dtype=np.float64)
    pos = np.sort(np.concatenate([[0.0], half, -half])) * GRID_M
    masks: dict[SubBand, Bool] = {}
    for band, sel_half in SUBARRAY_HALF.items():
        h = np.asarray(sel_half, dtype=np.float64)
        sel = np.sort(np.concatenate([[0.0], h, -h])) * GRID_M
        hit = np.isclose(pos[:, None], sel[None, :], atol=1e-9).any(axis=1)
        masks[band] = np.asarray(hit, dtype=np.bool_)
    return Geometry(positions_m=pos, masks=masks)


# --------------------------------------------------------------------------- #
# 2. Acoustic primitives
# --------------------------------------------------------------------------- #


def steering_vector(pos_m: F64, freqs_hz: F64, theta_rad: float) -> C128:
    """Free-field plane-wave response, shape (n_freq, n_mic).

    theta is measured from broadside; 0 rad is normal to the array axis.
    """
    tau = pos_m * math.sin(theta_rad) / C_SOUND
    phase = 2j * np.pi * freqs_hz[:, None] * tau[None, :]
    return np.asarray(np.exp(phase), dtype=np.complex128)


def diffuse_coherence(pos_m: F64, freqs_hz: F64) -> F64:
    """Coherence of a spherically isotropic field: sinc(2 f d / c), shape (n_f, M, M)."""
    dist = np.abs(pos_m[:, None] - pos_m[None, :])
    return np.asarray(
        np.sinc(2.0 * freqs_hz[:, None, None] * dist[None, :, :] / C_SOUND),
        dtype=np.float64,
    )


def band_shape(freqs_hz: F64, f_hp: float, f_lp: float) -> F64:
    """Target output band limit: 2nd-order Butterworth magnitudes, high and low."""
    f = np.maximum(freqs_hz, 1e-6)
    hp = (f / f_hp) ** 2 / np.sqrt(1.0 + (f / f_hp) ** 4)
    lp = 1.0 / np.sqrt(1.0 + (f / f_lp) ** 4)
    return np.asarray(hp * lp, dtype=np.float64)


@dataclass(frozen=True)
class DelayProfile:
    """Prescribed group delay: `tau_lo_ms` below `f_lo`, `tau_hi_ms` above `f_hi`.

    Long filters are only *needed* at low frequency (long wavelengths, wide
    sub-array, large steering spread across the aperture), and the ear tolerates
    far more delay there.  Blauert & Laws put the audibility threshold for group
    delay at roughly 1.6 ms at 8 kHz, 2 ms at 4 kHz, 3.2 ms at 1 kHz and 10 ms at
    500 Hz, so spending delay where it is both needed and inaudible is what keeps
    the broadband figure low.  The taper must stay gentle: a steep dtau/df is an
    all-pass a short FIR cannot realise, and it buys on-axis ripple.
    """

    tau_lo_ms: float = 1.50
    tau_hi_ms: float = 0.70
    f_lo_hz: float = 200.0
    f_hi_hz: float = 3000.0

    def tau_s(self, freqs_hz: F64) -> F64:
        t = np.clip(
            np.log(np.maximum(freqs_hz, 1e-6) / self.f_lo_hz)
            / math.log(self.f_hi_hz / self.f_lo_hz),
            0.0,
            1.0,
        )
        a = 0.5 - 0.5 * np.cos(np.pi * t)
        return np.asarray((self.tau_lo_ms + a * (self.tau_hi_ms - self.tau_lo_ms)) * 1e-3)


# --------------------------------------------------------------------------- #
# 3. Least-squares broadband beamformer design
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DesignConfig:
    fs_hz: float = 48000.0
    n_taps: int = 192
    n_design_freq: int = 1400
    gamma_diffuse: float = 0.10
    """Weight on diffuse-noise output power: buys directivity, costs on-axis ripple."""
    rho_white: float = 1e-2
    """Weight on white-noise output power: sets the white-noise gain floor."""
    f_hp_hz: float = 120.0
    f_lp_hz: float = 8000.0
    delay: DelayProfile = field(default_factory=DelayProfile)


def _design_grid(cfg: DesignConfig) -> tuple[F64, F64, F64]:
    """Frequency grid with the response-fit weight `w` and the noise weight `u`."""
    f = np.linspace(0.0, cfg.fs_hz / 2.0, cfg.n_design_freq)
    w = np.where((f >= 0.75 * cfg.f_hp_hz) & (f <= 1.125 * cfg.f_lp_hz), 1.0, 0.05)
    w[0] = 0.0
    # The noise weight must be non-zero at EVERY frequency, not just in the output
    # band.  Where it is zero the individual channel gains are unconstrained: the
    # least-squares fit only asks that they cancel on axis, and a superdirective
    # solution happily makes them enormous and opposite.  That costs nothing on
    # paper and everything in practice - out-of-band self-noise gain of tens of dB,
    # and no tolerance to mismatch at all.
    u = np.where((f >= 150.0) & (f <= cfg.f_lp_hz), 1.0, 0.25)
    return f, np.asarray(w / w.sum()), np.asarray(u / u.sum())


@dataclass
class NormalEquations:
    """Block-Toeplitz normal-equation terms for one look direction.

    Stacking the FIR taps as h[(m, n)] = h[m * L + n], the array response to a
    plane wave from theta0 is R(f) = a(f)^T h with a(f)[(m, n)] = d_m(f) e^{-j w n / fs}.
    Every quadratic term below therefore has blocks that depend only on the tap
    lag n - n', i.e. each (m, m') block is Toeplitz and is built from one 1-D
    kernel of length 2L-1.
    """

    fit: F64      # sum_f w_f Re(conj(a) a^T)     - on-axis response fit
    diffuse: F64  # sum_f u_f Re(E^H Gamma E)     - diffuse noise output power
    white: F64    # sum_f u_f Re(E^H E)           - white noise output power
    target: F64   # sum_f w_f Re(conj(t_f) a)     - linear term of the fit
    n_taps: int
    sin_theta: float


def build_normal_equations(
    geo: Geometry, cfg: DesignConfig, theta_rad: float
) -> NormalEquations:
    m_n = geo.n_mic
    lt = cfg.n_taps
    f, w, u = _design_grid(cfg)
    s0 = math.sin(theta_rad)
    gamma = diffuse_coherence(geo.positions_m, f)
    shape = band_shape(f, cfg.f_hp_hz, cfg.f_lp_hz)
    tau = cfg.delay.tau_s(f)
    omega = 2.0 * np.pi * f

    lag_s = np.arange(-(lt - 1), lt, dtype=np.float64) / cfg.fs_hz
    gather = (np.arange(lt)[:, None] - np.arange(lt)[None, :]) + (lt - 1)
    cos_lag = np.cos(omega[:, None] * lag_s[None, :])
    sin_lag = np.sin(omega[:, None] * lag_s[None, :])

    fit = np.zeros((m_n * lt, m_n * lt), dtype=np.float64)
    diff = np.zeros_like(fit)
    white = np.zeros_like(fit)
    for i in range(m_n):
        for j in range(m_n):
            # cos(2 pi f (Delta_ij + lag)) with Delta_ij = (p_j - p_i) sin(theta) / c
            delta = (geo.positions_m[j] - geo.positions_m[i]) * s0 / C_SOUND
            cd = np.cos(omega * delta)
            sd = np.sin(omega * delta)
            k_fit = ((w * cd)[:, None] * cos_lag - (w * sd)[:, None] * sin_lag).sum(0)
            k_dif = ((u * gamma[:, i, j])[:, None] * cos_lag).sum(0)
            sl = (slice(i * lt, (i + 1) * lt), slice(j * lt, (j + 1) * lt))
            fit[sl] = k_fit[gather]
            diff[sl] = k_dif[gather]
    k_white = (u[:, None] * cos_lag).sum(0)[gather]
    for i in range(m_n):
        white[i * lt : (i + 1) * lt, i * lt : (i + 1) * lt] = k_white

    target = np.zeros(m_n * lt, dtype=np.float64)
    taps_s = np.arange(lt, dtype=np.float64) / cfg.fs_hz
    for i in range(m_n):
        d_i = geo.positions_m[i] * s0 / C_SOUND
        arg = tau[:, None] + d_i - taps_s[None, :]
        target[i * lt : (i + 1) * lt] = ((w * shape)[:, None] * np.cos(omega[:, None] * arg)).sum(0)

    return NormalEquations(fit, diff, white, target, lt, s0)


def solve_fir(ne: NormalEquations, cfg: DesignConfig) -> F64:
    """Solve the regularised normal equations; returns (n_mic, n_taps) real FIRs."""
    n = ne.fit.shape[0]
    a = ne.fit + cfg.gamma_diffuse * ne.diffuse + cfg.rho_white * ne.white
    a = a + 1e-14 * np.eye(n)
    h = np.linalg.solve(a, ne.target)
    return np.asarray(h.reshape(-1, ne.n_taps), dtype=np.float64)


def design_beam(geo: Geometry, cfg: DesignConfig, theta_deg: float) -> F64:
    return solve_fir(build_normal_equations(geo, cfg, math.radians(theta_deg)), cfg)


# --------------------------------------------------------------------------- #
# 4. Measurement of the realised beamformer
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BeamMetrics:
    freqs_hz: F64
    on_axis_db: F64       # relative to the intended band shape
    group_delay_ms: F64
    di_db: F64
    wng_db: F64

    def band(self, lo: float, hi: float) -> Bool:
        return np.asarray((self.freqs_hz >= lo) & (self.freqs_hz <= hi))

    def mean_in(self, values: F64, lo: float, hi: float) -> float:
        return float(np.mean(values[self.band(lo, hi)]))

    def at(self, f_hz: float, values: F64) -> float:
        return float(values[int(np.argmin(np.abs(self.freqs_hz - f_hz)))])


def _fir_spectrum(fir: F64, fs_hz: float, n_fft: int) -> tuple[F64, C128]:
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / fs_hz).astype(np.float64)
    return freqs, np.asarray(np.fft.rfft(fir, n=n_fft, axis=1).T, dtype=np.complex128)


def array_response(geo: Geometry, gf: C128, freqs_hz: F64, theta_rad: float) -> C128:
    d = steering_vector(geo.positions_m, freqs_hz, theta_rad)
    return np.asarray(np.sum(gf * d, axis=1), dtype=np.complex128)


def measure(
    geo: Geometry, fir: F64, cfg: DesignConfig, theta_deg: float, n_fft: int = 8192
) -> BeamMetrics:
    theta = math.radians(theta_deg)
    freqs, gf = _fir_spectrum(fir, cfg.fs_hz, n_fft)
    r = array_response(geo, gf, freqs, theta)
    gamma = diffuse_coherence(geo.positions_m, freqs)

    sig = np.abs(r) ** 2
    p_diffuse = np.real(np.einsum("fi,fij,fj->f", gf, gamma, np.conj(gf)))
    p_white = np.sum(np.abs(gf) ** 2, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        di = 10.0 * np.log10(np.maximum(sig, 1e-30) / np.maximum(p_diffuse, 1e-30))
        wng = 10.0 * np.log10(np.maximum(sig, 1e-30) / np.maximum(p_white, 1e-30))
        mag = 20.0 * np.log10(np.maximum(np.abs(r), 1e-30)) - 20.0 * np.log10(
            np.maximum(band_shape(freqs, cfg.f_hp_hz, cfg.f_lp_hz), 1e-30)
        )
    gd = -np.gradient(np.unwrap(np.angle(r)), 2.0 * np.pi * (freqs[1] - freqs[0])) * 1e3
    return BeamMetrics(freqs, mag, np.asarray(gd, dtype=np.float64), di, wng)


def beampattern_db(
    geo: Geometry, fir: F64, cfg: DesignConfig, probe_hz: F64, angles_deg: F64
) -> F64:
    n_fft = 8192
    freqs, gf = _fir_spectrum(fir, cfg.fs_hz, n_fft)
    idx = np.array([int(np.argmin(np.abs(freqs - f))) for f in probe_hz])
    out = np.zeros((probe_hz.size, angles_deg.size), dtype=np.float64)
    for j, a in enumerate(angles_deg):
        r = array_response(geo, gf, freqs, math.radians(float(a)))
        out[:, j] = 20.0 * np.log10(np.maximum(np.abs(r[idx]), 1e-30))
    return out


# --------------------------------------------------------------------------- #
# 5. Tolerance Monte-Carlo
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Tolerance:
    gain_db_sigma: float = 0.5
    phase_deg_sigma: float = 2.0
    position_mm_sigma: float = 0.3


def tolerance_sweep(
    geo: Geometry, fir: F64, cfg: DesignConfig, theta_deg: float,
    tol: Tolerance, trials: int, seed: int,
) -> dict[str, float]:
    rng = np.random.default_rng(seed)
    theta = math.radians(theta_deg)
    n_fft = 4096
    freqs, gf = _fir_spectrum(fir, cfg.fs_hz, n_fft)
    sel = (freqs >= 200.0) & (freqs <= 7000.0)
    fb, gfb = freqs[sel], gf[sel]
    gamma = diffuse_coherence(geo.positions_m, fb)
    nominal_db = 20.0 * np.log10(np.maximum(np.abs(array_response(geo, gfb, fb, theta)), 1e-30))

    di_vals: list[float] = []
    dev_vals: list[float] = []
    for _ in range(trials):
        gain = 10.0 ** (rng.normal(0.0, tol.gain_db_sigma, geo.n_mic) / 20.0)
        phase = np.deg2rad(rng.normal(0.0, tol.phase_deg_sigma, geo.n_mic))
        dpos = rng.normal(0.0, tol.position_mm_sigma * 1e-3, geo.n_mic)
        gp = gfb * (gain * np.exp(1j * phase))[None, :]
        d = steering_vector(geo.positions_m + dpos, fb, theta)
        r = np.sum(gp * d, axis=1)
        sig = np.abs(r) ** 2
        p_d = np.real(np.einsum("fi,fij,fj->f", gp, gamma, np.conj(gp)))
        di_vals.append(float(np.mean(10.0 * np.log10(np.maximum(sig, 1e-30) / np.maximum(p_d, 1e-30)))))
        dev = 20.0 * np.log10(np.maximum(np.abs(r), 1e-30)) - nominal_db
        dev_vals.append(float(np.max(np.abs(dev))))
    return {
        "di_mean_db": float(np.mean(di_vals)),
        "di_p05_db": float(np.percentile(di_vals, 5.0)),
        "on_axis_dev_p95_db": float(np.percentile(dev_vals, 95.0)),
        "on_axis_dev_max_db": float(np.max(dev_vals)),
    }


# --------------------------------------------------------------------------- #
# 6. SRP-PHAT localisation and talker tracking
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SrpConfig:
    fs_hz: float = 16000.0
    frame: int = 512   # 32 ms
    hop: int = 256     # 16 ms
    f_min_hz: float = 300.0
    f_max_hz: float = 3800.0
    grid_step_deg: float = 2.5
    grid_limit_deg: float = 80.0

    def grid(self) -> F64:
        n = int(2 * self.grid_limit_deg / self.grid_step_deg) + 1
        return np.linspace(-self.grid_limit_deg, self.grid_limit_deg, n)

    @property
    def hop_ms(self) -> float:
        return 1e3 * self.hop / self.fs_hz


def srp_phat(geo: Geometry, spec: C128, freqs_hz: F64, angles_deg: F64) -> F64:
    """PHAT-weighted steered response power.  spec is (n_frame, n_bin, n_mic).

    Rather than summing M(M-1)/2 cross-spectra per look direction, use the
    identity  sum_{i<k} Re(x_i conj(x_k) e^{-jw(tau_i - tau_k)})
              = (|sum_i x_i conj(d_i)|^2 - M) / 2   for |x_i| = 1 after PHAT,
    which is O(M) per direction instead of O(M^2) and gives identical values.
    """
    x = spec / np.maximum(np.abs(spec), 1e-12)
    n_mic = geo.n_mic
    out = np.zeros((x.shape[0], angles_deg.size), dtype=np.float64)
    for j, a in enumerate(angles_deg):
        d = steering_vector(geo.positions_m, freqs_hz, math.radians(float(a)))
        beam = np.sum(x * np.conj(d)[None, :, :], axis=2)
        out[:, j] = 0.5 * np.sum(np.abs(beam) ** 2 - n_mic, axis=1)
    return out


def parabolic_peak(smap_row: F64, grid: F64) -> float:
    """Sub-grid DOA by fitting a parabola through the peak and its neighbours."""
    k = int(np.argmax(smap_row))
    if k == 0 or k == grid.size - 1:
        return float(grid[k])
    y0, y1, y2 = smap_row[k - 1], smap_row[k], smap_row[k + 1]
    den = y0 - 2.0 * y1 + y2
    if abs(den) < 1e-12:
        return float(grid[k])
    delta = 0.5 * (y0 - y2) / den
    return float(grid[k] + np.clip(delta, -1.0, 1.0) * (grid[1] - grid[0]))


def speech_like(n: int, fs: float, rng: np.random.Generator, active: F64 | None = None) -> F64:
    """Noise shaped to a coarse long-term average speech spectrum, syllabically gated."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.maximum(np.fft.rfftfreq(n, 1.0 / fs), 1.0)
    ltass = np.where(f < 500.0, f / 500.0, (500.0 / f) ** 0.9)
    sig = np.fft.irfft(spec * ltass, n=n)
    t = np.arange(n) / fs
    env = 0.3 + 0.7 * (0.5 + 0.5 * np.sin(2.0 * np.pi * 4.0 * t + rng.uniform(0.0, 6.28)))
    if active is not None:
        env = env * active
    out = sig * env
    return np.asarray(out / (float(np.std(sig)) + 1e-12), dtype=np.float64)


def propagate(pos_m: F64, sig: F64, theta_deg: float, fs: float) -> F64:
    """Exact fractional delay of one source onto every microphone; (n_sample, n_mic)."""
    n = sig.size
    s = np.fft.rfft(sig)
    f = np.fft.rfftfreq(n, 1.0 / fs)
    tau = pos_m * math.sin(math.radians(theta_deg)) / C_SOUND
    y = np.fft.irfft(s[None, :] * np.exp(2j * np.pi * f[None, :] * tau[:, None]), n=n, axis=1)
    return np.asarray(y.T, dtype=np.float64)


def diffuse_noise(pos_m: F64, n: int, fs: float, rng: np.random.Generator) -> F64:
    """Noise field with the correct sinc inter-microphone coherence, pink-tilted."""
    f = np.fft.rfftfreq(n, 1.0 / fs).astype(np.float64)
    gamma = diffuse_coherence(pos_m, f)
    m = pos_m.size
    z = (rng.standard_normal((f.size, m)) + 1j * rng.standard_normal((f.size, m))) / math.sqrt(2.0)
    spec = np.zeros((f.size, m), dtype=np.complex128)
    eye = np.eye(m)
    for k in range(f.size):
        g = gamma[k] + 1e-6 * eye
        try:
            chol = np.linalg.cholesky(g)
        except np.linalg.LinAlgError:
            ev, evec = np.linalg.eigh(g)
            chol = evec @ np.diag(np.sqrt(np.maximum(ev, 0.0)))
        spec[k] = chol @ z[k]
    tilt = 1.0 / np.maximum(f, 20.0) ** 0.5
    y = np.fft.irfft(spec * tilt[:, None], n=n, axis=0)
    return np.asarray(y / (float(np.std(y)) + 1e-12), dtype=np.float64)


def _frames(mix: F64, cfg: SrpConfig) -> tuple[C128, F64]:
    win = np.hanning(cfg.frame)
    n = mix.shape[0]
    blocks = np.stack([mix[s : s + cfg.frame] * win[:, None]
                       for s in range(0, n - cfg.frame, cfg.hop)])
    spec = np.fft.rfft(blocks, axis=1)
    f = np.fft.rfftfreq(cfg.frame, 1.0 / cfg.fs_hz)
    sel = (f >= cfg.f_min_hz) & (f <= cfg.f_max_hz)
    return np.asarray(spec[:, sel, :], dtype=np.complex128), np.asarray(f[sel])


def localisation_error(
    geo: Geometry, cfg: SrpConfig, true_deg: float, snr_db: float,
    interferer_deg: float | None, sir_db: float, seed: int, duration_s: float = 1.2,
) -> tuple[float, float]:
    """Return (median |error| in degrees, fraction of frames with |error| > 5 deg)."""
    rng = np.random.default_rng(seed)
    n = int(duration_s * cfg.fs_hz)
    mix = propagate(geo.positions_m, speech_like(n, cfg.fs_hz, rng), true_deg, cfg.fs_hz)
    if interferer_deg is not None:
        itf = propagate(geo.positions_m, speech_like(n, cfg.fs_hz, rng), interferer_deg, cfg.fs_hz)
        mix = mix + itf * 10.0 ** (-sir_db / 20.0)
    mix = mix + diffuse_noise(geo.positions_m, n, cfg.fs_hz, rng) * 10.0 ** (-snr_db / 20.0)
    spec, freqs = _frames(mix, cfg)
    grid = cfg.grid()
    smap = srp_phat(geo, spec, freqs, grid)
    est = np.array([parabolic_peak(smap[t], grid) for t in range(smap.shape[0])])
    err = np.abs(est - true_deg)
    return float(np.median(err)), float(np.mean(err > 5.0))


@dataclass(frozen=True)
class TrackerConfig:
    smoothing_tc_ms: float = 120.0
    switch_margin_db: float = 3.0
    switch_hold_ms: float = 150.0
    hangover_ms: float = 400.0
    noise_floor_tc_s: float = 5.0


@dataclass
class TrackerResult:
    beam_deg: F64
    switch_frames: list[int]


def track_talker(smap: F64, grid: F64, cfg: SrpConfig, tcfg: TrackerConfig) -> TrackerResult:
    """Hysteretic primary-talker tracker over the SRP map.

    A candidate must beat the held beam by `switch_margin_db` continuously for
    `switch_hold_ms` before the beam moves.  Without that hysteresis the beam
    ping-pongs on every syllable of a competing talker.
    """
    n_frame = smap.shape[0]
    a_s = math.exp(-cfg.hop_ms / tcfg.smoothing_tc_ms)
    a_n = math.exp(-cfg.hop_ms / (tcfg.noise_floor_tc_s * 1e3))
    hold_frames = max(1, int(round(tcfg.switch_hold_ms / cfg.hop_ms)))

    smooth = np.zeros(grid.size)
    floor = np.full(grid.size, np.inf)
    held = int(np.argmax(smap[0]))
    streak = 0
    cand = held
    out = np.zeros(n_frame)
    switches: list[int] = []
    for t in range(n_frame):
        smooth = a_s * smooth + (1.0 - a_s) * smap[t]
        floor = np.minimum(a_n * floor + (1.0 - a_n) * smooth, smooth)
        score = 10.0 * np.log10(np.maximum(smooth - floor, 1e-9) + 1e-9)
        best = int(np.argmax(score))
        if best != held and score[best] - score[held] > tcfg.switch_margin_db:
            streak = streak + 1 if best == cand else 1
            cand = best
            if streak >= hold_frames:
                held = best
                switches.append(t)
                streak = 0
        else:
            streak = 0
        out[t] = grid[held]
    return TrackerResult(out, switches)


def turn_taking_scenario(
    geo: Geometry, cfg: SrpConfig, tcfg: TrackerConfig,
    a_deg: float, b_deg: float, snr_db: float, seed: int,
) -> dict[str, float]:
    """Talker A speaks for 3 s, then talker B takes over.  Measure the switch."""
    rng = np.random.default_rng(seed)
    dur = 6.0
    n = int(dur * cfg.fs_hz)
    t = np.arange(n) / cfg.fs_hz
    gate_a = (t < 3.0).astype(np.float64)
    gate_b = (t >= 3.0).astype(np.float64)
    mix = propagate(geo.positions_m, speech_like(n, cfg.fs_hz, rng, gate_a), a_deg, cfg.fs_hz)
    mix = mix + propagate(geo.positions_m, speech_like(n, cfg.fs_hz, rng, gate_b), b_deg, cfg.fs_hz)
    mix = mix + diffuse_noise(geo.positions_m, n, cfg.fs_hz, rng) * 10.0 ** (-snr_db / 20.0)
    spec, freqs = _frames(mix, cfg)
    grid = cfg.grid()
    res = track_talker(srp_phat(geo, spec, freqs, grid), grid, cfg, tcfg)

    onset = int(3.0 * 1e3 / cfg.hop_ms)
    after = np.where(np.abs(res.beam_deg[onset:] - b_deg) <= 5.0)[0]
    switch_ms = float(after[0] * cfg.hop_ms) if after.size else float("nan")
    settle = slice(int(0.5 * 1e3 / cfg.hop_ms), onset)
    return {
        "hold_a_correct_pct": 100.0 * float(np.mean(np.abs(res.beam_deg[settle] - a_deg) <= 5.0)),
        "switch_delay_ms": switch_ms,
        "n_switches": float(len(res.switch_frames)),
    }


# --------------------------------------------------------------------------- #
# 7. Latency, gain staging, compute
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LatencyItem:
    stage: str
    ms: float
    note: str


def latency_budget(bf_hf_ms: float) -> list[LatencyItem]:
    return [
        LatencyItem("Mic + preamp + anti-alias", 0.02, "analogue, 1st order at 40 kHz"),
        LatencyItem("ADC decimation filter", 0.35, "low-latency filter mode, 48 kHz"),
        LatencyItem("Calibration FIR, 7 tap", 0.07, "per-mic gain/phase trim"),
        LatencyItem("Beamformer FIR, above 3 kHz", bf_hf_ms, "measured from the FIR bank"),
        LatencyItem("Beam cross-fade", 0.00, "two beams in parallel, no added delay"),
        LatencyItem("AGC / limiter", 0.00, "zero look-ahead, soft knee"),
        LatencyItem("DAC reconstruction filter", 0.28, "low-latency filter mode, 48 kHz"),
        LatencyItem("Balanced line driver", 0.00, "analogue"),
    ]


@dataclass(frozen=True)
class GainStaging:
    mic_sensitivity_dbv_per_pa: float = -38.0
    mic_self_noise_dba: float = 29.0
    mic_aop_db_spl: float = 130.0
    preamp_gain_db: float = 30.0
    adc_full_scale_dbv: float = 6.0        # 2 Vrms
    room_noise_gain_dba: float = 9.0
    self_noise_penalty_dba: float = 0.0
    dac_full_scale_dbu: float = 18.0       # balanced
    nominal_out_dbu: float = 4.0
    agc_target_dbfs: float = -20.0

    def spl_at_full_scale(self) -> float:
        return 94.0 + (self.adc_full_scale_dbv - self.preamp_gain_db) - self.mic_sensitivity_dbv_per_pa

    def dbfs_for_spl(self, spl_db: float) -> float:
        return spl_db - self.spl_at_full_scale()

    def self_noise_dbfs(self, *, beamformed: bool) -> float:
        """Self-noise referred to the on-axis input: follows WNG, not DI."""
        n = self.dbfs_for_spl(self.mic_self_noise_dba)
        return n + self.self_noise_penalty_dba if beamformed else n

    def room_noise_dbfs(self, spl_db: float, *, beamformed: bool) -> float:
        n = self.dbfs_for_spl(spl_db)
        return n - self.room_noise_gain_dba if beamformed else n

    def headroom_db(self) -> float:
        return self.dac_full_scale_dbu - self.nominal_out_dbu


def a_weighting_db(freqs_hz: F64) -> F64:
    """IEC 61672 A-weighting, dB, normalised to 0 dB at 1 kHz."""
    f = np.maximum(freqs_hz, 1e-6)
    f2 = f ** 2
    num = 12194.0 ** 2 * f2 ** 2
    den = ((f2 + 20.6 ** 2) * (f2 + 12194.0 ** 2)
           * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2)))
    return np.asarray(20.0 * np.log10(num / den) + 2.0, dtype=np.float64)


@dataclass(frozen=True)
class NoiseGains:
    """How the array treats the two noise sources that actually matter.

    They are *not* the same number, and confusing them is the classic error in
    superdirective array design:

      * Room noise is close to a diffuse (spherically isotropic) field, so the
        array's gain against it is the directivity index, DI(f).
      * Microphone self-noise is uncorrelated between elements, so the array's
        gain against it is the white-noise gain, WNG(f) - which a superdirective
        design drives *negative* at low frequency.  A design tuned only on DI
        will quietly trade a few dB of room noise for a hiss you cannot remove.

    Both are collapsed here to single A-weighted numbers over the output band,
    which is what a specification can actually be written against.
    """

    room_gain_dba: float
    self_noise_penalty_dba: float


def integrate_noise(
    geo: Geometry, fir: F64, cfg: DesignConfig, room_tilt_db_per_oct: float = -5.0
) -> NoiseGains:
    """A-weighted array gain against room noise, and penalty on mic self-noise.

    Computed from output noise *powers*, not from DI and WNG ratios: above the
    8 kHz output filter both of those are quotients of two near-zeros and are
    numerically meaningless, even though the noise power they describe is
    correctly negligible there.  The reference in both cases is a single omni
    microphone passed through the same output band shaping, so the comparison is
    like for like.
    """
    freqs, gf = _fir_spectrum(fir, cfg.fs_hz, 8192)
    sel = freqs >= 20.0
    f = freqs[sel]
    gfs = gf[sel]

    a_w = 10.0 ** (a_weighting_db(f) / 10.0)
    shape_sq = band_shape(f, cfg.f_hp_hz, cfg.f_lp_hz) ** 2
    room = 10.0 ** ((room_tilt_db_per_oct * np.log2(np.maximum(f, 20.0) / 1000.0)) / 10.0)

    gamma = diffuse_coherence(geo.positions_m, f)
    p_diffuse = np.real(np.einsum("fi,fij,fj->f", gfs, gamma, np.conj(gfs)))
    p_white = np.sum(np.abs(gfs) ** 2, axis=1)

    room_out = float(np.trapezoid(a_w * room * p_diffuse, f))
    room_ref = float(np.trapezoid(a_w * room * shape_sq, f))
    self_out = float(np.trapezoid(a_w * p_white, f))
    self_ref = float(np.trapezoid(a_w * shape_sq, f))
    return NoiseGains(
        room_gain_dba=10.0 * math.log10(room_ref / max(room_out, 1e-30)),
        self_noise_penalty_dba=10.0 * math.log10(max(self_out, 1e-30) / self_ref),
    )


def dbu_to_vrms(dbu: float) -> float:
    return float(0.7746 * 10.0 ** (dbu / 20.0))


# --------------------------------------------------------------------------- #
# 8. Report
# --------------------------------------------------------------------------- #


def _octave_rows(m: BeamMetrics) -> Iterator[tuple[float, float, float, float, float]]:
    # 1/3-octave averages: a full octave at the top of the band would straddle the
    # 8 kHz output filter's stopband, where DI and WNG are ratios of two near-zeros.
    for fc in (125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 6300.0):
        lo, hi = fc / 2.0 ** (1.0 / 6.0), fc * 2.0 ** (1.0 / 6.0)
        sel = m.band(lo, hi)
        yield (fc, float(np.mean(m.di_db[sel])), float(np.mean(m.wng_db[sel])),
               float(np.mean(m.group_delay_ms[sel])), float(np.mean(m.on_axis_db[sel])))


def run_report(cfg: DesignConfig, quick: bool) -> dict[str, object]:
    geo = build_geometry()
    print("=" * 84)
    print("MICROPHONE LINE ARRAY - low-latency talker-tracking design verification")
    print("=" * 84)

    # -- 1 ------------------------------------------------------------------ #
    print("\n[1] GEOMETRY")
    print(f"  array microphones      : {geo.n_mic}  (+1 rear reference = 16 ADC channels)")
    print(f"  total aperture         : {geo.aperture_m * 1e3:.1f} mm")
    print(f"  base grid pitch        : {GRID_M * 1e3:.1f} mm = lambda/2 at "
          f"{C_SOUND / (2 * GRID_M):.0f} Hz")
    print(f"  positions (mm)         : {', '.join(f'{p * 1e3:+.1f}' for p in geo.positions_m)}")
    print(f"  {'band':<5}{'mics':>6}{'pitch mm':>10}{'aperture mm':>13}{'alias-free to':>16}")
    bands: tuple[SubBand, ...] = ("LF", "MF", "HF")
    for b in bands:
        pitch = geo.sub_pitch_m(b)
        print(f"  {b:<5}{int(np.sum(geo.masks[b])):>6}{pitch * 1e3:>10.1f}"
              f"{geo.sub_aperture_m(b) * 1e3:>13.1f}{C_SOUND / (2 * pitch):>13.0f} Hz")
    print("  The nesting is a spatial-sampling guarantee, not a runtime band split: the")
    print("  beamformer below uses all 15 elements at every frequency and lets the")
    print("  optimiser choose the weighting.  The nested positions only ensure that an")
    print("  adequately-sampled sub-aperture exists in every octave.")

    # -- 2 ------------------------------------------------------------------ #
    print("\n[2] BEAMFORMER  (all figures measured from the truncated FIR bank)")
    print(f"  {geo.n_mic} x {cfg.n_taps} taps at {cfg.fs_hz / 1e3:.0f} kHz "
          f"= {cfg.n_taps / cfg.fs_hz * 1e3:.2f} ms filter span")
    print(f"  design weights: diffuse gamma={cfg.gamma_diffuse}, white rho={cfg.rho_white}")
    print(f"  target group delay: {cfg.delay.tau_lo_ms:.2f} ms below {cfg.delay.f_lo_hz:.0f} Hz "
          f"-> {cfg.delay.tau_hi_ms:.2f} ms above {cfg.delay.f_hi_hz:.0f} Hz")

    fir0 = design_beam(geo, cfg, 0.0)
    m0 = measure(geo, fir0, cfg, 0.0)
    dsb_cfg = DesignConfig(**{**cfg.__dict__, "gamma_diffuse": 0.0, "rho_white": 1e-3})
    fir_dsb = design_beam(geo, dsb_cfg, 0.0)
    m_dsb = measure(geo, fir_dsb, dsb_cfg, 0.0)

    print(f"\n  broadside beam        {'DI':>7}{'WNG':>8}{'grp del':>10}{'on-axis':>10}"
          f"{'DI (DSB)':>11}")
    print(f"  {'f (Hz)':>8}{'':<14}{'dB':>5}{'dB':>8}{'ms':>10}{'dB':>10}{'dB':>11}")
    dsb_rows = list(_octave_rows(m_dsb))
    for (fc, di, wng, gd, mag), (_, di_d, _, _, _) in zip(_octave_rows(m0), dsb_rows):
        print(f"  {fc:>8.0f}{'':<14}{di:>5.1f}{wng:>8.1f}{gd:>10.2f}{mag:>10.2f}{di_d:>11.1f}")

    ripple = float(np.max(m0.on_axis_db[m0.band(200.0, 7000.0)])
                   - np.min(m0.on_axis_db[m0.band(200.0, 7000.0)]))
    di_avg = m0.mean_in(m0.di_db, 200.0, 7000.0)
    di_dsb = m_dsb.mean_in(m_dsb.di_db, 200.0, 7000.0)
    wng_min = float(np.min(m0.wng_db[m0.band(200.0, 7000.0)]))
    gd_hf = m0.mean_in(m0.group_delay_ms, 3000.0, 7000.0)
    gd_lf = m0.mean_in(m0.group_delay_ms, 150.0, 250.0)
    print(f"\n  on-axis ripple 200 Hz - 7 kHz : {ripple:.2f} dB")
    print(f"  mean DI 200 Hz - 7 kHz        : {di_avg:.2f} dB "
          f"(delay-and-sum on the same array: {di_dsb:.2f} dB)")
    print(f"  worst white-noise gain        : {wng_min:.1f} dB")
    print(f"  group delay 3 - 7 kHz         : {gd_hf:.2f} ms")
    print(f"  group delay 150 - 250 Hz      : {gd_lf:.2f} ms")

    steered: dict[str, float] = {}
    for ang in (45.0, 75.0):
        ms = measure(geo, design_beam(geo, cfg, ang), cfg, ang)
        r = float(np.max(ms.on_axis_db[ms.band(200.0, 7000.0)])
                  - np.min(ms.on_axis_db[ms.band(200.0, 7000.0)]))
        steered[f"di_{ang:.0f}deg"] = ms.mean_in(ms.di_db, 200.0, 7000.0)
        steered[f"ripple_{ang:.0f}deg"] = r
        print(f"  steered to {ang:>4.0f} deg          : DI {steered[f'di_{ang:.0f}deg']:.2f} dB, "
              f"ripple {r:.2f} dB, group delay "
              f"{ms.mean_in(ms.group_delay_ms, 3000.0, 7000.0):.2f} ms at HF")

    # -- 3 ------------------------------------------------------------------ #
    print("\n[3] BEAMPATTERN, broadside beam")
    probe = np.array([250.0, 500.0, 1000.0, 2000.0, 4000.0, 6300.0])
    fine = np.arange(-90.0, 90.5, 1.0)
    bp_fine = beampattern_db(geo, fir0, cfg, probe, fine)
    bp_fine = bp_fine - bp_fine[:, int(np.argmin(np.abs(fine)))][:, None]
    print(f"  {'f (Hz)':>8}{'-6 dB beamwidth':>18}{'peak sidelobe':>16}"
          f"{'mean off-lobe':>16}")
    widths: dict[str, float] = {}
    for i, f in enumerate(probe):
        row = bp_fine[i]
        inside = np.where(row >= -6.0)[0]
        # contiguous run containing broadside
        c = int(np.argmin(np.abs(fine)))
        lo = hi = c
        while lo - 1 in inside and row[lo - 1] >= -6.0:
            lo -= 1
        while hi + 1 in inside and row[hi + 1] >= -6.0:
            hi += 1
        width = float(fine[hi] - fine[lo])
        # Guard band: the first bin outside a -6 dB edge is still ~-6 dB by
        # definition, so measure sidelobes beyond 1.5x the main-lobe half-width.
        guard = int(round(1.5 * (hi - lo) / 2.0))
        g_lo, g_hi = max(0, c - guard), min(row.size - 1, c + guard)
        outside = np.concatenate([row[:g_lo], row[g_hi + 1:]])
        widths[f"{f:.0f}Hz"] = width
        print(f"  {f:>8.0f}{width:>15.0f} deg{float(np.max(outside)):>13.1f} dB"
              f"{float(np.mean(outside)):>13.1f} dB")

    coarse = np.arange(-90.0, 91.0, 15.0)
    bp = beampattern_db(geo, fir0, cfg, probe, coarse)
    bp = bp - bp[:, coarse.size // 2][:, None]
    print("\n  response at fixed angles (dB re on-axis)")
    print("     angle:" + "".join(f"{a:>7.0f}" for a in coarse))
    for i, f in enumerate(probe):
        print(f"  {f:>7.0f} Hz" + "".join(f"{v:>7.1f}" for v in bp[i]))
    print("  (a superdirective design minimises *integrated* diffuse noise, so it "
          "places\n   deep nulls at particular angles rather than a smooth taper - "
          "the mean\n   off-lobe column is the figure that matters, not any single "
          "angle.)")

    print("\n  beam grid: cross-over loss for a talker exactly between two beams")
    grid_loss: dict[str, float] = {}
    beam_counts: dict[float, int] = {}
    for du in (0.06, 0.10, 0.15):
        a0 = 0.0
        a1 = math.degrees(math.asin(du))
        mid = math.radians(math.degrees(math.asin(du / 2.0)))
        _, g0 = _fir_spectrum(design_beam(geo, cfg, a0), cfg.fs_hz, 8192)
        _, g1 = _fir_spectrum(design_beam(geo, cfg, a1), cfg.fs_hz, 8192)
        ff = np.fft.rfftfreq(8192, 1.0 / cfg.fs_hz).astype(np.float64)
        sel = (ff >= 1000.0) & (ff <= 7000.0)
        r0 = np.abs(array_response(geo, g0, ff, mid))[sel]
        r1 = np.abs(array_response(geo, g1, ff, mid))[sel]
        ref = np.abs(array_response(geo, g0, ff, 0.0))[sel]
        loss = float(np.max(-20.0 * np.log10(np.maximum(np.maximum(r0, r1) / ref, 1e-9))))
        n_beams = int(math.ceil(2.0 * math.sin(math.radians(75.0)) / du)) + 1
        grid_loss[f"du_{du}"] = loss
        beam_counts[du] = n_beams
        print(f"    beam spacing du=sin(theta) step {du:.2f} "
              f"({n_beams:>2d} beams over +-75 deg): worst loss {loss:5.2f} dB")
    chosen_du = min((d for d, l in grid_loss.items() if l <= 1.5),
                    key=lambda d: beam_counts[float(d.split("_")[1])], default="du_0.06")
    n_beam_bank = beam_counts[float(chosen_du.split("_")[1])]
    print(f"    -> {n_beam_bank} beams (step {chosen_du.split('_')[1]}) keeps a talker "
          "anywhere in coverage within 1.5 dB of a\n       beam centre; beams are "
          "spaced uniformly in sin(theta), not in angle, because that\n       is what "
          "makes the main lobe a constant width.")

    # -- 4 ------------------------------------------------------------------ #
    trials = 60 if quick else 300
    print(f"\n[4] TOLERANCE MONTE-CARLO, {trials} trials "
          "(gain 0.5 dB, phase 2 deg, position 0.3 mm, 1 sigma)")
    print("  Evaluated on a STEERED beam as well as at broadside.  Position error along")
    print("  the array axis is INVISIBLE at broadside - a plane wave arriving normal to")
    print("  the array reaches every element simultaneously however the elements are")
    print("  spaced - so a broadside-only sweep silently tests gain and phase alone.")
    print("  The error appears as sin(theta) grows: 1 mm of axial displacement is 4.2 deg")
    print("  of phase at 8 kHz steered to 30 deg, and 8.1 deg steered to 75 deg.")
    fir75 = design_beam(geo, cfg, 75.0)
    m75 = measure(geo, fir75, cfg, 75.0)
    di75 = m75.mean_in(m75.di_db, 200.0, 7000.0)
    print(f"\n  {'':<26}{'DI mean':>9}{'DI p5':>8}{'dev p95':>10}{'dev worst':>11}")
    tol_all: dict[str, dict[str, float]] = {}
    for ang, fir_a, nominal in ((0.0, fir0, di_avg), (75.0, fir75, di75)):
        t = tolerance_sweep(geo, fir_a, cfg, ang, Tolerance(), trials, seed=7)
        tol_all[f"{ang:.0f}deg"] = t
        print(f"  steered {ang:>4.0f} deg (nom {nominal:5.2f}){t['di_mean_db']:>9.2f}"
              f"{t['di_p05_db']:>8.2f}{t['on_axis_dev_p95_db']:>10.2f}"
              f"{t['on_axis_dev_max_db']:>11.2f}")
    tol = tol_all["75deg"]

    # -- 5 ------------------------------------------------------------------ #
    scfg = SrpConfig()
    print(f"\n[5] SRP-PHAT LOCALISATION  ({scfg.frame / scfg.fs_hz * 1e3:.0f} ms frames, "
          f"{scfg.hop_ms:.0f} ms hop, {scfg.grid().size} beams, "
          f"{scfg.f_min_hz:.0f}-{scfg.f_max_hz:.0f} Hz)")
    sources = [-53.7, -18.3, 3.1, 27.9, 61.4]
    n_src = 3 if quick else 5
    cases = [
        ("quiet room, single talker", 20.0, None, 0.0),
        ("noisy room (5 dB SNR)", 5.0, None, 0.0),
        ("competing talker, 6 dB down", 15.0, 42.0, 6.0),
        ("competing talker, 3 dB down", 15.0, 42.0, 3.0),
    ]
    loc: dict[str, float] = {}
    print(f"  {'scenario':<30}{'median |err|':>14}{'frames >5 deg':>16}")
    for label, snr, itf, sir in cases:
        res = [localisation_error(geo, scfg, t, snr, itf, sir, seed=100 + i)
               for i, t in enumerate(sources[:n_src])]
        med = float(np.median([r[0] for r in res]))
        gross = 100.0 * float(np.mean([r[1] for r in res]))
        loc[label] = med
        print(f"  {label:<30}{med:>11.2f} deg{gross:>14.1f} %")

    print("\n  talker tracking, A at -35 deg for 3 s then B at +40 deg")
    tcfg = TrackerConfig()
    track = turn_taking_scenario(geo, scfg, tcfg, -35.0, 40.0, snr_db=15.0, seed=11)
    print(f"    beam on talker A before hand-over : {track['hold_a_correct_pct']:.0f} % of frames")
    print(f"    time to lock onto talker B        : {track['switch_delay_ms']:.0f} ms")
    print(f"    total beam switches in 6 s        : {track['n_switches']:.0f}")
    print(f"    (hysteresis: {tcfg.switch_margin_db:.0f} dB margin held for "
          f"{tcfg.switch_hold_ms:.0f} ms, {tcfg.hangover_ms:.0f} ms hangover)")

    # -- 6 ------------------------------------------------------------------ #
    print("\n[6] LATENCY BUDGET, microphone diaphragm to balanced line output")
    items = latency_budget(gd_hf)
    total = sum(i.ms for i in items)
    for it in items:
        print(f"  {it.stage:<32}{it.ms:>7.2f} ms   {it.note}")
    print(f"  {'-' * 32}{'-' * 10}")
    print(f"  {'TOTAL, speech band above 3 kHz':<32}{total:>7.2f} ms")
    print(f"  {'TOTAL, band below 250 Hz':<32}{total + (gd_lf - gd_hf):>7.2f} ms")
    stft_ms = 512 / 16000 * 1e3
    print(f"  A 512-point / 16 kHz overlap-save STFT beamformer would add {stft_ms:.0f} ms "
          f"on its own\n  ({stft_ms / total:.0f}x this entire chain) - which is why the "
          "beamformer here is time domain.")

    # -- 7 ------------------------------------------------------------------ #
    ng = integrate_noise(geo, fir0, cfg)
    ng_dsb = integrate_noise(geo, fir_dsb, dsb_cfg)
    gs = GainStaging(room_noise_gain_dba=ng.room_gain_dba,
                     self_noise_penalty_dba=ng.self_noise_penalty_dba)
    print("\n[7] NOISE AND GAIN STAGING")
    print("  A-weighted over the 120 Hz - 8 kHz output band:")
    print(f"    gain against diffuse room noise (follows DI)   : "
          f"{ng.room_gain_dba:+.1f} dB  "
          f"(delay-and-sum: {ng_dsb.room_gain_dba:+.1f} dB)")
    print(f"    penalty on mic self-noise (follows WNG)        : "
          f"{ng.self_noise_penalty_dba:+.1f} dB  "
          f"(delay-and-sum: {ng_dsb.self_noise_penalty_dba:+.1f} dB)")
    print("    self-noise is uncorrelated between elements, so it is governed by "
          "white-noise\n    gain, not directivity; the two move in opposite "
          "directions in a superdirective\n    design, which is why WNG is "
          "constrained rather than left free.")
    print(f"\n  mic sensitivity / self-noise / AOP : {gs.mic_sensitivity_dbv_per_pa:.0f} dBV/Pa, "
          f"{gs.mic_self_noise_dba:.0f} dBA, {gs.mic_aop_db_spl:.0f} dB SPL")
    print(f"  preamp gain                        : {gs.preamp_gain_db:.0f} dB")
    print(f"  SPL at ADC full scale              : {gs.spl_at_full_scale():.0f} dB SPL "
          f"({gs.mic_aop_db_spl - gs.spl_at_full_scale():.0f} dB below the mic's AOP, "
          "so the ADC clips first)")
    for spl, what in ((45.0, "quiet room noise floor"), (55.0, "far talker at 3 m"),
                      (65.0, "normal talker at 1.5 m"), (85.0, "loud / close talker")):
        print(f"    {what:<30}{spl:>5.0f} dB SPL -> {gs.dbfs_for_spl(spl):>7.1f} dBFS/mic")
    print(f"  mic self-noise, one channel        : {gs.self_noise_dbfs(beamformed=False):.1f} dBFS")
    print(f"  mic self-noise, beam output        : {gs.self_noise_dbfs(beamformed=True):.1f} dBFS "
          f"(= {gs.mic_self_noise_dba + ng.self_noise_penalty_dba:.0f} dBA SPL equivalent)")
    print(f"  45 dBA room noise, beam output     : "
          f"{gs.room_noise_dbfs(45.0, beamformed=True):.1f} dBFS "
          f"(= {45.0 - ng.room_gain_dba:.0f} dBA SPL equivalent)")
    snr = gs.dbfs_for_spl(65.0) - gs.room_noise_dbfs(45.0, beamformed=True)
    print(f"  -> talker-to-room-noise at the output: {snr:.1f} dB "
          f"(unprocessed single mic: {65.0 - 45.0:.0f} dB)")
    print(f"  AGC target                         : {gs.agc_target_dbfs:.0f} dBFS")
    print(f"  DAC 0 dBFS                         : +{gs.dac_full_scale_dbu:.0f} dBu balanced "
          f"= {dbu_to_vrms(gs.dac_full_scale_dbu):.2f} Vrms")
    print(f"  nominal output                     : +{gs.nominal_out_dbu:.0f} dBu "
          f"= {dbu_to_vrms(gs.nominal_out_dbu):.3f} Vrms, at "
          f"{gs.nominal_out_dbu - gs.dac_full_scale_dbu:.0f} dBFS")
    print(f"  headroom above nominal             : {gs.headroom_db():.0f} dB")
    print(f"  unbalanced output                  : -10 dBV = "
          f"{dbu_to_vrms(-7.78):.3f} Vrms nominal, 0 dBFS = 2.0 Vrms")

    # -- 8 ------------------------------------------------------------------ #
    print("\n[8] COMPUTE BUDGET")
    mac_bf = geo.n_mic * cfg.n_taps * cfg.fs_hz * 2.0
    mac_cal = geo.n_mic * 7 * cfg.fs_hz
    pairs = geo.n_mic * (geo.n_mic - 1) // 2
    n_bin = int((scfg.f_max_hz - scfg.f_min_hz) / (scfg.fs_hz / scfg.frame))
    n_beam = scfg.grid().size
    mac_srp = pairs * n_bin * n_beam * (scfg.fs_hz / scfg.hop)
    total_mac = (mac_bf + mac_cal + mac_srp) / 1e6
    print(f"  beamformer, 2 beams cross-fading : {mac_bf / 1e6:>8.1f} MMAC/s")
    print(f"  per-mic calibration FIR          : {mac_cal / 1e6:>8.1f} MMAC/s")
    print(f"  SRP-PHAT, {pairs} pairs x {n_beam} beams   : {mac_srp / 1e6:>8.1f} MMAC/s")
    print(f"  {'-' * 33}{'-' * 10}")
    print(f"  {'TOTAL':<33}{total_mac:>9.1f} MMAC/s")
    print(f"  beam coefficient storage         : "
          f"{n_beam_bank * geo.n_mic * cfg.n_taps * 4 / 1024:>8.0f} kB (float32, "
          f"{n_beam_bank} beams)")
    print()

    return {
        "n_mic": geo.n_mic,
        "aperture_mm": geo.aperture_m * 1e3,
        "di_mean_db": di_avg,
        "di_dsb_db": di_dsb,
        "wng_min_db": wng_min,
        "on_axis_ripple_db": ripple,
        "group_delay_hf_ms": gd_hf,
        "group_delay_lf_ms": gd_lf,
        "total_latency_hf_ms": total,
        "total_latency_lf_ms": total + (gd_lf - gd_hf),
        "steered": steered,
        "beam_crossover_loss_db": grid_loss,
        "tolerance": tol_all,
        "localisation_median_deg": loc,
        "tracking": track,
        "mmac_per_s": total_mac,
        "spl_at_full_scale_db": gs.spl_at_full_scale(),
        "room_noise_gain_dba": ng.room_gain_dba,
        "self_noise_penalty_dba": ng.self_noise_penalty_dba,
        "beamwidth_deg": widths,
        "n_beams": n_beam_bank,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--taps", type=int, default=192, help="FIR taps per microphone")
    p.add_argument("--fs", type=float, default=48000.0, help="processing sample rate, Hz")
    p.add_argument("--gamma", type=float, default=0.10, help="diffuse-noise weight")
    p.add_argument("--rho", type=float, default=1e-2, help="white-noise weight")
    p.add_argument("--quick", action="store_true", help="fewer Monte-Carlo trials")
    p.add_argument("--json", action="store_true", help="also emit the summary as JSON")
    a = p.parse_args()

    cfg = DesignConfig(fs_hz=a.fs, n_taps=a.taps, gamma_diffuse=a.gamma, rho_white=a.rho)
    summary = run_report(cfg, quick=a.quick)
    if a.json:
        print(json.dumps(summary, indent=2, default=float))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
