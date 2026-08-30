# Low-Latency Talker-Tracking Microphone Line Array

A 16-channel steered line array that locks onto whoever is talking, delivers a
balanced line-level feed, and does it in **1.4 ms** from diaphragm to XLR pin 2.

Every number in this document is produced by
[`tools/mic_line_array_design.py`](../tools/mic_line_array_design.py) — run it to
regenerate them. Nothing here is a rule of thumb; the beamformer figures are
measured from the *truncated* FIR bank that would actually run on the DSP, not
from idealised frequency-domain weights.

---

## 1. The brief, as interpreted

| Requirement | What it was taken to mean |
|---|---|
| "microphone line array" | A linear (1-D) array — resolves bearing along one axis, mounted on a wall, table edge or above a display |
| "finds the primary talker" | Fully automatic: no operator, no presets. Localise, decide who is *primary*, steer, and hand over cleanly when someone else takes the floor |
| "minimum delay" | Latency is a first-class design constraint, budgeted term by term and traded against directivity explicitly — not whatever falls out of a convenient DSP structure |
| "line level for output" | Calibrated, standards-compliant analogue output: balanced +4 dBu with real headroom, plus unbalanced −10 dBV |

Two consequences that shape everything below:

- **Minimum delay rules out the obvious architecture.** The textbook broadband
  beamformer runs in the STFT domain. A 512-point frame at 16 kHz costs 32 ms of
  algorithmic latency *before* any filtering — 23× this entire signal chain. The
  beamformer here is therefore time-domain FIR throughout.
- **Steering must not be continuous.** Re-deriving filter coefficients per frame
  makes latency and stability a function of the tracker. Instead a fixed bank of
  34 pre-computed beams is stored, two run in parallel, and steering is a
  cross-fade between them — which adds exactly zero delay.

---

## 2. Headline specification

| Parameter | Value |
|---|---|
| Microphones | 15 in the array + 1 rear-facing reference = 16 ADC channels |
| Aperture | 513.6 mm |
| Coverage | ±75° from broadside, 34 beams |
| Bandwidth | 120 Hz – 8 kHz (wideband speech) |
| **Latency, mic to line out** | **1.42 ms** above 3 kHz; 2.21 ms below 250 Hz |
| Directivity index | 9.5 dB mean (200 Hz – 7 kHz), 11.9 dB at 6.3 kHz |
| A-weighted room-noise rejection | 6.1 dB |
| A-weighted self-noise | 19 dBA SPL equivalent at the beam output |
| On-axis response flatness | ±0.5 dB (1.00 dB peak-to-peak) |
| White-noise gain | ≥ −0.4 dB at all frequencies and all beams |
| Talker localisation | 0.06° median error (quiet), 0.27° at 5 dB SNR |
| Hand-over time | 160 ms to lock onto a new talker |
| Output | +4 dBu balanced (+18 dBu clip) / −10 dBV unbalanced |
| Compute | 329 MMAC/s, 382 kB coefficient storage |

---

## 3. What a line array cannot do

Stating this up front, because it constrains where the product can be mounted:

- **Cone ambiguity.** A linear array measures only the angle to the array *axis*.
  Every source on a cone around that axis produces identical inter-microphone
  delays. In a plane this collapses to a front/back mirror: θ and 180° − θ are
  indistinguishable.
- **No elevation.** A talker standing and the same talker seated at the same
  bearing are the same signal.
- **No range.** Two talkers on the same bearing at different distances cannot be
  separated at all.

Mitigations, in order of cost: mount the array against a wall, table edge or
display bezel so the rear hemisphere is physically baffled; use the 16th
(rear-facing) microphone as a front/back discriminator and as a noise reference;
and if genuine 2-D coverage is needed, this design is the row element of an L or
cross array — the beamformer maths below is unchanged, only the steering
manifold grows.

---

## 4. Geometry

Base grid pitch **21.4 mm = λ/2 at 8 kHz**. This is the binding spatial-sampling
constraint: for steering to ±75° without a grating lobe entering visible space,
the pitch must satisfy `d ≤ λ / (1 + sin θmax)` = 42.88 / 1.966 = **21.8 mm**, so
21.4 mm holds with a little margin.

Element positions are chosen so that three *uniform* octave sub-arrays are
embedded in one 15-element aperture and share elements:

| Sub-array | Elements | Pitch | Aperture | Alias-free to |
|---|---|---|---|---|
| LF | 7 | 85.6 mm | 513.6 mm | 2004 Hz |
| MF | 7 | 42.8 mm | 256.8 mm | 4007 Hz |
| HF | 7 | 21.4 mm | 128.4 mm | 8014 Hz |

