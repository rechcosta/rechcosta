"""Generate the animated profile header: a logic-analyzer capture of a UART line.

The waveform is computed, not drawn by hand: each byte of MESSAGE is framed as
UART 8N1 (idle high, 1 start bit low, 8 data bits LSB-first, 1 stop bit high).

Animation is pure CSS inside the SVG, so it runs when GitHub serves the file
through <img>. Two independent loops:
  * capture: a scan head sweeps left to right revealing the trace and the
    decoded bytes, then cursors A/B measure one frame, then the capture clears;
  * typing:  the subtitle cycles through TYPED_LINES, one character per step.

Reveals use opaque "curtains" painted in the panel colour instead of animated
clip paths, because CSS animation inside <clipPath> is not repainted reliably
by every browser. With prefers-reduced-motion the final frame is shown static.

Text is converted to outlines because an SVG loaded through <img> cannot fetch
web fonts.

Usage:
    python gen_header.py --fonts /path/to/ibm-plex-ttf --out ../assets
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

MESSAGE = "rechcosta"
BAUD = 115_200
BIT_US = 1e6 / BAUD          # 8.68 µs per bit
IDLE_BITS = 2                # idle-high bits before and after the burst

TYPED_LINES = (
    "digital hardware on FPGAs",
    "writing C, Assembly and VHDL",
    "computer vision applied to astronomy @ LUNA",
    "from registers to full-stack apps",
)

W, H = 1200, 384
X0, X1 = 92, 1168            # waveform horizontal extent
HIGH_Y, LOW_Y = 282, 318     # logic levels
ANN_Y, ANN_H = 234, 28       # decoder annotation lane

# Capture loop timing (seconds)
CAP_PERIOD = 10.0
SWEEP_START, SWEEP_END = 0.4, 6.4
CURSORS_IN = 6.7
CLEAR_START = 9.4

# Typing loop timing (seconds per line)
LINE_PERIOD = 3.2
TYPE_TIME = 1.4              # time to type the longest line is scaled per line
TYPED_X, TYPED_Y, TYPED_SIZE = 42, 188, 17


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    border: str
    grid: str
    text: str
    muted: str
    signal: str
    accent: str
    ann_fill: str
    ann_stroke: str
    cursor: str


DARK = Theme("dark", "#0D1117", "#30363D", "#21262D", "#E6EDF3", "#7D8590",
             "#3FB950", "#58A6FF", "#0F2A3F", "#1F6FEB", "#D29922")
LIGHT = Theme("light", "#FFFFFF", "#D0D7DE", "#EAEEF2", "#1F2328", "#59636E",
              "#1A7F37", "#0969DA", "#DDF4FF", "#54AEFF", "#9A6700")


def _fmt(v: float) -> str:
    """One decimal is a tenth of a pixel; keeps the SVG small."""
    return f"{v:.1f}".rstrip("0").rstrip(".")


def pct(t: float, period: float) -> str:
    return f"{100 * t / period:.3f}%"


class Outliner:
    """Converts a string into an SVG path using a font's glyph outlines."""

    def __init__(self, path: Path):
        self.font = TTFont(path)
        self.glyphs = self.font.getGlyphSet()
        self.cmap = self.font.getBestCmap()
        self.upem = self.font["head"].unitsPerEm
        self.hmtx = self.font["hmtx"]

    def advance(self, ch: str, size: float) -> float:
        return self.hmtx[self.cmap[ord(ch)]][0] * size / self.upem

    def width(self, text: str, size: float, tracking: float = 0.0) -> float:
        return sum(self.advance(c, size) for c in text) + tracking * max(len(text) - 1, 0)

    def path(self, text: str, x: float, y: float, size: float,
             anchor: str = "start", tracking: float = 0.0) -> str:
        if anchor != "start":
            w = self.width(text, size, tracking)
            x -= w if anchor == "end" else w / 2
        scale = size / self.upem
        pen = SVGPathPen(self.glyphs, ntos=_fmt)
        for ch in text:
            gname = self.cmap[ord(ch)]
            # Font units are y-up; SVG is y-down, hence the negative y scale.
            self.glyphs[gname].draw(TransformPen(pen, (scale, 0, 0, -scale, x, y)))
            x += self.hmtx[gname][0] * scale + tracking
        return pen.getCommands()


def uart_bits(message: str) -> list[int]:
    bits = [1] * IDLE_BITS
    for byte in message.encode("ascii"):
        bits.append(0)                                   # start
        bits.extend((byte >> i) & 1 for i in range(8))   # data, LSB first
        bits.append(1)                                   # stop
    bits.extend([1] * IDLE_BITS)
    return bits


