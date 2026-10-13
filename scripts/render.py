#!/usr/bin/env python3
"""Render the SVG assets used by the profile README.

Standard library only, so the scheduled workflow needs no installs.

    python scripts/render.py                    # live star/fork counts (GITHUB_TOKEN or GH_TOKEN)
    python scripts/render.py --data repos.json  # replay a saved GraphQL `data` payload
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

LOGIN = "NiceDayZc"
OUT = Path(__file__).resolve().parents[1] / "assets"

MONO = ("'Cascadia Code','JetBrains Mono','SF Mono',ui-monospace,Menlo,Consolas,"
        "'Liberation Mono','DejaVu Sans Mono',monospace")
# Advance of one monospace cell, in em. Every run is pinned with textLength, so
# viewers whose fallback font is narrower or wider still land on the same grid.
EM = 0.6


@dataclass(frozen=True)
class Theme:
    name: str
    paper: str  # card and tape background
    edge: str   # borders and hairlines
    ink: str    # primary text
    soft: str   # secondary text
    faint: str  # prompts and separators


DARK = Theme("dark", "#0a0a0a", "#2e2e2e", "#fafafa", "#a3a3a3", "#737373")
LIGHT = Theme("light", "#ffffff", "#d9d9d9", "#0a0a0a", "#525252", "#8a8a8a")

FEATURED = [
    ("OkLine", "Unofficial LINE SDK for Python: QR login, E2EE Letter Sealing, bot framework and CLI.",
     "$ pip install okline"),
    ("okgram", "Instagram private API client that talks like the real Android app: HTTP/2 + JA3/JA4 TLS.",
     "http/2 · ja3 · ja4"),
    ("openjbl", "Open toolkit for the JBL Portable Bluetooth protocol, with EQ over CLI, TUI and GUI.",
     "ble · textual · vite"),
    ("FacebookCodec", "Reverse-engineered Facebook BitMap codec that builds valid __dyn and __csr params.",
     "rle · custom base64"),
]
FOCUS = ["REVERSE ENGINEERING", "PRIVATE APIS", "PROTOCOL ANALYSIS", "TLS FINGERPRINTING",
         "E2EE", "BLUETOOTH LE", "PYTHON SDKS"]
STACK = ["PYTHON", "TYPESCRIPT", "JAVASCRIPT", "REACT", "NEXT.JS", "TAILWIND", "VITE",
         "SUPABASE", "POSTGRES", "TEXTUAL", "GIT"]

# figlet "ANSI Shadow"
FIGLET = {
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "I": ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
    "C": [" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "D": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "Y": ["██╗   ██╗", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚██╔╝  ", "   ██║   ", "   ╚═╝   "],
    "Z": ["███████╗", "╚══███╔╝", "  ███╔╝ ", " ███╔╝  ", "███████╗", "╚══════╝"],
}


# ── svg primitives ──────────────────────────────────────────────────────────

def num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def svg(w: int, h: int, body: str, css: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'xml:space="preserve">\n'
        f"<style>text{{font-family:{MONO};white-space:pre}}{css}"
        "@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>\n"
        f"{body}\n</svg>\n"
    )


def text(x: float, y: float, s: str, size: float, fill: str, *,
         weight: int | None = None, anchor: str | None = None, extra: str = "") -> str:
    attrs = f'x="{num(x)}" y="{num(y)}" font-size="{num(size)}" fill="{fill}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    if len(s) > 1:
        attrs += f' textLength="{num(len(s) * EM * size)}" lengthAdjust="spacing"'
    return f"<text {attrs}{extra}>{escape(s)}</text>"


def runs(x: float, y: float, size: float, parts: list[tuple], **kw) -> str:
    """Lay out [(text, colour[, weight]), ...] left to right on the monospace grid."""
    out, col = [], 0
    for s, fill, *weight in parts:
        core = s.strip()
        if core:
            lead = len(s) - len(s.lstrip())
            out.append(text(x + (col + lead) * EM * size, y, core, size, fill,
                            weight=weight[0] if weight else None, **kw))
        col += len(s)
    return "".join(out)


def chevron(x: float, y: float, size: float, color: str, extra: str = "") -> str:
    """The ❯ prompt, drawn as a stroke so it does not depend on the viewer's fonts."""
    top, h, w, left = y - size * 0.6, size * 0.5, size * 0.27, x + size * 0.1
    return (f'<path d="M{num(left)} {num(top)}L{num(left + w)} {num(top + h / 2)}L{num(left)} {num(top + h)}" '
            f'stroke="{color}" stroke-width="{num(size * 0.12)}" stroke-linecap="round" '
            f'stroke-linejoin="round" fill="none"{extra}/>')