Positions, mm from centre:

```
-256.8  -171.2  -128.4  -85.6  -64.2  -42.8  -21.4   0
  +21.4  +42.8   +64.2  +85.6 +128.4 +171.2 +256.8
```

**The nesting is a spatial-sampling guarantee, not a runtime band split.** The
beamformer uses all 15 elements at every frequency; the optimiser decides the
weighting and naturally de-emphasises the widely-spaced outer elements at high
frequency. The nested positions simply guarantee that *some* adequately-sampled
sub-aperture exists in every octave, so the optimiser is never asked to do the
impossible. The measured pattern confirms it works: peak sidelobe −13.7 dB and
mean off-lobe rejection −21.7 dB at 6.3 kHz, with no grating lobe anywhere.

At the other end, 513.6 mm is only 0.37 λ at 250 Hz. No amount of aperture
shading gives useful directivity from a third of a wavelength — which is why the
beamformer below is superdirective rather than delay-and-sum, and why its
robustness constraint matters so much.

---

## 5. Signal chain

```
 15x analog MEMS       16-ch                    fixed-point / float DSP
    ┌────────┐      ┌──────────┐   TDM    ┌───────────────────────────────┐
    │  mic   ├─30dB─┤          │          │  per-mic calibration FIR (7)  │
    │  x15   │      │  2x 8-ch ├─────────►│              │                │
    └────────┘      │   ADC    │  48 kHz  │       ┌──────┴──────┐         │
    ┌────────┐      │  24-bit  │  shared  │       │             │         │
    │rear ref├─30dB─┤          │  MCLK    │  beam[k] FIR   beam[k'] FIR   │
    └────────┘      └──────────┘          │   15x192        15x192        │
                                          │       └──────┬──────┘         │
                                          │        cross-fade (30 ms)     │
                                          │              │                │
                                          │      AGC / limiter (0 look)   │
                                          │              │                │
                          ┌───────────────┤   SRP-PHAT ──┘  (16 ms hop)   │
                          │  decimate     │   talker tracker              │
                          │  to 16 kHz    └───────────────────────────────┘
                          └───────────────────────────┐
                                                      ▼
                                        ┌──────────┐    ┌─────────────┐
                                        │   DAC    ├───►│  balanced   ├──► XLR  +4 dBu
                                        │  24-bit  │    │ line driver ├──► RCA  -10 dBV
                                        └──────────┘    └─────────────┘
```

The localisation path is deliberately **off the audio path**. It runs at 16 kHz
on 32 ms frames — 32 ms of analysis latency that costs nothing, because it only
selects which pre-computed beam is active. The audio never passes through it.

---

## 6. Beamformer

### 6.1 Formulation

Stack every FIR tap into one vector `h`, with `h[(m,n)] = h[m·L + n]` for
microphone `m` and tap `n`. The array's response to a plane wave from θ₀ is then
linear in `h`:

```
R(f) = a(f)ᵀ h ,      a(f)[(m,n)] = d_m(f) · e^{-j2πf n / fs}
```

The design is a single regularised least-squares problem:

```
minimise   Σ_f w_f |a(f)ᵀh − t(f)|²        response fit
         + γ Σ_f u_f · hᵀ Re(Eᴴ Γ(f) E) h  diffuse-field output noise power
         + ρ Σ_f u_f · hᵀ Re(Eᴴ E) h       white (self-) noise output power
```

with target `t(f) = S(f)·e^{-j2πf·τ(f)}` — the intended band shape `S` carrying
the intended group delay `τ`. Γ(f) is the spherically-isotropic coherence
`sinc(2fd/c)`.

Three things make this practical:

- **The normal-equation matrix is block-Toeplitz.** Every (m,m′) block depends
  only on the tap lag `n − n′`, so the 2880 × 2880 system is assembled from 1-D
  kernels of length 2L−1 rather than a triple loop. Build time is ~1 s.
- **γ is the directivity knob, ρ is the robustness knob.** γ = 0 gives plain
  delay-and-sum; increasing γ buys directivity and spends on-axis flatness. ρ
  sets the white-noise gain floor directly.
- **`u_f` must be non-zero at every frequency, including outside the output
  band.** This is the trap. Where the noise weight is zero, the individual
  channel gains are unconstrained — the fit only requires that they *cancel* on
  axis, and the superdirective solution happily makes them enormous and
  opposite. Costs nothing on paper; in the first version of this design it
  produced tens of dB of out-of-band self-noise gain and zero tolerance to
  mismatch. Holding `u_f` at 0.25 outside the band fixes it.

