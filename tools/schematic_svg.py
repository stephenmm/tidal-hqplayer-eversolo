"""Minimal SVG schematic primitives: everything on an 8 px grid, strokes in
currentColor so both page themes work, var(--accent) reserved for the one thing
each drawing is about."""
from __future__ import annotations

Pin = tuple[float, float]

U = 8  # grid unit

def _t(x: float, y: float, s: str, anchor: str = "start", cls: str = "lbl",
       fill: str | None = None) -> str:
    f = f' fill="{fill}"' if fill else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="{cls}"{f}>{s}</text>'

def txt(x: float, y: float, s: str, anchor: str = "start", cls: str = "lbl",
        fill: str | None = None) -> str:
    return _t(x, y, s, anchor, cls, fill)

def wire(*pts: tuple[float, float], accent: bool = False, dash: str | None = None) -> str:
    p = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    st = 'stroke="var(--accent)"' if accent else 'stroke="currentColor"'
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<polyline points="{p}" fill="none" {st} stroke-width="1.4"{d}/>'

def dot(x: float, y: float, accent: bool = False) -> str:
    c = "var(--accent)" if accent else "currentColor"
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{c}"/>'

def box(x: float, y: float, w: float, h: float, title: str, sub: str | None = None,
        accent: bool = False) -> str:
    st = "var(--accent)" if accent else "currentColor"
    o: list[str] = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="2" '
         f'fill="none" stroke="{st}" stroke-width="1.4"/>']
    if sub:
        o.append(_t(x + w/2, y + h/2 - 2, title, "middle", "ref"))
        o.append(_t(x + w/2, y + h/2 + 11, sub, "middle", "val"))
    else:
        o.append(_t(x + w/2, y + h/2 + 4, title, "middle", "ref"))
    return "".join(o)

def res(x: float, y: float, ref: str, val: str, horiz: bool = True,
        flip: bool = False) -> str:
    """Body centred on (x, y). IEC rectangle; leads drawn by the caller."""
    if horiz:
        w, h = 30, 12
        o: list[str] = [f'<rect x="{x-w/2:.1f}" y="{y-h/2:.1f}" width="{w}" height="{h}" fill="none" '
             f'stroke="currentColor" stroke-width="1.4"/>']
        o.append(_t(x, y - 10, ref, "middle", "ref"))
        o.append(_t(x, y + 20, val, "middle", "val"))
    else:
        w, h = 12, 30
        o = [f'<rect x="{x-w/2:.1f}" y="{y-h/2:.1f}" width="{w}" height="{h}" fill="none" '
             f'stroke="currentColor" stroke-width="1.4"/>']
        side = -1 if flip else 1
        a = "end" if flip else "start"
        o.append(_t(x + side*11, y - 2, ref, a, "ref"))
        o.append(_t(x + side*11, y + 9, val, a, "val"))
    return "".join(o)

def cap(x: float, y: float, ref: str, val: str, horiz: bool = True, polar: bool = False,
        flip: bool = False) -> str:
    """Two plates centred on (x, y), 8 px apart."""
    o: list[str] = []
    if horiz:
        o.append(f'<line x1="{x-4}" y1="{y-9}" x2="{x-4}" y2="{y+9}" stroke="currentColor" stroke-width="1.6"/>')
        o.append(f'<line x1="{x+4}" y1="{y-9}" x2="{x+4}" y2="{y+9}" stroke="currentColor" stroke-width="1.6"/>')
        o.append(_t(x, y - 14, ref, "middle", "ref"))
        o.append(_t(x, y + 24, val, "middle", "val"))
        if polar:
            o.append(_t(x - 11, y + 4, "+", "middle", "val"))
    else:
        o.append(f'<line x1="{x-9}" y1="{y-4}" x2="{x+9}" y2="{y-4}" stroke="currentColor" stroke-width="1.6"/>')
        o.append(f'<line x1="{x-9}" y1="{y+4}" x2="{x+9}" y2="{y+4}" stroke="currentColor" stroke-width="1.6"/>')
        side, a = (-13, "end") if flip else (13, "start")
        o.append(_t(x + side, y - 2, ref, a, "ref"))
        o.append(_t(x + side, y + 9, val, a, "val"))
    return "".join(o)

def opamp(x: float, y: float, ref: str, w: float = 46, h: float = 44,
          minus_top: bool = True) -> tuple[str, Pin, Pin, Pin]:
    """Triangle with apex right; (x, y) is the top-left of the bounding box."""
    o: list[str] = [f'<polygon points="{x},{y} {x},{y+h} {x+w},{y+h/2}" fill="none" '
         f'stroke="currentColor" stroke-width="1.4"/>']
    a, b = (y + h*0.28, y + h*0.72) if minus_top else (y + h*0.72, y + h*0.28)
    o.append(_t(x + 7, a + 4, "&#8722;", "middle", "pin"))
    o.append(_t(x + 7, b + 4, "+", "middle", "pin"))
    o.append(_t(x + w*0.45, y + h + 14, ref, "middle", "ref"))
    return "".join(o), (x, a), (x, b), (x + w, y + h/2)

def gnd(x: float, y: float) -> str:
    return ("".join([
        f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+7}" stroke="currentColor" stroke-width="1.4"/>',
        f'<line x1="{x-9}" y1="{y+7}" x2="{x+9}" y2="{y+7}" stroke="currentColor" stroke-width="1.6"/>',
        f'<line x1="{x-5.5}" y1="{y+11}" x2="{x+5.5}" y2="{y+11}" stroke="currentColor" stroke-width="1.6"/>',
        f'<line x1="{x-2}" y1="{y+15}" x2="{x+2}" y2="{y+15}" stroke="currentColor" stroke-width="1.6"/>']))

def rail(x: float, y: float, label: str, down: bool = False) -> str:
    """Supply flag: short stub with a bar and a label."""
    d = 1 if down else -1
    o: list[str] = [f'<line x1="{x}" y1="{y}" x2="{x}" y2="{y+d*9}" stroke="currentColor" stroke-width="1.4"/>',
         f'<line x1="{x-10}" y1="{y+d*9}" x2="{x+10}" y2="{y+d*9}" stroke="currentColor" stroke-width="1.8"/>',
         _t(x, y + d*9 + (14 if down else -6), label, "middle", "rail")]
    return "".join(o)

def arrowdefs() -> str:
    return ('<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
            'markerHeight="6" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker>'
            '<marker id="ara" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
            'markerHeight="6" orient="auto-start-reverse">'
            '<path d="M 0 0 L 10 5 L 0 10 z" fill="var(--accent)"/></marker></defs>')

def arrow(x1: float, y1: float, x2: float, y2: float, accent: bool = False) -> str:
    st = "var(--accent)" if accent else "currentColor"
    m = "ara" if accent else "ar"
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{st}" '
            f'stroke-width="1.4" marker-end="url(#{m})"/>')

def svg(w: float, h: float, body: str, label: str) -> str:
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" role="img" aria-label="{label}">'
            + arrowdefs() + body + '</svg>')
