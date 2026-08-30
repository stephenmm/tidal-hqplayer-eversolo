#!/usr/bin/env python3
"""Regenerate the five section schematics in docs/schematics/.

    python3 tools/draw_schematics.py

No dependencies. Symbols come from tools/schematic_svg.py; everything sits on an
8 px grid, which is most of what stops a hand-placed drawing looking accidental.
The files written here are standalone: literal colours and their own type rules,
because the CSS variables the published page uses do not exist outside it.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from schematic_svg import *  # noqa: F403

def hdr(t: str, sub: str, sub2: str | None = None) -> str:
    o = txt(24, 24, t, "start", "hdr") + txt(24, 40, sub, "start", "note")
    if sub2:
        o += txt(24, 54, sub2, "start", "note")
    return o

# --------------------------------------------------------------------- 1 --- #
def mic_channel() -> str:
    o: list[str] = [hdr("MICROPHONE CHANNEL &#8212; ONE OF SIXTEEN",
             "VREF is buffered once and shared by all channels. R3/R4 at 0.1 % give "
             "0.012 dB of channel-to-channel gain error.")]
    Y = 214
    # capsule
    o.append(box(30, 182, 80, 64, "MEMS", "-38 dBV/Pa"))
    o.append(txt(30, 174, "MK1", "start", "ref"))
    o.append(wire((70, 182), (70, 146)))
    o.append(rail(70, 146, "AVDD 3V3"))
    o.append(dot(70, 158))
    o.append(wire((70, 158), (142, 158)))
    o.append(cap(142, 168, "C1", "100n", horiz=False))
    o.append(wire((142, 158), (142, 164)))
    o.append(wire((142, 172), (142, 186)))
    o.append(gnd(142, 186))
    o.append(wire((70, 246), (70, 262)))
    o.append(gnd(70, 262))
    # input coupling
    o.append(wire((110, Y), (168, Y)))
    o.append(cap(182, Y, "C2", "1u", polar=True))
    o.append(wire((186, Y), (224, Y)))
    o.append(dot(224, Y))
    # bias resistor to VREF, routed downward
    o.append(res(224, 252, "R1", "100k", horiz=False, flip=True))
    o.append(wire((224, Y), (224, 237)))
    o.append(wire((224, 267), (224, 278)))
    o.append(rail(224, 278, "VREF", down=True))
    # amplifier: + pin sits on the signal rail
    tri, mi, pl, out = opamp(272, 174, "U1a", w=46, h=56)
    o.append(tri)
    o.append(wire((224, Y), (272, Y)))
    # inverting node, gain network above the body
    o.append(wire((250, 190), (272, 190)))
    o.append(wire((250, 190), (250, 140)))
    o.append(dot(250, 158))
    o.append(res(210, 158, "R3", "1k00"))
    o.append(wire((250, 158), (225, 158)))
    o.append(wire((195, 158), (172, 158), (172, 140)))
    o.append(rail(172, 140, "VREF"))
    o.append(res(285, 140, "R4", "30k9"))
    o.append(wire((250, 140), (270, 140)))
    o.append(wire((300, 140), (336, 140), (336, 202)))
    # output, anti-alias, coupling
    o.append(wire((318, 202), (336, 202)))
    o.append(dot(336, 202))
    o.append(wire((336, 202), (360, 202)))
    o.append(res(375, 202, "R5", "1k"))
    o.append(wire((390, 202), (430, 202)))
    o.append(dot(415, 202))
    o.append(cap(415, 232, "C4", "3n9", horiz=False, flip=True))
    o.append(wire((415, 202), (415, 228)))
    o.append(wire((415, 236), (415, 252)))
    o.append(gnd(415, 252))
    o.append(cap(468, 202, "C5", "2u2", polar=True))
    o.append(wire((430, 202), (464, 202)))
    o.append(wire((472, 202), (508, 202)))
    o.append(arrow(508, 202, 542, 202, accent=True))
    o.append(txt(550, 197, "to ADC", "start", "ref", "var(--accent)"))
    o.append(txt(550, 211, "channel n", "start", "val", "var(--accent)"))
    # design notes along the bottom
    o.append(txt(150, 322, "input pole 1.6 Hz", "middle", "note"))
    o.append(txt(310, 322, "gain = 1 + R4/R3 = 30.0 dB", "middle", "note"))
    o.append(txt(480, 322, "anti-alias pole 41 kHz", "middle", "note"))
    return svg(700, 344, "".join(o),
               "Schematic of one microphone channel: MEMS capsule, AC coupling, a 30 dB "
               "non-inverting preamplifier referenced to a shared mid-rail, an anti-alias "
               "pole and output coupling to the ADC")

# --------------------------------------------------------------------- 2 --- #
def poc_channel() -> str:
    o: list[str] = [hdr("PROOF-OF-CONCEPT CHANNEL &#8212; ELECTRET INTO AN AUDIO INTERFACE",
             "Hand-solderable throughout. No MEMS, no converters and no clock on the "
             "breadboard &#8212; which is what makes it buildable.")]
    Y = 150
    o.append(rail(100, 92, "+5 V"))
    o.append(wire((100, 92), (100, 103)))
    o.append(res(100, 118, "R1", "2k2", horiz=False, flip=True))
    o.append(wire((100, 133), (100, 150)))
    o.append(dot(100, Y))
    o.append(f'<circle cx="100" cy="190" r="20" fill="none" stroke="currentColor" stroke-width="1.4"/>')
    o.append(txt(100, 194, "MK1", "middle", "ref"))
    o.append(wire((100, Y), (100, 170)))
    o.append(wire((100, 210), (100, 226)))
    o.append(gnd(100, 226))
    o.append(txt(100, 262, "electret capsule", "middle", "note"))
    o.append(wire((100, Y), (176, Y)))
    o.append(cap(190, Y, "C1", "1u", polar=True))
    o.append(wire((194, Y), (232, Y)))
    o.append(res(247, Y, "R2", "100R"))
    o.append(wire((262, Y), (300, Y)))
    o.append(dot(285, Y))
    o.append(res(285, 182, "R3", "10k", horiz=False))
    o.append(wire((285, Y), (285, 167)))
    o.append(wire((285, 197), (285, 214)))
    o.append(gnd(285, 214))
    o.append(arrow(300, Y, 340, Y, accent=True))
    o.append(box(344, 116, 150, 68, "audio interface", "mic input", accent=True))
    o.append(txt(419, 206, "PHANTOM POWER OFF", "middle", "note", "var(--cost)"))
    for i, line in enumerate([
            "One interface samples every channel",
            "simultaneously &#8212; the only property",
            "the array actually needs.",
            "",
            "Its own latency is irrelevant:",
            "validation happens offline."]):
        o.append(txt(524, 126 + i*16, line, "start", "note"))
    return svg(700, 284, "".join(o),
               "Schematic of a proof-of-concept microphone channel: an electret capsule "
               "with a bias resistor and coupling capacitor feeding an audio interface "
               "microphone input with phantom power switched off")

# --------------------------------------------------------------------- 3 --- #
def digital() -> str:
    o: list[str] = [hdr("DIGITAL SECTION &#8212; ONE CLOCK DOMAIN, ONE TDM BUS",
             "Sample instants are simultaneous across all four converters: the bus is "
             "serial, the sampling is not.")]
    o.append(box(24, 86, 92, 46, "OSC1", "24.576 MHz"))
    o.append(arrow(116, 109, 146, 109))
    o.append(box(150, 80, 84, 58, "U10", "clock fanout"))
    o.append(wire((234, 109), (258, 109), (258, 318)))
    ys = [162, 214, 266, 318]
    for i, y in enumerate(ys):
        o.append(dot(258, y))
        o.append(wire((258, y), (272, y)))
        o.append(res(287, y, "33R", ""))
        o.append(wire((302, y), (330, y)))
        o.append(box(330, y - 22, 118, 44, f"U{i+1}  ADC", f"slots {i*4}-{i*4+3}"))
        o.append(arrow(278, y + 14, 330, y + 14, accent=True))
        o.append(txt(274, y + 18, "4 ch", "end", "val", "var(--accent)"))
        o.append(wire((448, y), (496, y)))
        o.append(dot(496, y))
    o.append(wire((496, 162), (496, 318)))
    o.append(arrow(496, 162, 496, 122))
    o.append(txt(470, 358, "SDATA &#8212; wired-OR, one slot each", "start", "val"))
    # DSP and memories
    o.append(box(540, 86, 160, 110, "U20  DSP", "SHARC+ / xcore.ai", accent=True))
    o.append(wire((496, 122), (496, 112), (540, 112)))
    o.append(wire((620, 86), (620, 64), (192, 64), (192, 80)))
    o.append(txt(406, 58, "MCLK / BCLK / FSYNC / RESET", "middle", "val"))
    o.append(box(540, 216, 160, 40, "U21", "QSPI boot flash"))
    o.append(box(540, 268, 160, 40, "U22", "EEPROM: calibration"))
    o.append(wire((620, 196), (620, 216)))
    o.append(wire((620, 256), (620, 268)))
    o.append(txt(268, 382, "33R series on every clock branch. At 24.576 MHz a 545 mm board is a",
                 "start", "note"))
    o.append(txt(268, 396, "transmission line, so clocks are fanned out, never daisy-chained.",
                 "start", "note"))
    return svg(700, 412, "".join(o),
               "Schematic of the digital section: one oscillator fanned out through series "
               "terminations to four four-channel ADCs and the DSP, with all converter data "
               "returning on a single shared TDM line")

# --------------------------------------------------------------------- 4 --- #
def output() -> str:
    o: list[str] = [hdr("OUTPUT SECTION &#8212; BALANCED AND UNBALANCED",
             "0 dBFS = +18 dBu = 6.15 Vrms differential = &#177;4.35 V peak per leg, so "
             "&#177;12 V rails leave 7 V of margin.")]
    Y = 150
    o.append(txt(6, 110, "from DSP", "start", "val", "var(--accent)"))
    o.append(arrow(6, Y, 40, Y, accent=True))
    o.append(box(40, 116, 104, 68, "U30  DAC", "24-bit"))
    o.append(wire((144, 138), (190, 138)))
    o.append(wire((144, 162), (190, 162)))
    o.append(txt(167, 131, "OUT+", "middle", "val"))
    o.append(txt(167, 176, "OUT-", "middle", "val"))
    tri, mi, pl, out = opamp(190, 124, "U31", w=44, h=52)
    o.append(tri)
    o.append(txt(212, 206, "differential to single-ended", "middle", "note"))
    o.append(wire((234, Y), (268, Y)))
    o.append(dot(256, Y))
    o.append(box(268, 116, 108, 68, "U32", "THAT 1646"))
    o.append(rail(322, 116, "+12 V"))
    o.append(rail(322, 184, "-12 V", down=True))
    for dy, pin in ((-24, "XLR pin 2"), (24, "XLR pin 3")):
        o.append(wire((376, Y + dy), (400, Y + dy)))
        o.append(res(415, Y + dy, "R6" if dy < 0 else "R7", "100R"))
        o.append(wire((430, Y + dy), (450, Y + dy)))
        o.append(wire((530, Y + dy), (560, Y + dy)))
        o.append(arrow(560, Y + dy, 596, Y + dy, accent=True))
        o.append(txt(604, Y + dy + 4, pin, "start", "ref", "var(--accent)"))
    o.append(box(450, 116, 80, 68, "clamp", "TVS to rails"))
    o.append(txt(490, 202, "survives 48 V phantom", "middle", "note", "var(--cost)"))
    o.append(txt(415, 104, "build-out", "middle", "note"))
    o.append(txt(604, 206, "pin 1 = chassis", "start", "val"))
    o.append(wire((256, Y), (256, 246), (300, 246)))
    o.append(box(300, 226, 120, 40, "U33", "-16 dB buffer"))
    o.append(wire((420, 246), (560, 246)))
    o.append(arrow(560, 246, 596, 246, accent=True))
    o.append(txt(604, 250, "RCA, -10 dBV", "start", "ref", "var(--accent)"))
    return svg(740, 296, "".join(o),
               "Schematic of the output section: DAC differential outputs through a "
               "differential-to-single-ended stage into a balanced line driver feeding XLR "
               "through build-out resistors and a phantom-power clamp, plus an attenuated "
               "unbalanced RCA output")

# --------------------------------------------------------------------- 5 --- #
def power() -> str:
    o: list[str] = [hdr("POWER TREE",
             "Microphone PSRR is about -60 dB, so supply ripple lands almost directly in the audio:",
             "analogue rails are linear-regulated and the switchers stay on the far side of the split.")]
    o.append(box(24, 96, 96, 44, "12 V in", "fuse + TVS"))
    o.append(wire((120, 118), (160, 118), (160, 272)))
    rows = [
        (96,  "U40  buck", "3V3 digital", "U41  buck", "1V1 core", "DSP core and I/O", False),
        (176, "U42  LDO", "5V0 analogue", "U43  LDO", "3V3 analogue", "16 microphones", True),
        (272, "U44  DC-DC", "&#177;15 V", "U45/46  LDO", "&#177;12 V", "balanced line driver", True),
    ]
    for y, r1, v1, r2, v2, load, an in rows:
        o.append(dot(160, y))
        o.append(wire((160, y), (196, y)))
        o.append(box(196, y - 20, 116, 40, r1, v1, accent=an))
        o.append(arrow(312, y, 348, y, accent=an))
        o.append(box(352, y - 20, 122, 40, r2, v2, accent=an))
        o.append(arrow(474, y, 510, y, accent=an))
        o.append(txt(518, y + 4, load, "start", "val"))
    # preamp branch off the 5 V rail
    o.append(dot(330, 176))
    o.append(wire((330, 196), (330, 216)))
    o.append(arrow(330, 216, 366, 216, accent=True))
    o.append(txt(374, 220, "16 preamps", "start", "val"))
    o.append(txt(518, 152, "linear, no switcher in the analogue path", "start", "note",
                 "var(--accent)"))
    o.append(txt(518, 300, "LC post-filter: a 100-500 kHz switcher", "start", "note"))
    o.append(txt(518, 314, "is out of band, but its harmonics", "start", "note"))
    o.append(txt(518, 328, "intermodulate if they are let through", "start", "note"))
    o.append(wire((24, 356), (676, 356), dash="4 4"))
    o.append(txt(24, 374, "AGND and DGND meet at a single point beneath U1, the first ADC.",
                 "start", "note"))
    return svg(700, 388, "".join(o),
               "Power tree: a 12 V input feeding switching regulators for the digital rails "
               "and linear regulators for the analogue rails, with a separate isolated "
               "supply post-filtered for the balanced line driver")

STYLE = """<style>
.hdr{font:600 10px 'Helvetica Neue',Arial,sans-serif;letter-spacing:.13em;fill:#5c6e73}
.ref{font:500 11px 'DejaVu Sans Mono',Menlo,monospace;fill:#101a1e}
.val{font:10px 'DejaVu Sans Mono',Menlo,monospace;fill:#5c6e73}
.pin{font:11px 'DejaVu Sans Mono',Menlo,monospace;fill:#5c6e73}
.rail{font:10px 'DejaVu Sans Mono',Menlo,monospace;fill:#5c6e73}
.note,.lbl{font:10.5px 'Helvetica Neue',Arial,sans-serif;fill:#5c6e73}
</style>"""


def standalone(body: str) -> str:
    """Bake in literal colours, a type stylesheet and a painted background."""
    import re
    m = re.match(r'<svg viewBox="0 0 (\d+) (\d+)"', body)
    assert m
    w, h = int(m.group(1)), int(m.group(2))
    s = (body.replace("currentColor", "#101a1e")
             .replace("var(--accent)", "#0c6f7c")
             .replace("var(--cost)", "#a94e26")
             .replace("var(--muted)", "#5c6e73")
             .replace("<svg viewBox", '<svg xmlns="http://www.w3.org/2000/svg" viewBox', 1))
    i = s.index(">") + 1
    return s[:i] + STYLE + f'<rect width="{w}" height="{h}" fill="#f6f8f8"/>' + s[i:]


def main() -> int:
    out = pathlib.Path(__file__).resolve().parent.parent / "docs" / "schematics"
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("mic", mic_channel), ("poc", poc_channel), ("digital", digital),
                     ("output", output), ("power", power)):
        svg_text = standalone(fn())
        (out / f"{name}.svg").write_text(svg_text)
        print(f"  {name}.svg  {len(svg_text):6d} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