Operating point: **γ = 0.1, ρ = 0.01, L = 192 taps at 48 kHz** (4.00 ms span).

### 6.2 Frequency-dependent group delay

The single most important latency decision. The target delay τ(f) is **not**
constant: 1.50 ms below 200 Hz, tapering to 0.70 ms above 3 kHz.

Two independent reasons, and they agree:

1. **Aperture crossing is a hard physical floor.** Any beamformer that coherently
   sums an aperture `A` steered at θ must wait for the wavefront to cross it:
   `A·sin θ / c`. At ±75° the full 513.6 mm LF aperture needs
   `0.5136 × sin 75° / 343` = **1.45 ms** — so τ_LF = 1.50 ms is that floor plus
   margin, not an arbitrary choice. But high frequencies only use the inner
   128.4 mm sub-aperture, needing just 0.36 ms. Forcing HF to wait for the LF
   aperture would throw away a millisecond for nothing.
2. **The ear tolerates delay unevenly.** Blauert & Laws put the audibility
   threshold for group delay at roughly 1.6 ms at 8 kHz, 2 ms at 4 kHz, 3.2 ms at
   1 kHz and 10 ms at 500 Hz. Spending delay where it is both *needed* and
   *inaudible* is free.

The taper must be gentle. A steep dτ/df is an all-pass a short FIR cannot
realise, and it is paid for in on-axis ripple: an early attempt at
1.6 ms → 0.35 ms over 250–2000 Hz produced **7.5 dB** of ripple. The shipped
1.50 → 0.70 ms over 200–3000 Hz produces **1.00 dB**.

### 6.3 Measured performance, broadside beam

| f (Hz) | DI (dB) | WNG (dB) | Group delay (ms) | On-axis (dB) | DI, delay-and-sum |
|---|---|---|---|---|---|
| 125 | 0.8 | −1.4 | 1.51 | −0.44 | 0.1 |
| 250 | 2.6 | 0.3 | 1.42 | −0.64 | 0.5 |
| 500 | 4.1 | 5.1 | 0.84 | −0.27 | 1.7 |
| 1000 | 6.2 | 8.0 | 0.54 | −0.23 | 4.3 |
| 2000 | 8.5 | 10.4 | 0.53 | −0.07 | 7.3 |
| 4000 | 10.5 | 11.0 | 0.70 | −0.07 | 9.9 |
| 6300 | 11.9 | 11.2 | 0.70 | −0.05 | 11.5 |

Mean DI 200 Hz – 7 kHz: **9.54 dB**, against 8.56 dB for delay-and-sum on the
same array. Superdirectivity is worth about 1 dB broadband — and about 2 dB
across 250 Hz – 1 kHz, peaking at 2.4 dB near 500 Hz, which is where room noise
actually lives.

Beamwidth and sidelobes:

| f (Hz) | −6 dB beamwidth | Peak sidelobe | Mean off-lobe |
|---|---|---|---|
| 250 | 94° | −13.3 dB | −15.4 dB |
| 500 | 58° | −7.4 dB | −12.8 dB |
| 1000 | 34° | −13.3 dB | −18.9 dB |
| 2000 | 20° | −13.1 dB | −21.0 dB |
| 4000 | 10° | −10.6 dB | −20.6 dB |
| 6300 | 8° | −13.7 dB | −21.7 dB |

A superdirective design minimises *integrated* diffuse noise, so it places deep
nulls at particular angles rather than a smooth taper. The mean off-lobe column
is the meaningful figure; any single angle is not.

### 6.4 Steering

| Steered to | Mean DI | Ripple | Worst WNG | Group delay (HF) |
|---|---|---|---|---|
| 0° | 9.54 dB | 1.00 dB | −0.4 dB | 0.70 ms |
| 25° | 9.42 dB | 0.82 dB | 2.9 dB | 0.70 ms |
| 45° | 9.35 dB | 0.60 dB | 4.6 dB | 0.70 ms |
| 60° | 9.67 dB | 0.52 dB | 3.7 dB | 0.70 ms |
| 75° | 12.07 dB | 0.50 dB | 2.2 dB | 0.70 ms |

DI *rises* toward endfire — the main lobe narrows in the steering plane and the
ambiguity cone shrinks. More importantly, **group delay is identical for every
beam**, so a beam switch produces no timing step, only a gain cross-fade.