def star(cx: float, cy: float, r: float, fill: str) -> str:
    pts = []
    for k in range(10):
        rad = r if k % 2 == 0 else r * 0.48
        ang = math.radians(-90 + k * 36)
        pts.append(f"{num(cx + rad * math.cos(ang))},{num(cy + rad * math.sin(ang))}")
    return f'<polygon points="{" ".join(pts)}" fill="{fill}"/>'


def sparkle(cx: float, cy: float, r: float, fill: str) -> str:
    """Four-pointed star used between words on the tapes."""
    return (f'<path d="M{num(cx)} {num(cy - r)}Q{num(cx)} {num(cy)} {num(cx + r)} {num(cy)}'
            f'Q{num(cx)} {num(cy)} {num(cx)} {num(cy + r)}Q{num(cx)} {num(cy)} {num(cx - r)} {num(cy)}'
            f'Q{num(cx)} {num(cy)} {num(cx)} {num(cy - r)}Z" fill="{fill}"/>')


def fork(x: float, y: float, color: str) -> str:
    """Fork glyph in a 14x16 box whose top-left corner is (x, y)."""
    return (f'<g transform="translate({num(x)} {num(y)})" stroke="{color}" stroke-width="1.6" '
            f'fill="none" stroke-linecap="round">'
            '<circle cx="3" cy="3" r="2"/><circle cx="11" cy="3" r="2"/><circle cx="7" cy="13" r="2"/>'
            '<path d="M3 5v1.2a2.5 2.5 0 0 0 2.5 2.5h3a2.5 2.5 0 0 0 2.5-2.5V5M7 8.7V11"/></g>')


def book(x: float, y: float, color: str) -> str:
    """Repository glyph in a 16x18 box whose top-left corner is (x, y)."""
    return (f'<g transform="translate({num(x)} {num(y)})" stroke="{color}" stroke-width="1.7" '
            f'fill="none" stroke-linejoin="round" stroke-linecap="round">'
            '<path d="M2 15.5V3.5A2 2 0 0 1 4 1.5h10v12.5H4a2 2 0 0 0-2 2 2 2 0 0 0 2 2h10"/>'
            '<path d="M6 5.5h5"/></g>')


def fade(gid: str, color: str, peak: float = 1.0) -> str:
    """Horizontal gradient, transparent at both ends and `peak` opaque in the middle."""
    return (f'<linearGradient id="{gid}" x1="0" x2="1"><stop offset="0" stop-color="{color}" stop-opacity="0"/>'
            f'<stop offset=".5" stop-color="{color}" stop-opacity="{peak}"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient>')


# ── animation helpers ───────────────────────────────────────────────────────
# Everything is visible by default and CSS only hides it until its moment, so a
# renderer without animation support (or reduced motion) shows the final frame.

BASE_CSS = (".k{animation:k .01s linear both}@keyframes k{from{opacity:0}to{opacity:1}}"
            ".cb{animation:k .01s linear both,b 1.1s step-end infinite}"
            "@keyframes b{0%{opacity:1}50%{opacity:0}}")


def typed(x: float, y: float, size: float, s: str, t0: float, step: float, fill: str) -> tuple[str, float]:
    a = EM * size
    out = [text(x + i * a, y, ch, size, fill, extra=f' class="k" style="animation-delay:{t0 + (i + 1) * step:.2f}s"')
           for i, ch in enumerate(s) if ch != " "]
    return "".join(out), t0 + len(s) * step


def appear(markup: str, t: float) -> str:
    return f'<g class="k" style="animation-delay:{t:.2f}s">{markup}</g>'


def cursor_rect(x: float, y: float, size: float, fill: str, extra: str) -> str:
    return (f'<rect x="{num(x)}" y="{num(y - size * 0.82)}" width="{num(EM * size)}" '
            f'height="{num(size * 1.04)}" fill="{fill}" fill-opacity=".9"{extra}/>')