def capture_css(sweep_dist: float) -> str:
    P = CAP_PERIOD
    return f"""
@keyframes sweep {{
  0%, {pct(SWEEP_START, P)} {{ transform: translateX(0); }}
  {pct(SWEEP_END, P)}, 100% {{ transform: translateX({sweep_dist:.1f}px); }}
}}
@keyframes cursors {{
  0%, {pct(CURSORS_IN, P)} {{ opacity: 0; }}
  {pct(CURSORS_IN + 0.4, P)}, {pct(CLEAR_START, P)} {{ opacity: 1; }}
  {pct(CLEAR_START + 0.4, P)}, 100% {{ opacity: 0; }}
}}
@keyframes clear {{
  0%, {pct(CLEAR_START, P)} {{ opacity: 1; }}
  {pct(CLEAR_START + 0.4, P)}, 100% {{ opacity: 0; }}
}}
.sweep   {{ animation: sweep   {P}s linear infinite; }}
.cursors {{ animation: cursors {P}s linear infinite; }}
.capture {{ animation: clear   {P}s linear infinite; }}
"""


def typing_css(mono: Outliner) -> str:
    n = len(TYPED_LINES)
    period = n * LINE_PERIOD
    longest = max(len(s) for s in TYPED_LINES)
    css = []
    for i, line in enumerate(TYPED_LINES):
        chars = len(line)
        dist = mono.width(line, TYPED_SIZE)   # cursor ends right after the text
        t_type = TYPE_TIME * chars / longest
        start, end = i * LINE_PERIOD, (i + 1) * LINE_PERIOD
        # Visibility window of this line inside the full cycle.
        before = f"0%, {pct(start, period)}" if i else None
        css.append(f"@keyframes show{i} {{")
        if before:
            css.append(f"  {before} {{ opacity: 0; }}")
        css.append(f"  {pct(start + 0.001, period) if i else '0%'}, "
                   f"{pct(end - 0.001, period)} {{ opacity: 1; }}")
        css.append(f"  {pct(end, period)}, 100% {{ opacity: 0; }}")
        css.append("}")
        css.append(f"@keyframes type{i} {{")
        css.append(f"  0%, {pct(start + 0.15, period)} {{ transform: translateX(0); "
                   f"animation-timing-function: steps({chars}, end); }}")
        css.append(f"  {pct(start + 0.15 + t_type, period)}, 100% "
                   f"{{ transform: translateX({dist:.2f}px); }}")
        css.append("}")
        css.append(f".show{i} {{ animation: show{i} {period}s linear infinite; }}")
        css.append(f".type{i} {{ animation: type{i} {period}s linear infinite; }}")
    css.append("@keyframes blink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }")
    css.append(".blink { animation: blink 1s steps(1, end) infinite; }")
    return "\n".join(css)