### 6.5 Beam grid

Beams are spaced uniformly in `u = sin θ`, not in angle — that is what keeps the
main lobe a constant width across coverage.

| Beam spacing Δu | Beams over ±75° | Worst cross-over loss |
|---|---|---|
| 0.06 | 34 | 1.16 dB |
| 0.10 | 21 | 3.23 dB |
| 0.15 | 14 | 7.74 dB |

**34 beams** chosen: a talker anywhere in coverage is within 1.2 dB of a beam
centre. Storage is 34 × 15 × 192 × 4 B = 382 kB.

### 6.6 Tolerance

300-trial Monte-Carlo with per-microphone gain 0.5 dB, phase 2°, position 0.3 mm
(1σ):

| | Value |
|---|---|
| Nominal DI | 9.54 dB |
| Mean DI | 9.53 dB |
| 5th-percentile DI | 9.52 dB |
| On-axis deviation, p95 | 0.99 dB |
| On-axis deviation, worst | 1.58 dB |

Essentially no degradation — which is the whole point of constraining WNG rather
than chasing maximum DI. An unconstrained superdirective design on this aperture
reaches higher DI on paper and falls apart on the bench.

---

## 7. Latency

| Stage | Delay | Notes |
|---|---|---|
| Mic + preamp + anti-alias | 0.02 ms | analogue, 1st order at 40 kHz |
| ADC decimation filter | 0.35 ms | **budget allocation — verify on the datasheet** |
| Calibration FIR, 7 tap | 0.07 ms | per-mic gain/phase trim |
| Beamformer FIR, above 3 kHz | 0.70 ms | *measured* from the FIR bank |
| Beam cross-fade | 0.00 ms | two beams in parallel |
| AGC / limiter | 0.00 ms | zero look-ahead, soft knee |
| DAC reconstruction filter | 0.28 ms | **budget allocation — verify on the datasheet** |
| Balanced line driver | 0.00 ms | analogue |
| **Total, speech band above 3 kHz** | **1.42 ms** | |
| Total, band below 250 Hz | 2.21 ms | inaudible per §6.2 |

Notes on the two largest terms:

- **The converters, not the DSP, dominate.** 0.63 ms of the 1.42 ms is ADC + DAC
  decimation/interpolation filtering. These two figures are *allocations*, not
  measurements — they assume the chosen converters offer a short-group-delay
  filter mode and that it is enabled. Confirm this before committing to parts;
  a converter in default linear-phase mode can be 3–5× worse and would dominate
  the budget on its own.
- **The AGC has no look-ahead.** A look-ahead limiter is the conventional choice
  and would add 0.3–1 ms. Instead: soft-knee compression with a fast release and
  a hard clip guard, accepting a few tenths of a dB of transient overshoot rather
  than paying for it in latency on every sample.
- **1.42 ms is 0.49 m of air.** For reinforcement into the same room, the array
  is acoustically closer to the listener than a loudspeaker half a metre away —
  the Haas-effect budget is essentially untouched.

---

## 8. Finding the primary talker

### 8.1 Localisation

SRP-PHAT on the 16 kHz path: 32 ms Hann frames, 16 ms hop, 300–3800 Hz, over a
65-point angular grid, with a parabolic fit through the peak for sub-grid
resolution. Rather than summing all 105 microphone-pair cross-spectra per
direction, the identity

```
Σ_{i<k} Re(x_i x_k* e^{-jω(τ_i-τ_k)}) = ( |Σ_i x_i d_i*|² − M ) / 2      (|x_i| = 1 after PHAT)
```

gives identical values in O(M) instead of O(M²) per direction.

| Scenario | Median error | Frames > 5° |
|---|---|---|
| Quiet room, single talker | 0.06° | 0.0 % |
| Noisy room, 5 dB SNR | 0.27° | 0.0 % |
| Competing talker 6 dB down | 0.17° | 14.5 % |
| Competing talker 3 dB down | 0.25° | 28.2 % |

The median is excellent throughout; the interesting column is the right-hand
one. With a competing talker only 3 dB down, more than a quarter of frames point
at the *wrong person*. Per-frame localisation is not talker tracking.

### 8.2 The tracker

Which is why the raw peak never steers anything. Between SRP-PHAT and the beam
bank sits a hysteretic state machine:

- Per-beam scores smoothed with a 120 ms time constant.
- A per-beam noise floor tracked with a 5 s running minimum and subtracted —
  this is what stops HVAC, a projector fan or a laptop on the table from being
  "the talker".