def typing_cursor(name: str, x: float, y: float, size: float, fill: str, t_show: float, t0: float,
                  step: float, n: int, t_hide: float) -> tuple[str, str]:
    """Cursor that waits at the prompt, follows `n` typed characters, then vanishes at `t_hide`."""
    a = EM * size
    frames = [(0, 0, 0)] if t_show > 0 else []
    frames.append((t_show, 1, 0))
    frames += [(t0 + (i + 1) * step, 1, (i + 1) * a) for i in range(n)]
    kf = "".join(f"{num(100 * t / t_hide)}%{{opacity:{op};transform:translateX({num(dx)}px)}}"
                 for t, op, dx in frames)
    css = (f"@keyframes {name}{{{kf}100%{{opacity:1;transform:translateX({num(n * a)}px)}}}}"
           f".{name}{{opacity:0;animation:{name} {t_hide:.2f}s step-end}}")
    return cursor_rect(x, y, size, fill, f' class="{name}"'), css


def blinking_cursor(x: float, y: float, size: float, fill: str, t: float) -> str:
    return cursor_rect(x, y, size, fill, f' class="cb" style="animation-delay:{t:.2f}s,{t:.2f}s"')


# ── assets ──────────────────────────────────────────────────────────────────

def window(w: int, h: int, title: str) -> str:
    """Terminal window chrome: rounded body, soft light, title bar."""
    t = DARK
    dots = "".join(f'<circle cx="{cx}" cy="24" r="6" fill="#2b2b2b" stroke="#3d3d3d"/>' for cx in (28, 48, 68))
    return f"""<defs>
<clipPath id="wc"><rect width="{w}" height="{h}" rx="16"/></clipPath>
<linearGradient id="we" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".34"/><stop offset=".5" stop-color="#fff" stop-opacity=".06"/><stop offset="1" stop-color="#fff" stop-opacity=".22"/></linearGradient>
<radialGradient id="wg" cx=".1" cy="0" r=".8"><stop offset="0" stop-color="#fff" stop-opacity=".08"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>
</defs>
<g clip-path="url(#wc)">
<rect width="{w}" height="{h}" fill="{t.paper}"/>
<rect width="{w}" height="{h}" fill="url(#wg)"/>
<rect width="{w}" height="48" fill="#111"/>
<path d="M0 48.5H{w}" stroke="#1f1f1f"/>
</g>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="15.5" fill="none" stroke="url(#we)"/>
{dots}
{text(w / 2, 29, title, 14, t.faint, anchor="middle")}"""