def build(theme: Theme, mono: Outliner, mono_md: Outliner, sans: Outliner) -> str:
    bits = uart_bits(MESSAGE)
    bw = (X1 - X0) / len(bits)
    level = {1: HIGH_Y, 0: LOW_Y}
    lane_top, lane_bot = ANN_Y - 4, LOW_Y + 6
    sweep_dist = (X1 - X0) + 8
    out: list[str] = []
    add = out.append

    def text(o: Outliner, s: str, x, y, size, fill, anchor="start", tr=0.0, cls=""):
        c = f' class="{cls}"' if cls else ""
        add(f'<path{c} fill="{fill}" d="{o.path(s, x, y, size, anchor, tr)}"/>')

    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img">')
    add("<style>")
    add(capture_css(sweep_dist))
    add(typing_css(mono))
    add("""@media (prefers-reduced-motion: reduce) {
  .sweep, .cursors, .capture, .blink { animation: none; }
  .curtain, .typed-extra, .blink { display: none; }
  [class^="show"], [class^="type"] { animation: none; }
}""")
    add("</style>")
    add(f'<defs><clipPath id="lane"><rect x="{X0-2}" y="{lane_top-2}" '
        f'width="{X1-X0+4}" height="{lane_bot-lane_top+4}"/></clipPath></defs>')
    add(f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="10" '
        f'fill="{theme.bg}" stroke="{theme.border}"/>')

    # Title block (static)
    text(mono, "CH0  UART TX  ·  115200 BAUD  ·  8N1", 40, 44, 14, theme.muted, tr=0.6)
    text(mono, "REV 2026.2", W - 40, 44, 14, theme.muted, "end", 0.6)
    add(f'<line x1="40" y1="60" x2="{W-40}" y2="60" stroke="{theme.border}"/>')
    text(sans, "Gustavo Rech Costa", 40, 124, 50, theme.text)
    text(mono, "Computer Engineering @ UFSC", 42, 160, 18, theme.accent, tr=0.2)

    # Typed subtitle: prompt + one line at a time, revealed by a stepping curtain
    prompt = "> "
    text(mono, prompt, TYPED_X, TYPED_Y, TYPED_SIZE, theme.accent)
    lx = TYPED_X + mono.width(prompt, TYPED_SIZE)
    adv = mono.advance(" ", TYPED_SIZE)
    for i, line in enumerate(TYPED_LINES):
        extra = " typed-extra" if i else ""
        add(f'<g class="show{i}{extra}">')
        text(mono, line, lx, TYPED_Y, TYPED_SIZE, theme.muted)
        lw = mono.width(line, TYPED_SIZE) + adv * 2
        add(f'<g class="type{i}">')
        add(f'<rect class="curtain" x="{lx:.1f}" y="{TYPED_Y-17}" width="{lw:.1f}" '
            f'height="24" fill="{theme.bg}"/>')
        add(f'<rect class="blink" x="{lx:.1f}" y="{TYPED_Y-14}" width="{adv*0.9:.1f}" '
            f'height="18" fill="{theme.accent}"/>')
        add("</g></g>")

    # Capture lane: trace + decoded bytes, revealed by the sweeping curtain
    add(f'<g clip-path="url(#lane)">')
    add('<g class="capture">')
    for k, ch in enumerate(MESSAGE):
        start = IDLE_BITS + k * 10
        xs, xe = X0 + (start + 1) * bw, X0 + (start + 9) * bw
        notch = 6
        add(f'<path d="M{xs+notch:.2f},{ANN_Y} H{xe-notch:.2f} L{xe:.2f},{ANN_Y+ANN_H/2} '
            f'L{xe-notch:.2f},{ANN_Y+ANN_H} H{xs+notch:.2f} L{xs:.2f},{ANN_Y+ANN_H/2} Z" '
            f'fill="{theme.ann_fill}" stroke="{theme.ann_stroke}" stroke-width="1"/>')
        text(mono, f"'{ch}' 0x{ord(ch):02X}", (xs + xe) / 2, ANN_Y + 19, 13.5,
             theme.text, "middle")
        for b, mark in ((start, "S"), (start + 9, "P")):
            text(mono, mark, X0 + (b + 0.5) * bw, ANN_Y + 19, 10.5, theme.muted, "middle")
    pts = [f"{X0:.2f},{level[bits[0]]}"]
    for i in range(1, len(bits)):
        if bits[i] != bits[i - 1]:
            x = X0 + i * bw
            pts += [f"{x:.2f},{level[bits[i-1]]}", f"{x:.2f},{level[bits[i]]}"]
    pts.append(f"{X1:.2f},{level[bits[-1]]}")
    add(f'<polyline points="{" ".join(pts)}" fill="none" stroke="{theme.signal}" '
        f'stroke-width="2.2" stroke-linejoin="miter"/>')
    add("</g>")
    add('<g class="sweep curtain">')
    add(f'<rect x="{X0}" y="{lane_top}" width="{sweep_dist+4}" '
        f'height="{lane_bot-lane_top}" fill="{theme.bg}"/>')
    add(f'<line x1="{X0}" y1="{lane_top}" x2="{X0}" y2="{lane_bot}" '
        f'stroke="{theme.accent}" stroke-width="2"/>')
    add("</g></g>")

    # Graticule drawn over the curtain so it stays visible while the lane is empty
    for i in range(len(bits) + 1):
        x = X0 + i * bw
        add(f'<line x1="{x:.2f}" y1="{HIGH_Y-6}" x2="{x:.2f}" y2="{LOW_Y+6}" '
            f'stroke="{theme.grid}" stroke-width="1" opacity="0.7"/>')
    text(mono_md, "TX", 40, (HIGH_Y + LOW_Y) / 2 + 5, 15, theme.text)

    # Cursors A/B bracketing exactly one frame (start bit → end of stop bit)
    ca, cb = X0 + IDLE_BITS * bw, X0 + (IDLE_BITS + 10) * bw
    add('<g class="cursors">')
    for x, name in ((ca, "A"), (cb, "B")):
        add(f'<line x1="{x:.2f}" y1="{ANN_Y-14}" x2="{x:.2f}" y2="{LOW_Y+14}" '
            f'stroke="{theme.cursor}" stroke-width="1.2" stroke-dasharray="4 3"/>')
        text(mono_md, name, x, ANN_Y - 18, 11, theme.cursor, "middle")
    text(mono, f"∆t(A,B) = {10 * BIT_US:.1f} µs  ·  1 frame", W - 40, ANN_Y - 18,
         13.5, theme.cursor, "end")
    add("</g>")

    # Time ruler
    total_us = len(bits) * BIT_US
    ry = LOW_Y + 26
    add(f'<line x1="{X0}" y1="{ry}" x2="{X1}" y2="{ry}" stroke="{theme.border}"/>')
    t = 0
    while t <= total_us:
        x = X0 + (t / BIT_US) * bw
        add(f'<line x1="{x:.2f}" y1="{ry}" x2="{x:.2f}" y2="{ry+5}" stroke="{theme.muted}"/>')
        text(mono, f"{t} µs", x, ry + 20, 11.5, theme.muted, "middle")
        t += 100

    add("</svg>")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    mono = Outliner(args.fonts / "IBMPlexMono-Regular.ttf")
    mono_md = Outliner(args.fonts / "IBMPlexMono-SemiBold.ttf")
    sans = Outliner(args.fonts / "IBMPlexSans-SemiBold.ttf")

    args.out.mkdir(parents=True, exist_ok=True)
    for theme in (DARK, LIGHT):
        (args.out / f"header-{theme.name}.svg").write_text(
            build(theme, mono, mono_md, sans), encoding="utf-8")


if __name__ == "__main__":
    main()