- A challenger must beat the held beam by **3 dB continuously for 150 ms**
  before the beam moves.
- 400 ms hangover after speech offset, so the beam does not wander during
  natural pauses.
- Beam changes cross-fade over 30 ms between the two running beamformers.

Measured on a turn-taking scenario — talker A at −35° for 3 s, then talker B at
+40°:

| | Result |
|---|---|
| Beam correctly on A before hand-over | 100 % of frames |
| Time to lock onto B | 160 ms |
| Total beam switches in 6 s | 1 |

One switch, where one switch was warranted. The 160 ms is essentially the
150 ms hysteresis window — i.e. the tracker is as fast as it is allowed to be,
and the trade is explicit and tunable rather than emergent.

---

## 9. Noise: two different gains

The classic error in superdirective array design is to quote the directivity
index and imply it applies to all noise. It does not:

- **Room noise** is close to a diffuse (spherically isotropic) field. The array's
  gain against it is the **directivity index**.
- **Microphone self-noise** is uncorrelated between elements. The array's gain
  against it is the **white-noise gain** — which a superdirective design drives
  *negative* at low frequency.

They move in opposite directions. A design tuned only on DI quietly trades a few
dB of room noise for a hiss that cannot be removed downstream.

A-weighted over the 120 Hz – 8 kHz output band, referenced to a single omni
microphone through the same band shaping:

| | This design | Delay-and-sum |
|---|---|---|
| Gain against diffuse room noise | **+6.1 dB** | +3.9 dB |
| Effect on mic self-noise | **−10.2 dB** | −11.8 dB |

Superdirectivity buys 2.2 dB more room-noise rejection and gives back 1.6 dB of
self-noise benefit. Since mic self-noise is 29 dBA and a real room is 40–45 dBA,
room noise dominates and the trade is clearly worth taking — but it is a trade,
and ρ is the knob if a quieter room or a noisier microphone changes the balance.

---

## 10. Output stage and gain staging

### 10.1 Acoustic to digital

| Point | Value |
|---|---|
| Mic sensitivity / self-noise / AOP | −38 dBV/Pa, 29 dBA, 130 dB SPL |
| Preamp gain | 30 dB |
| SPL at ADC full scale | 108 dB SPL |
| Quiet room noise floor, 45 dB SPL | −63.0 dBFS/mic |
| Far talker at 3 m, 55 dB SPL | −53.0 dBFS/mic |
| Normal talker at 1.5 m, 65 dB SPL | −43.0 dBFS/mic |
| Loud/close talker, 85 dB SPL | −23.0 dBFS/mic |
| Mic self-noise, one channel | −79.0 dBFS |
| Mic self-noise, beam output | −89.2 dBFS (= 19 dBA SPL equivalent) |
| 45 dBA room noise, beam output | −69.1 dBFS (= 39 dBA SPL equivalent) |
| Talker-to-room-noise at output | 26.1 dB (single mic: 20 dB) |

The 30 dB preamp gain puts ADC clip at 108 dB SPL — 22 dB below the
microphone's acoustic overload point, so the converter clips first and does so
gracefully. The system is microphone-noise-limited, not converter-limited
(−79 dBFS mic noise against roughly −110 dBFS for a 24-bit converter), which is
the right place to be: it means analogue gain can stay conservative and the rest
of the range can be taken digitally in 32-bit float without cost.

### 10.2 Digital to line

| Point | Value |
|---|---|
| AGC target | −20 dBFS |
| DAC 0 dBFS | +18 dBu balanced = 6.15 Vrms |
| Nominal output | +4 dBu = 1.228 Vrms, at −14 dBFS |
| Headroom above nominal | 14 dB |
| Unbalanced output | −10 dBV = 0.316 Vrms nominal; 0 dBFS = 2.0 Vrms |

Implementation:

- **Balanced (XLR):** DAC into a differential line driver (THAT 1646, DRV134 or
  an OPA1632 discrete equivalent) on ±15 V rails. +18 dBu clip = 6.15 Vrms
  differential = ±8.7 V peak per leg, comfortable on ±15 V with margin for the
  driver's own headroom. Output impedance 100 Ω per leg, servo-free DC blocking,
  and the driver must survive phantom power applied by a mistakenly-configured
  console — 48 V through 6.8 kΩ into a clamped output.
- **Unbalanced (RCA):** taken from the same DAC through a separate buffer at
  −16 dB relative to the balanced output, so 0 dBFS = 2.0 Vrms and nominal sits
  at the −10 dBV consumer standard.