def banner(word: str, x0: float, y0: float, cw: float, ch: float, t0: float,
           row_step: float) -> tuple[str, str, str, float]:
    """ANSI Shadow lettering built from rects and double strokes, printed row by row."""
    rows = ["".join(FIGLET[c][r] for c in word) for r in range(6)]
    assert len({len(r) for r in rows}) == 1, "figlet rows must share a width"
    bw, bh = len(rows[0]) * cw, 6 * ch
    d, cx, cy = cw * 0.2, cw / 2, ch / 2
    seg = {
        "═": [[(0, cy - d), (cw, cy - d)], [(0, cy + d), (cw, cy + d)]],
        "║": [[(cx - d, 0), (cx - d, ch)], [(cx + d, 0), (cx + d, ch)]],
        "╗": [[(0, cy - d), (cx + d, cy - d), (cx + d, ch)], [(0, cy + d), (cx - d, cy + d), (cx - d, ch)]],
        "╔": [[(cw, cy - d), (cx - d, cy - d), (cx - d, ch)], [(cw, cy + d), (cx + d, cy + d), (cx + d, ch)]],
        "╝": [[(0, cy + d), (cx + d, cy + d), (cx + d, 0)], [(0, cy - d), (cx - d, cy - d), (cx - d, 0)]],
        "╚": [[(cw, cy + d), (cx - d, cy + d), (cx - d, 0)], [(cw, cy - d), (cx + d, cy - d), (cx + d, 0)]],
    }
    all_blocks, printed = [], []
    for r, row in enumerate(rows):
        y = y0 + r * ch
        blocks, lines, c = [], [], 0
        while c < len(row):
            if row[c] == "█":
                start = c
                while c < len(row) and row[c] == "█":
                    c += 1
                # a hair of overlap hides anti-aliasing seams between rows
                blocks.append(f"M{num(x0 + start * cw)} {num(y)}h{num((c - start) * cw)}v{num(ch + 0.6)}"
                              f"h{num(-(c - start) * cw)}z")
                continue
            for poly in seg.get(row[c], []):
                ox = x0 + c * cw
                lines.append("M" + "L".join(f"{num(ox + px)} {num(y + py)}" for px, py in poly))
            c += 1
        all_blocks += blocks
        printed.append(appear(
            f'<path d="{"".join(lines)}" stroke="#4a4a4a" stroke-width="{num(cw * 0.11)}" '
            f'stroke-linecap="square" fill="none"/><path d="{"".join(blocks)}" fill="#dcdcdc"/>',
            t0 + r * row_step))

    t_done = t0 + 5 * row_step
    # a slanted band of light that sweeps across the letters every few seconds
    band = (f"M{num(x0 - 260)} {num(y0 + bh)}L{num(x0 - 200)} {num(y0)}H{num(x0 - 60)}"
            f"L{num(x0 - 120)} {num(y0 + bh)}Z")
    defs = (f'<path id="bk" d="{"".join(all_blocks)}"/><clipPath id="bkc"><use href="#bk"/></clipPath>'
            + fade("shine", "#fff"))
    body = ('<use href="#bk" fill="#fff" class="g1"/><use href="#bk" fill="#5c5c5c" class="g2"/>'
            f'<g class="jt">{"".join(printed)}'
            f'<g clip-path="url(#bkc)"><path d="{band}" fill="url(#shine)" class="sh"/></g></g>')
    css = (
        f".sh{{animation:sh 6s cubic-bezier(.45,0,.25,1) {t_done + 0.9:.2f}s infinite}}"
        f"@keyframes sh{{0%{{transform:translateX(0)}}45%,100%{{transform:translateX({num(bw + 360)}px)}}}}"
        ".g1,.g2{opacity:0}.g1{animation:g1 7s step-end 5.5s infinite}.g2{animation:g2 7s step-end 5.5s infinite}"
        ".jt{animation:jt 7s step-end 5.5s infinite}"
        "@keyframes g1{0%{opacity:0}1%{opacity:.55;transform:translate(-6px,1px)}2.2%{opacity:.4;transform:translate(4px,0)}"
        "3.4%{opacity:0;transform:none}}"
        "@keyframes g2{0%{opacity:0}1%{opacity:.8;transform:translate(6px,-1px)}2.2%{opacity:.6;transform:translate(-3px,1px)}"
        "3.4%{opacity:0;transform:none}}"
        "@keyframes jt{0%{transform:none}1%{transform:translate(2px,0)}2.2%{transform:translate(-2px,0)}3.4%{transform:none}}"
    )
    return defs, body, css, t_done


def hero() -> str:
    W, H, X, size = 1200, 470, 48, 21
    t, a, step = DARK, EM * 21, 0.05
    parts, css = [window(W, H, "nicedayzc@rmutt: ~")], [BASE_CSS]

    y1, cmd, t_type = 98, "./decompile nicedayzc", 0.6
    chars, t_typed = typed(X + 2 * a, y1, size, cmd, t_type, step, t.ink)
    t_enter = t_typed + 0.35
    cur, c_css = typing_cursor("c1", X + 2 * a, y1, size, t.ink, 0, t_type, step, len(cmd), t_enter)
    parts += [chevron(X, y1, size, t.faint), chars, cur]
    css.append(c_css)

    defs, art, b_css, t_printed = banner("NICEDAYZC", X, 124, 15.2, 30, t_enter + 0.05, 0.07)
    parts.insert(0, f"<defs>{defs}</defs>")
    parts.append(art)
    css.append(b_css)

    y2, t_prompt2 = 354, t_printed + 0.35
    chars, t_typed = typed(X + 2 * a, y2, size, "whoami", t_prompt2 + 0.35, 0.08, t.ink)
    t_out = t_typed + 0.3
    cur, c_css = typing_cursor("c2", X + 2 * a, y2, size, t.ink, t_prompt2, t_prompt2 + 0.35, 0.08, 6, t_out)
    parts += [appear(chevron(X, y2, size, t.faint), t_prompt2), chars, cur]
    css.append(c_css)

    parts.append(appear(runs(X, y2 + 36, size, [
        ("reverse engineer", t.ink), (" · ", t.faint), ("cyber security", t.ink), (" · ", t.faint),
        ("cs student @ rmutt", t.ink)]), t_out))

    y3, t_last = y2 + 80, t_out + 0.25
    parts += [appear(chevron(X, y3, size, t.faint), t_last), blinking_cursor(X + 2 * a, y3, size, t.ink, t_last)]
    return svg(W, H, "\n".join(parts), "".join(css))


