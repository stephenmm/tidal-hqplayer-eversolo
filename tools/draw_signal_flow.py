#!/usr/bin/env python3
"""Draw docs/schematics/flow.svg - which way each audio stream runs inside the
reSpeaker XVF3800, and what an I2S tap could and could not achieve.

    python3 tools/draw_signal_flow.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from schematic_svg import *  # noqa: F403
from draw_schematics import standalone

def flow() -> str:
    o: list[str] = []
    o.append(txt(24, 22, "WHICH WAY EACH STREAM RUNS", "start", "hdr"))
    o.append(txt(24, 38, "The microphone path and the loudspeaker path are separate, and they "
                         "run in opposite directions.", "start", "note"))
    Y1, Y2, Y3 = 96, 216, 324

    # ---- capture ------------------------------------------------------- #
    o.append(txt(24, Y1 - 24, "CAPTURE &#8212; your room to the far end", "start", "hdr",
                 "var(--accent)"))
    o.append(box(24, Y1 - 16, 92, 44, "talker", "your room"))
    o.append(arrow(116, Y1 + 6, 148, Y1 + 6, accent=True))
    o.append(box(148, Y1 - 16, 84, 44, "4 mics", "PDM"))
    o.append(arrow(232, Y1 + 6, 264, Y1 + 6, accent=True))
    o.append(box(264, Y1 - 16, 150, 44, "XVF3800", "beamformer + AEC", accent=True))
    o.append(arrow(414, Y1 + 6, 452, Y1 + 6, accent=True))
    o.append(txt(433, Y1 - 4, "beam", "middle", "val", "var(--accent)"))
    o.append(box(452, Y1 - 16, 104, 44, "USB IN", "or I2S DATA1"))
    o.append(arrow(556, Y1 + 6, 590, Y1 + 6, accent=True))
    o.append(box(590, Y1 - 16, 104, 44, "host", "PC or MCU"))
    o.append(txt(356, Y1 + 44, "58 ms of delay lives here", "start", "note", "var(--cost)"))

    # ---- playback ------------------------------------------------------ #
    o.append(txt(24, Y2 - 24, "PLAYBACK &#8212; the far end into your room", "start", "hdr"))
    o.append(box(590, Y2 - 16, 104, 44, "host", "PC or MCU"))
    o.append(arrow(590, Y2 + 6, 556, Y2 + 6))
    o.append(box(452, Y2 - 16, 104, 44, "USB OUT", "or I2S DATA0"))
    o.append(arrow(452, Y2 + 6, 414, Y2 + 6))
    o.append(box(264, Y2 - 16, 150, 44, "DAC", "TLV320AIC3104"))
    o.append(arrow(264, Y2 + 6, 232, Y2 + 6))
    o.append(box(120, Y2 - 16, 112, 44, "jack / speaker", "3.5 mm, JST"))
    o.append(arrow(120, Y2 + 6, 88, Y2 + 6))
    o.append(box(24, Y2 - 16, 64, 44, "room", None))
    o.append(txt(339, Y2 + 44, "carries the far end, never the beam", "middle", "note"))

    # ---- the route that does not exist --------------------------------- #
    o.append(wire((300, Y1 + 28), (300, Y2 - 16), dash="5 4"))
    my = (Y1 + 28 + Y2 - 16) / 2
    o.append(f'<line x1="291" y1="{my-9}" x2="309" y2="{my+9}" stroke="var(--cost)" stroke-width="2.2"/>')
    o.append(f'<line x1="309" y1="{my-9}" x2="291" y2="{my+9}" stroke="var(--cost)" stroke-width="2.2"/>')
    o.append(txt(318, my + 4, "no route inside the chip", "start", "note", "var(--cost)"))

    # ---- the tap -------------------------------------------------------- #
    o.append(wire((24, 272), (410, 272), dash="4 4"))
    o.append(txt(24, 292, "WHAT YOU COULD BUILD &#8212; tap the beam off I2S", "start", "hdr",
                 "var(--accent)"))
    o.append(dot(573, Y1 + 6, accent=True))
    o.append(wire((573, Y1 + 6), (573, 300), (223, 300), (223, Y3), accent=True))
    o.append(box(148, Y3, 150, 44, "I2S DATA1", "the beam, PCM", accent=True))
    o.append(arrow(298, Y3 + 22, 330, Y3 + 22, accent=True))
    o.append(box(330, Y3, 116, 44, "I2S DAC", "PCM5102A"))
    o.append(arrow(446, Y3 + 22, 478, Y3 + 22, accent=True))
    o.append(box(478, Y3, 120, 44, "line driver", "THAT 1646"))
    o.append(arrow(598, Y3 + 22, 630, Y3 + 22, accent=True))
    o.append(txt(638, Y3 + 26, "XLR", "start", "ref", "var(--accent)"))
    o.append(txt(148, Y3 + 66, "A standalone box with a real balanced output and no computer "
                               "in the audio path.", "start", "note"))
    o.append(txt(148, Y3 + 80, "It does not reduce the 58 ms: that delay is inside the "
                               "XVF3800, upstream of the tap.", "start", "note", "var(--cost)"))
    return svg(720, 430, "".join(o),
               "Signal flow inside the reSpeaker XVF3800: the capture path carries the "
               "beamformed microphone signal to the host with 58 ms of delay, the playback "
               "path carries far-end audio from the host to the loudspeaker, the two never "
               "connect inside the device, and a tap on the I2S beam output could feed an "
               "external DAC and balanced line driver")

def main() -> int:
    out = pathlib.Path(__file__).resolve().parent.parent / "docs" / "schematics"
    out.mkdir(parents=True, exist_ok=True)
    svg_text = standalone(flow())
    (out / "flow.svg").write_text(svg_text)
    print(f"  flow.svg  {len(svg_text):6d} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