- **AGC:** 20 dB of range, 10 ms attack, 300 ms release, holding the beam output
  at −20 dBFS. Deliberately slow enough not to pump on syllables, and frozen
  entirely when the tracker reports no speech so that it does not spend the pause
  winding up the room noise.

---

## 11. Hardware realisation

Candidate parts. Every latency-critical figure below must be confirmed against
the datasheet before commitment — particularly the converter filter modes, which
are the single largest fixed term in the latency budget.

| Block | Candidate | Why |
|---|---|---|
| Microphone | Analog MEMS, −38 dBV/Pa, ≥65 dB SNR (Knowles SPU0410LR5H class; TDK ICS-40730 for lower noise) | Analogue output keeps the decimation filter — and therefore its group delay — under our control rather than the microphone's |
| Preamp | Low-noise op-amp, fixed 30 dB | No variable gain: the array depends on channel matching, and a per-channel VGA is a matching liability |
| ADC | 2 × 8-channel 24-bit TDM (AKM AK5578 class), **low-latency filter mode** | Simultaneous sampling, one shared MCLK, TDM keeps the pin count sane |
| DAC | 24-bit stereo (PCM5242 class), low-latency mode | |
| Line driver | THAT 1646 / DRV134, ±15 V | |
| DSP | ADI ADSP-21569 SHARC+ or XMOS xcore.ai XU316 | 329 MMAC/s with headroom; both have native TDM and enough on-chip RAM for the 382 kB beam bank |

**Mechanical and acoustic.** Element position tolerance ±0.3 mm (the Monte-Carlo
in §6.6 is run at that figure). Sealed acoustic ports with gaskets, mesh over
each port for dust and pop, and the PCB decoupled from the enclosure so
structure-borne vibration does not couple in — a vibration path is coherent
across elements and therefore beamforms *perfectly*, straight into the output.

**Calibration.** Superdirectivity at low frequency is sensitive to gain and phase
mismatch. Each unit is calibrated at end-of-line against a reference source, and
a 7-tap correction FIR per microphone is stored in NVM. The 0.07 ms this costs is
already in the latency budget.

**Clocking.** One MCLK domain for all converters. TDM is a serial bus but the
sample instants are simultaneous, so there is no inter-channel skew to correct —
worth stating explicitly because it is a common source of unexplained
beamformer degradation when it is *not* true.

---

## 12. Compute budget

| Block | Cost |
|---|---|
| Beamformer, 2 beams cross-fading (15 × 192 × 48 kHz × 2) | 276.5 MMAC/s |
| Per-mic calibration FIR (15 × 7 × 48 kHz) | 5.0 MMAC/s |
| SRP-PHAT (105 pairs × 65 beams, 62.5 fps) | 47.8 MMAC/s |
| **Total** | **329.3 MMAC/s** |
| Beam coefficient storage | 382 kB (float32, 34 beams) |

The beamformer dominates, and it is dominated in turn by the 192-tap length —
which is set by the 4 ms filter span needed to shape a beam at 200 Hz. This is
the real cost of low-frequency directivity, and it is paid in MACs rather than in
latency only because of the group-delay taper in §6.2.

---

## 13. Reproducing these numbers

```bash
pip install numpy
python3 tools/mic_line_array_design.py            # full report, ~3 min
python3 tools/mic_line_array_design.py --quick    # fewer Monte-Carlo trials
python3 tools/mic_line_array_design.py --json     # machine-readable summary
```

Useful knobs for exploring the trade space:

```bash
--gamma 0.3    # more directivity, more on-axis ripple
--rho 0.03     # more robustness, less directivity
--taps 256     # longer filters: marginally better LF, more MACs
```

The script is typed and clean under `mypy --strict`.

---

## 14. Deliberately out of scope

- **Acoustic echo cancellation.** Needed for any duplex conferencing use. A
  time-domain NLMS AEC adds no latency and would sit between the beamformer and
  the AGC, with the loudspeaker feed as reference. It is a substantial subsystem
  in its own right.
- **Dereverberation.** The array's directivity attenuates the reverberant field
  by construction (that is the 6.1 dB in §9); explicit dereverberation would add
  latency and is usually not worth it at this DI.
- **Multiple simultaneous outputs.** The architecture extends naturally to N
  independent talker feeds — N more beamformer instances at 138 MMAC/s each —
  but "the primary talker" was specified as singular.
- **Elevation.** Requires a second axis; see §3.