def wrap(s: str, width: int) -> list[str]:
    lines, line = [], ""
    for word in s.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + [line]


def card(name: str, blurb: str, tag: str, repo: dict, delay: float) -> str:
    # Cards stay dark on both GitHub themes: GitHub breaks a <picture> nested in a
    # link, and a card has to link to its repo.
    W, H, P, beam, t = 560, 190, 28, 200, DARK
    parts = [f"""<defs>
<clipPath id="cc"><rect width="{W}" height="{H}" rx="14"/></clipPath>
{fade("cb", t.ink)}
<radialGradient id="cg" cx="1" cy="0" r=".9"><stop offset="0" stop-color="{t.ink}" stop-opacity=".07"/><stop offset="1" stop-color="{t.ink}" stop-opacity="0"/></radialGradient>
</defs>
<g clip-path="url(#cc)"><rect width="{W}" height="{H}" fill="{t.paper}"/><rect width="{W}" height="{H}" fill="url(#cg)"/></g>
<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="13.5" fill="none" stroke="{t.edge}"/>
<g clip-path="url(#cc)"><rect x="{-beam}" width="{beam}" height="2" fill="url(#cb)" class="bm"/></g>"""]
    css = (f".bm{{animation:bm 7s cubic-bezier(.5,0,.5,1) {delay:.2f}s infinite}}"
           f"@keyframes bm{{0%{{transform:translateX(0)}}60%,100%{{transform:translateX({W + beam}px)}}}}")

    parts += [book(P, 30, t.soft), text(P + 30, 46, name, 22, t.ink, weight=700)]

    # stars and forks, laid out from the right edge
    fsz, right = 16, W - P
    forks, stars = str(repo["forkCount"]), str(repo["stargazerCount"])
    parts.append(text(right, 46, forks, fsz, t.soft, anchor="end"))
    fx = right - len(forks) * EM * fsz - 20
    parts.append(fork(fx, 33, t.soft))
    sx = fx - 18
    parts.append(text(sx, 46, stars, fsz, t.soft, anchor="end"))
    parts.append(star(sx - len(stars) * EM * fsz - 12, 40.5, 8, t.ink))

    lines = wrap(blurb, int((W - 2 * P) / (EM * 16.5)))
    assert len(lines) <= 2, f"{name}: blurb wraps to {len(lines)} lines"
    for i, line in enumerate(lines):
        parts.append(text(P, 92 + i * 26, line, 16.5, t.soft))

    lang = (repo.get("primaryLanguage") or {}).get("name", "—")
    parts.append(f'<circle cx="{P + 6}" cy="{H - 35}" r="5" fill="none" stroke="{t.soft}" stroke-width="2"/>')
    parts.append(text(P + 20, H - 30, lang, 15, t.soft))
    if tag.startswith("$ "):
        a = EM * 15
        x = right - (len(tag) + 1) * a
        parts.append(runs(x, H - 30, 15, [("$", t.faint), (tag[1:], t.ink)]))
        parts.append(blinking_cursor(x + len(tag) * a + 2, H - 30, 15, t.ink, 0))
        css += BASE_CSS
    else:
        parts.append(text(right, H - 30, tag, 15, t.soft, anchor="end"))
    return svg(W, H, "\n".join(parts), css)


