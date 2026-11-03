#!/usr/bin/env python3
"""Render the README demo GIF and the social/og image.

Needs ``rsvg-convert`` (librsvg) and ``magick`` (ImageMagick) on PATH; nothing from PyPI.
The terminal text below is real ``pii-airlock`` 0.7.0 output, pasted in, not invented.
Run the CLI from this repo (an older pipx install prints ``<PERSON_1>``-style tokens).

    python3 scripts/make_visuals.py            # writes docs/public/demo.gif and og.png
"""

from __future__ import annotations

import subprocess
import tempfile
from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs" / "public"

BG, FG, DIM = "#0f172a", "#e2e8f0", "#64748b"
BLUE, GREEN, AMBER, PINK = "#60a5fa", "#4ade80", "#fbbf24", "#f472b6"
MONO = "Menlo, 'DejaVu Sans Mono', monospace"
SANS = "'Helvetica Neue', Helvetica, Arial, sans-serif"

Seg = tuple[str, str]  # (text, colour)
Line = list[Seg]


def run(*cmd: str) -> None:
    subprocess.run(cmd, check=True)


# --------------------------------------------------------------------------- terminal GIF

W, H, FS, LH, PAD_X, PAD_Y = 920, 400, 15, 24, 28, 78


def prompt(cmd: str) -> Line:
    return [("$ ", GREEN), (cmd, FG)]


# (line, typed?) - typed lines animate char by char, the others appear at once.
SCRIPT: list[tuple[Line, bool, int]] = [  # (line, typed, pause_ms_after)
    ([("# 1. a prompt with real personal data", DIM)], False, 500),
    (prompt("cat prompt.txt"), True, 250),
    ([("Draft a reply to ", FG), ("Sarah Miller", PINK), (" (", FG),
      ("sarah.miller@acme.com", PINK), (") about invoice 4471.", FG)], False, 900),
    ([], False, 0),
    ([("# 2. scrub it locally: the AI never sees the real values", DIM)], False, 500),
    (prompt("pii-airlock scrub prompt.txt -o safe.txt --map prompt.pii-map.json"), True, 350),
    ([("Wrote safe.txt", DIM)], False, 0),
    ([("Mapping (2 entries) saved to prompt.pii-map.json", DIM)], False, 500),
    (prompt("cat safe.txt"), True, 250),
    ([("Draft a reply to ", FG), ("<PERSON_311093>", BLUE), (" (", FG),
      ("<EMAIL_ADDRESS_706274>", BLUE), (") about invoice 4471.", FG)], False, 1500),
    ([], False, 0),
    ([("# 3. the answer comes back with tokens; restore the originals", DIM)], False, 500),
    (prompt("pii-airlock restore reply.txt --map prompt.pii-map.json"), True, 350),
    ([("Hi ", FG), ("Sarah Miller", GREEN), (", I will send invoice 4471 to ", FG),
      ("sarah.miller@acme.com", GREEN), (" today.", FG)], False, 2600),
]


def terminal_svg(lines: list[Line], cursor: tuple[int, int] | None) -> str:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
        f'<rect width="{W}" height="{H}" rx="14" fill="{BG}"/>',
        f'<rect y="0" width="{W}" height="44" rx="14" fill="#1e293b"/>',
        f'<rect y="30" width="{W}" height="14" fill="#1e293b"/>',
        '<circle cx="26" cy="22" r="6.5" fill="#f87171"/>',
        '<circle cx="48" cy="22" r="6.5" fill="#fbbf24"/>',
        '<circle cx="70" cy="22" r="6.5" fill="#4ade80"/>',
        f'<text x="{W // 2}" y="27" text-anchor="middle" font-family="{SANS}" font-size="13" '
        f'fill="{DIM}">pii-airlock</text>',
    ]
    for i, line in enumerate(lines):
        y = PAD_Y + i * LH
        spans = "".join(f'<tspan fill="{c}">{escape(t)}</tspan>' for t, c in line)
        out.append(
            f'<text x="{PAD_X}" y="{y}" font-family="{MONO}" font-size="{FS}" '
            f'xml:space="preserve">{spans}</text>'
        )
    if cursor:
        row, col = cursor
        cx = PAD_X + col * FS * 0.602
        out.append(
            f'<rect x="{cx:.1f}" y="{PAD_Y + row * LH - FS + 2}" width="{FS * 0.6:.1f}" '
            f'height="{FS + 2}" fill="{FG}" opacity="0.85"/>'
        )
    out.append("</svg>")
    return "\n".join(out)