def tapes(t: Theme) -> str:
    """Two marquee tapes crossing each other, scrolling in opposite directions."""
    W, H, size, band = 1200, 250, 24, 54
    a, gap = EM * 24, EM * 24 * 1.4
    cx, cy = W / 2, H / 2
    parts, css = [], []
    specs = [  # words, angle, tape colour, text colour, border, direction
        (STACK, 7, t.paper, t.ink, t.edge, 1),
        (FOCUS, -7, t.ink, t.paper, None, -1),
    ]
    for i, (words, angle, bg, fg, border, direction) in enumerate(specs):
        unit, x = [], 0.0
        for word in words:
            unit.append(text(x, cy + size * 0.36, word, size, fg, weight=700))
            x += len(word) * a + gap
            unit.append(sparkle(x, cy, size * 0.3, fg))
            x += gap
        period = x
        copies = math.ceil((1700 + period) / period)
        track = "".join(f'<g transform="translate({num(-250 + k * period)} 0)">{"".join(unit)}</g>'
                        for k in range(copies))
        stroke = f' stroke="{border}" stroke-width="1.5"' if border else ""
        start, end = (-period, 0) if direction > 0 else (0, -period)
        css.append(f".t{i}{{animation:t{i} {period / 38:.1f}s linear infinite}}"
                   f"@keyframes t{i}{{from{{transform:translateX({num(start)}px)}}"
                   f"to{{transform:translateX({num(end)}px)}}}}")
        parts.append(f'<g transform="rotate({angle} {cx} {cy})">'
                     f'<rect x="-250" y="{num(cy - band / 2)}" width="1700" height="{band}" fill="{bg}"{stroke}/>'
                     f'<g class="t{i}">{track}</g></g>')
    return svg(W, H, "\n".join(parts), "".join(css))


def heading(t: Theme, path: str) -> str:
    W, H, size = 1200, 60, 22
    a = EM * size
    end = 4 + (4 + len(path)) * a  # chevron, space, "~/", path
    return svg(W, H, "\n".join([
        f'<defs><linearGradient id="hl" x1="0" x2="1"><stop offset="0" stop-color="{t.ink}" stop-opacity=".35"/>'
        f'<stop offset="1" stop-color="{t.ink}" stop-opacity="0"/></linearGradient></defs>',
        chevron(4, 38, size, t.faint),
        runs(4 + 2 * a, 38, size, [("~/", t.faint), (path, t.ink, 700)]),
        f'<rect x="{num(end + 18)}" y="30" width="{num(W - end - 18)}" height="1.5" fill="url(#hl)"/>',
    ]))


def footer(t: Theme) -> str:
    W, H = 1200, 70
    return svg(W, H, "\n".join([
        f"<defs>{fade('fl', t.ink, 0.45)}</defs>",
        f'<rect width="{W}" height="1.5" fill="url(#fl)"/>',
        text(W / 2, 46, "[process exited with code 0]", 16, t.faint, anchor="middle"),
    ]))


# ── data + main ─────────────────────────────────────────────────────────────

def query() -> str:
    fields = "stargazerCount forkCount primaryLanguage { name }"
    repos = "\n".join(f'  r{i}: repository(owner: "{LOGIN}", name: "{name}") {{ {fields} }}'
                      for i, (name, _, _) in enumerate(FEATURED))
    return "query {\n" + repos + "\n}"


def fetch(token: str) -> dict:
    body = json.dumps({"query": query()}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body, headers={
        "Authorization": f"bearer {token}", "User-Agent": f"{LOGIN}-profile-readme"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            if payload.get("errors"):
                raise RuntimeError(payload["errors"])
            return payload["data"]
        except (OSError, RuntimeError):
            if attempt == 3:
                raise
            time.sleep(3 * 2 ** attempt)
    raise AssertionError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, help="render from a saved GraphQL `data` payload")
    args = ap.parse_args()

    if args.data:
        data = json.loads(args.data.read_text("utf-8"))
    else:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if not token:
            sys.exit("render.py: set GITHUB_TOKEN or GH_TOKEN (or pass --data)")
        data = fetch(token)

    assets = {"hero.svg": hero()}
    for i, (name, blurb, tag) in enumerate(FEATURED):
        assets[f"card-{name.lower()}.svg"] = card(name, blurb, tag, data[f"r{i}"], delay=i * 1.6)
    # transparent assets get a variant per GitHub theme, picked with <picture>
    for t in (DARK, LIGHT):
        assets[f"h-projects-{t.name}.svg"] = heading(t, "projects")
        assets[f"tapes-{t.name}.svg"] = tapes(t)
        assets[f"footer-{t.name}.svg"] = footer(t)

    OUT.mkdir(exist_ok=True)
    for filename, content in assets.items():
        (OUT / filename).write_text(content, encoding="utf-8", newline="\n")
    stars = sum(data[f"r{i}"]["stargazerCount"] for i in range(len(FEATURED)))
    print(f"rendered {len(assets)} assets, {stars} stars across featured repos")


if __name__ == "__main__":
    main()