def clip(line: Line, n: int) -> Line:
    """First n characters of a coloured line."""
    res: Line = []
    for text, colour in line:
        if n <= 0:
            break
        res.append((text[:n], colour))
        n -= len(text)
    return res


def build_frames() -> list[tuple[str, int]]:
    frames: list[tuple[str, int]] = []
    shown: list[Line] = []
    for line, typed, pause in SCRIPT:
        row = len(shown)
        if typed:
            total = sum(len(t) for t, _ in line)
            step = 3
            for n in range(2, total + step, step):
                n = min(n, total)
                frames.append((terminal_svg(shown + [clip(line, n)], (row, n)), 55))
            shown.append(line)
            frames.append((terminal_svg(shown, (row + 1, 0)), 120))
        else:
            shown.append(line)
            frames.append((terminal_svg(shown, (len(shown), 0)), max(pause, 40)))
            continue
        if pause:
            frames[-1] = (frames[-1][0], pause)
    return frames


def make_gif(path: Path) -> None:
    frames = build_frames()
    with tempfile.TemporaryDirectory() as tmp:
        args: list[str] = []
        for i, (svg, ms) in enumerate(frames):
            svg_path, png = Path(tmp) / f"f{i:03}.svg", Path(tmp) / f"f{i:03}.png"
            svg_path.write_text(svg, encoding="utf-8")
            run("rsvg-convert", "-o", str(png), str(svg_path))
            args += ["-delay", str(max(ms // 10, 2)), str(png)]
        run("magick", *args, "-loop", "0", "-layers", "OptimizePlus", "-colors", "48", str(path))
    print(f"{path.name}: {len(frames)} frames, {path.stat().st_size // 1024} KiB")


# --------------------------------------------------------------------------- social image

def og_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640">
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#0b1220"/><stop offset="1" stop-color="#1e3a8a"/>
  </linearGradient>
</defs>
<rect width="1280" height="640" fill="url(#bg)"/>
<g transform="translate(84 44) scale(2)">
  <rect x="6" y="6" width="52" height="52" rx="14" fill="#3b82f6"/>
  <path d="M32 14 16 21v10c0 10 7 16 16 19 9-3 16-9 16-19V21z" fill="#fff"/>
  <path d="m25 32 5 5 10-11" stroke="#3b82f6" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
</g>
<text x="96" y="318" font-family="{SANS}" font-size="104" font-weight="700" fill="#fff">pii-airlock</text>
<text x="96" y="388" font-family="{SANS}" font-size="38" fill="#cbd5e1">Keep real personal data out of your AI prompts.</text>
<text x="96" y="436" font-family="{SANS}" font-size="30" fill="#93c5fd">Local. Reversible. No cloud.</text>
<rect x="96" y="484" width="1088" height="84" rx="14" fill="#0f172a" opacity="0.85"/>
<text x="124" y="535" font-family="{MONO}" font-size="22" xml:space="preserve"><tspan fill="#f472b6">Sarah Miller</tspan><tspan fill="#94a3b8"> (</tspan><tspan fill="#f472b6">sarah@acme.com</tspan><tspan fill="#94a3b8">)  &#8594;  </tspan><tspan fill="#60a5fa">&lt;PERSON_311093&gt;</tspan><tspan fill="#94a3b8"> (</tspan><tspan fill="#60a5fa">&lt;EMAIL_ADDRESS_706274&gt;</tspan><tspan fill="#94a3b8">)</tspan></text>
<text x="1184" y="112" text-anchor="end" font-family="{SANS}" font-size="26" fill="#93c5fd">Claude Code &#183; Codex &#183; Cursor &#183; Copilot</text>
</svg>"""


def make_og(path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        svg = Path(tmp) / "og.svg"
        svg.write_text(og_svg(), encoding="utf-8")
        run("rsvg-convert", "-o", str(path), str(svg))
        run("magick", str(path), "-strip", "-colors", "128", str(path))
    print(f"{path.name}: {path.stat().st_size // 1024} KiB")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    make_gif(OUT / "demo.gif")
    make_og(OUT / "og.png")
