#!/usr/bin/env python3
"""KAIROVEL - a travel poster for a place that isn't there.

Draws a 1024x1024 travel poster of KAIROVEL, a floating-island
archipelago in the sky at golden hour, using only the Python 3
standard library. Deterministic: fixed seed, no time, no network,
no files read. Writes entry.png into MAKEFUN_OUTPUT_DIR (or ./out).
"""

import math
import os
import random
import struct
import zlib

W = 1024
H = 1024
HORIZON = 635  # y of the horizon / top of the sea of clouds

rng = random.Random(20261121)


# ---------------------------------------------------------------- buffer

def new_canvas():
    return bytearray(W * H * 3)


def set_px(buf, x, y, r, g, b):
    if 0 <= x < W and 0 <= y < H:
        i = (y * W + x) * 3
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b


def blend_px(buf, x, y, r, g, b, a):
    """Blend colour (r,g,b) over the pixel at (x,y) with alpha a (0..1)."""
    if a <= 0.0 or not (0 <= x < W and 0 <= y < H):
        return
    i = (y * W + x) * 3
    if a >= 1.0:
        buf[i] = r
        buf[i + 1] = g
        buf[i + 2] = b
        return
    inv = 1.0 - a
    buf[i] = int(buf[i] * inv + r * a + 0.5)
    buf[i + 1] = int(buf[i + 1] * inv + g * a + 0.5)
    buf[i + 2] = int(buf[i + 2] * inv + b * a + 0.5)


def fill_rect(buf, x0, y0, x1, y1, r, g, b, a=1.0):
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(W, x1)
    y1 = min(H, y1)
    if x1 <= x0 or y1 <= y0:
        return
    if a >= 1.0:
        row = bytes((r, g, b)) * (x1 - x0)
        for y in range(y0, y1):
            i = (y * W + x0) * 3
            buf[i:i + len(row)] = row
    else:
        for y in range(y0, y1):
            for x in range(x0, x1):
                blend_px(buf, x, y, r, g, b, a)


def fill_row(buf, y, r, g, b):
    i = (y * W) * 3
    buf[i:i + W * 3] = bytes((r, g, b)) * W


# ---------------------------------------------------------------- helpers

def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return (int(round(lerp(c1[0], c2[0], t))),
            int(round(lerp(c1[1], c2[1], t))),
            int(round(lerp(c1[2], c2[2], t))))


def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def draw_ellipse(buf, cx, cy, rx, ry, color, alpha=1.0, soft=0.0):
    """Filled ellipse; soft>0 fades the alpha near the rim (0..1 of radius)."""
    x0 = max(0, int(cx - rx) - 1)
    x1 = min(W - 1, int(cx + rx) + 1)
    y0 = max(0, int(cy - ry) - 1)
    y1 = min(H - 1, int(cy + ry) + 1)
    r, g, b = color
    for y in range(y0, y1 + 1):
        dy = (y - cy) / ry
        dy2 = dy * dy
        if dy2 > 1.0 and soft <= 0.0:
            continue
        for x in range(x0, x1 + 1):
            dx = (x - cx) / rx
            d2 = dx * dx + dy2
            if d2 > 1.0:
                continue
            if soft > 0.0:
                d = math.sqrt(d2)
                edge = 1.0 - smooth((d - (1.0 - soft)) / soft)
                blend_px(buf, x, y, r, g, b, alpha * edge)
            else:
                blend_px(buf, x, y, r, g, b, alpha)


def fill_polygon(buf, pts, color, alpha=1.0):
    """Scanline fill of a simple polygon (list of (x, y))."""
    if len(pts) < 3:
        return
    ys = [p[1] for p in pts]
    y0 = max(0, int(min(ys)))
    y1 = min(H - 1, int(max(ys)) + 1)
    n = len(pts)
    r, g, b = color
    for y in range(y0, y1 + 1):
        xs = []
        for k in range(n):
            x1, y1p = pts[k]
            x2, y2p = pts[(k + 1) % n]
            if (y1p <= y < y2p) or (y2p <= y < y1p):
                t = (y - y1p) / (y2p - y1p)
                xs.append(x1 + t * (x2 - x1))
        xs.sort()
        for j in range(0, len(xs) - 1, 2):
            xa = max(0, int(math.ceil(xs[j])))
            xb = min(W - 1, int(math.floor(xs[j + 1])))
            for x in range(xa, xb + 1):
                blend_px(buf, x, y, r, g, b, alpha)


def draw_line(buf, x0, y0, x1, y1, color, width=2, alpha=1.0):
    """Simple thick line via stepping along its length."""
    dx = x1 - x0
    dy = y1 - y0
    steps = int(max(abs(dx), abs(dy))) + 1
    r, g, b = color
    half = width // 2
    for s in range(steps + 1):
        t = s / steps
        x = int(round(x0 + dx * t))
        y = int(round(y0 + dy * t))
        for oy in range(-half, half + 1):
            for ox in range(-half, half + 1):
                blend_px(buf, x + ox, y + oy, r, g, b, alpha)


# ---------------------------------------------------------------- sky

SKY_STOPS = [
    (0.00, (24, 14, 62)),    # deep indigo
    (0.30, (62, 32, 104)),   # violet
    (0.48, (138, 54, 124)),  # magenta purple
    (0.58, (214, 96, 92)),   # warm rose
    (0.63, (255, 166, 84)),  # gold at horizon
    (1.00, (255, 196, 128)), # low warm glow
]


def sky_color(t):
    for k in range(len(SKY_STOPS) - 1):
        t0, c0 = SKY_STOPS[k]
        t1, c1 = SKY_STOPS[k + 1]
        if t0 <= t <= t1:
            return mix(c0, c1, (t - t0) / (t1 - t0))
    return SKY_STOPS[-1][1]


def paint_sky(buf):
    for y in range(HORIZON):
        fill_row(buf, y, *sky_color(y / HORIZON))
    # below the horizon: warm cloud-sea base, gold near the horizon
    # deepening to soft lavender at the bottom
    top = (255, 203, 148)
    bottom = (196, 164, 206)
    for y in range(HORIZON, H):
        t = (y - HORIZON) / (H - HORIZON)
        fill_row(buf, y, *mix(top, bottom, t * t))


# ---------------------------------------------------------------- sun

def paint_sun(buf, cx, cy, radius):
    # wide warm glow — stronger and more orange than before so the
    # golden hour reads instead of washing out into the pale sky
    glow_r = radius * 3.8
    gx0 = max(0, int(cx - glow_r))
    gx1 = min(W - 1, int(cx + glow_r))
    gy0 = max(0, int(cy - glow_r))
    gy1 = min(H - 1, int(cy + glow_r))
    for y in range(gy0, gy1 + 1):
        for x in range(gx0, gx1 + 1):
            d = math.hypot(x - cx, y - cy) / glow_r
            if d >= 1.0:
                continue
            a = (1.0 - d) ** 2 * 0.70
            blend_px(buf, x, y, 255, 158, 66, a)
    # disc: deep gold now, not pale cream — warm core, brighter heart
    draw_ellipse(buf, cx, cy, radius, radius, (255, 198, 96), 1.0)
    draw_ellipse(buf, cx, cy, radius * 0.82, radius * 0.82,
                 (255, 216, 138), 1.0)
    # thin bright ring right at the rim for a crisp poster sun
    ring = radius + 3
    for ang in range(0, 360):
        th = math.radians(ang)
        x = int(cx + ring * math.cos(th))
        y = int(cy + ring * math.sin(th))
        blend_px(buf, x, y, 255, 226, 160, 0.7)


# ---------------------------------------------------------------- clouds

CREAM = (255, 241, 222)
CREAM_SHADOW = (232, 204, 214)
LAVENDER = (206, 178, 214)
GOLD_LIT = (255, 214, 158)
# deeper tones for the new shadow layer of the cloud sea
CLOUD_DEEP = (178, 148, 198)   # deep lavender shadow
CLOUD_ROSE = (228, 176, 182)   # warm rose shadow
GOLD_DEEP = (244, 186, 122)    # deep gold lit by the low sun


def cloud_puff(buf, cx, cy, rx, ry, lit):
    """One soft cloud puff: bright lit top, shadowed underside."""
    draw_ellipse(buf, cx, cy, rx, ry,
                 GOLD_LIT if lit else CREAM, 0.95, soft=0.35)
    draw_ellipse(buf, cx, cy + ry * 0.45, rx * 0.92, ry * 0.55,
                 LAVENDER if lit else CREAM_SHADOW, 0.55, soft=0.45)


def cloud_puff_toned(buf, cx, cy, rx, ry, top, shadow,
                     top_a=0.9, shadow_a=0.6):
    """A cloud puff in explicit tones, for the deeper shadow layer."""
    draw_ellipse(buf, cx, cy, rx, ry, top, top_a, soft=0.35)
    draw_ellipse(buf, cx, cy + ry * 0.45, rx * 0.92, ry * 0.55,
                 shadow, shadow_a, soft=0.45)


def paint_cloud_sea(buf):
    # back layer: broad low puffs along the horizon
    for i in range(30):
        cx = rng.uniform(-60, W + 60)
        cy = rng.uniform(HORIZON + 6, HORIZON + 120)
        rx = rng.uniform(90, 220)
        ry = rng.uniform(22, 52)
        cloud_puff(buf, cx, cy, rx, ry, lit=(i % 3 == 0))
    # deep layer: larger puffs in richer shadow tones (lavender, rose,
    # deep gold) so the lower third stops reading as one flat pale wash
    for i in range(14):
        cx = rng.uniform(-60, W + 60)
        cy = rng.uniform(HORIZON + 50, HORIZON + 220)
        rx = rng.uniform(130, 280)
        ry = rng.uniform(28, 60)
        top = GOLD_DEEP if i % 3 == 0 else CREAM
        shadow = CLOUD_DEEP if i % 2 == 0 else CLOUD_ROSE
        cloud_puff_toned(buf, cx, cy, rx, ry, top, shadow)
    # mid layer: bigger overlapping puffs
    for i in range(24):
        cx = rng.uniform(-40, W + 40)
        cy = rng.uniform(HORIZON + 90, H - 60)
        rx = rng.uniform(110, 260)
        ry = rng.uniform(30, 66)
        cloud_puff(buf, cx, cy, rx, ry, lit=(i % 4 == 0))
    # front layer: a few large soft puffs low down, with shadow
    for i in range(11):
        cx = rng.uniform(0, W)
        cy = rng.uniform(H - 190, H - 30)
        rx = rng.uniform(180, 330)
        ry = rng.uniform(44, 80)
        cloud_puff(buf, cx, cy, rx, ry, lit=False)


def paint_sky_wisps(buf):
    # a few thin high clouds catching the gold light
    for (cx, cy, rx, ry) in [
        (180, 300, 150, 16), (300, 330, 110, 12),
        (820, 210, 170, 15), (700, 260, 120, 11),
        (470, 150, 130, 12), (120, 430, 130, 13),
    ]:
        draw_ellipse(buf, cx, cy, rx, ry, (255, 205, 170), 0.35, soft=0.6)


# ---------------------------------------------------------------- islands

GREEN_TOP = (52, 148, 112)
GREEN_LIGHT = (96, 186, 138)
GREEN_DARK = (28, 96, 74)
ROCK_1 = (128, 78, 96)
ROCK_2 = (98, 60, 86)
ROCK_3 = (70, 44, 70)
ROCK_TIP = (52, 32, 58)


def jagged_rock(buf, x_left, x_right, y_top, y_tip, seed_jitter):
    """Layered, jagged rock underside tapering to a point at (mid, y_tip)."""
    layers = [
        (0.00, ROCK_1, 1.00),
        (0.10, ROCK_2, 0.97),
        (0.22, ROCK_3, 0.94),
    ]
    mid = (x_left + x_right) / 2.0
    for frac, color, shrink in layers:
        y0 = y_top + frac * (y_tip - y_top)
        half = (x_right - x_left) / 2.0 * shrink
        xl = mid - half
        xr = mid + half
        pts = [(xl, y0), (xr, y0)]
        # jagged descent to the tip
        steps = 7
        for s in range(1, steps + 1):
            t = s / steps
            side = 1 if s % 2 == 0 else -1
            wob = rng.uniform(0.05, 0.16) * half * side
            x = mid + wob * (1.0 - t)
            if s == steps:
                x = mid
            y = y0 + t * (y_tip - y0)
            pts.append((x, y))
        fill_polygon(buf, pts, color, 1.0)
    # layered rock; the strata are implied by the colour bands alone,
    # so no drawn lines (they can poke past the jagged silhouette).


def island_top(buf, cx, cy, rx, ry):
    """Domed green crown of an island, with a darker rim and light."""
    # thin dark rim so the crown holds a crisp edge against the sky
    draw_ellipse(buf, cx, cy, rx + 2, ry + 2, (26, 70, 54), 0.85)
    draw_ellipse(buf, cx, cy, rx, ry, GREEN_DARK, 1.0)
    draw_ellipse(buf, cx, cy - ry * 0.12, rx * 0.94, ry * 0.82,
                 GREEN_TOP, 1.0)
    draw_ellipse(buf, cx - rx * 0.25, cy - ry * 0.28, rx * 0.55, ry * 0.45,
                 GREEN_LIGHT, 0.9, soft=0.25)


def distant_island(buf, cx, cy, rx, ry, tip_y):
    """One tiny, hazy island far away, half-sunk in the cloud sea.

    Muted colours and low alpha; drawn before the cloud sea so the
    puffs veil its base. A single depth cue, not a new landmark.
    """
    # soft green dome, washed out by distance haze
    draw_ellipse(buf, cx, cy, rx, ry, (120, 150, 132), 0.75, soft=0.3)
    draw_ellipse(buf, cx - rx * 0.2, cy - ry * 0.25, rx * 0.6, ry * 0.55,
                 (158, 176, 152), 0.6, soft=0.35)
    # short hazy rock tapering to the tip
    mid = cx
    fill_polygon(buf, [(cx - rx * 0.9, cy + 2), (cx + rx * 0.9, cy + 2),
                       (mid + rx * 0.18, cy + (tip_y - cy) * 0.55),
                       (mid, tip_y),
                       (mid - rx * 0.15, cy + (tip_y - cy) * 0.55)],
                 (158, 128, 148), 0.65)


def tree(buf, x, y, h):
    """Small silhouette tree: trunk + two stacked triangles."""
    draw_line(buf, x, y, x, y - int(h * 0.35), (30, 52, 40), 3, 1.0)
    fill_polygon(buf, [(x - h * 0.28, y - int(h * 0.25)),
                       (x + h * 0.28, y - int(h * 0.25)),
                       (x, y - h)], (22, 78, 58), 1.0)
    fill_polygon(buf, [(x - h * 0.22, y - int(h * 0.55)),
                       (x + h * 0.22, y - int(h * 0.55)),
                       (x, y - int(h * 1.15))], (30, 96, 68), 1.0)


def bush(buf, x, y, r):
    draw_ellipse(buf, x, y, r, r * 0.7, (34, 104, 72), 1.0, soft=0.2)
    draw_ellipse(buf, x - r * 0.5, y - r * 0.2, r * 0.6, r * 0.45,
                 (52, 128, 88), 0.9, soft=0.3)


def waterfall(buf, x, y_top, y_bottom, width):
    """A waterfall ribbon falling from an island edge into the clouds."""
    # main ribbon, slightly wavy edges
    pts = []
    steps = 14
    for s in range(steps + 1):
        t = s / steps
        y = y_top + t * (y_bottom - y_top)
        wob = math.sin(t * 9.0) * width * 0.18
        pts.append((x - width / 2 + wob, y))
    for s in range(steps, -1, -1):
        t = s / steps
        y = y_top + t * (y_bottom - y_top)
        wob = math.sin(t * 9.0 + 1.3) * width * 0.18
        pts.append((x + width / 2 + wob, y))
    fill_polygon(buf, pts, (196, 226, 238), 0.92)
    # bright core streaks
    for off in (-width * 0.30, -width * 0.10, width * 0.10, width * 0.30):
        x0 = int(x + off)
        draw_line(buf, x0, int(y_top + 6), x0 + 3, int(y_bottom - 8),
                  (255, 255, 255), 3, 0.6)
    # mist where it meets the clouds — a broad billow plus side puffs
    # so the landing reads clearly instead of fading into the pale sea
    draw_ellipse(buf, x, y_bottom + 6, width * 1.9, 34,
                 (255, 246, 230), 0.8, soft=0.6)
    draw_ellipse(buf, x - width * 0.85, y_bottom + 18, width * 0.9, 20,
                 (255, 248, 236), 0.65, soft=0.65)
    draw_ellipse(buf, x + width * 0.8, y_bottom + 16, width * 0.85, 18,
                 (255, 248, 236), 0.65, soft=0.65)


def lighthouse(buf, x, y_base, h):
    """Small cream lighthouse / temple tower on an island crown."""
    w = 22
    # tower
    fill_rect(buf, x - w // 2, y_base - h, x + w // 2, y_base,
              250, 236, 208, 1.0)
    # warm red band around the tower
    fill_rect(buf, x - w // 2, y_base - h + 12, x + w // 2, y_base - h + 22,
              196, 84, 66, 1.0)
    fill_rect(buf, x - w // 2, y_base - h, x - w // 2 + 4, y_base,
              214, 128, 96, 1.0)
    # gallery + dome
    fill_rect(buf, x - w // 2 - 4, y_base - h - 6, x + w // 2 + 4,
              y_base - h, 214, 128, 96, 1.0)
    fill_polygon(buf, [(x - w // 2 - 2, y_base - h - 6),
                       (x + w // 2 + 2, y_base - h - 6),
                       (x, y_base - h - 22)], (176, 84, 74), 1.0)
    # warm light glow
    draw_ellipse(buf, x, y_base - h - 10, 26, 16, (255, 214, 130),
                 0.55, soft=0.7)
    draw_ellipse(buf, x, y_base - h - 10, 7, 7, (255, 240, 190), 1.0)


# ---------------------------------------------------------------- airship & birds

def airship(buf, cx, cy, scale):
    """Tiny airship with a striped balloon, for scale and wonder."""
    bw = int(74 * scale)
    bh = int(30 * scale)
    # balloon
    draw_ellipse(buf, cx, cy, bw, bh, (196, 84, 66), 1.0)
    draw_ellipse(buf, cx, cy, bw, bh, (232, 140, 92), 0.85, soft=0.3)
    # stripes
    for k in range(-2, 3):
        x0 = cx + k * bw // 3
        draw_line(buf, x0, cy - bh + 6, x0, cy + bh - 6,
                  (250, 226, 180), 3, 0.7)
    # fins
    fill_polygon(buf, [(cx - bw + 6, cy - 2), (cx - bw - 16, cy - 18),
                       (cx - bw - 2, cy - 10)], (176, 84, 66), 1.0)
    fill_polygon(buf, [(cx - bw + 6, cy + 2), (cx - bw - 16, cy + 18),
                       (cx - bw - 2, cy + 10)], (176, 84, 66), 1.0)
    # gondola
    fill_rect(buf, cx - int(20 * scale), cy + bh - 2,
              cx + int(20 * scale), cy + bh + int(12 * scale),
              84, 52, 66, 1.0)
    draw_line(buf, cx - int(16 * scale), cy + bh - 2,
              cx - int(16 * scale), cy + bh + int(12 * scale),
              (52, 32, 44), 2, 1.0)
    draw_line(buf, cx + int(16 * scale), cy + bh - 2,
              cx + int(16 * scale), cy + bh + int(12 * scale),
              (52, 32, 44), 2, 1.0)


def bird(buf, x, y, s):
    """Small chevron bird."""
    draw_line(buf, x - s, y, x, y - int(s * 0.55), (44, 28, 62), 2, 0.9)
    draw_line(buf, x, y - int(s * 0.55), x + s, y, (44, 28, 62), 2, 0.9)


# ---------------------------------------------------------------- type

FONT = {
    'K': ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    'A': [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    'I': ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
    'R': ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    'O': [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    'V': ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    'E': ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    'L': ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
}

TEXT_FG = (255, 240, 214)   # warm cream
TEXT_EDGE = (38, 22, 58)    # dark indigo outline


def draw_text(buf, text, cx, y0, scale, spacing):
    """Draw centred bitmap capitals; outline pass then cream fill."""
    gw, gh = 5, 7
    total = len(text) * gw * scale + (len(text) - 1) * spacing
    x = cx - total // 2
    pad = 5
    for ch in text:
        glyph = FONT[ch]
        for row in range(gh):
            for col in range(gw):
                if glyph[row][col] != '#':
                    continue
                rx = x + col * scale
                ry = y0 + row * scale
                # dark outline: expanded rect behind the cell
                fill_rect(buf, rx - pad, ry - pad,
                          rx + scale + pad, ry + scale + pad,
                          *TEXT_EDGE, a=0.92)
        x += gw * scale + spacing
    x = cx - total // 2
    for ch in text:
        glyph = FONT[ch]
        for row in range(gh):
            for col in range(gw):
                if glyph[row][col] != '#':
                    continue
                rx = x + col * scale
                ry = y0 + row * scale
                fill_rect(buf, rx, ry, rx + scale, ry + scale,
                          *TEXT_FG, a=1.0)
        x += gw * scale + spacing
    return total


def draw_rule(buf, cx, y, half_len):
    """Thin decorative rule with a small diamond, under the name."""
    draw_line(buf, cx - half_len, y, cx + half_len, y,
              (255, 240, 214), 2, 0.85)
    d = 7
    fill_polygon(buf, [(cx, y - d), (cx + d, y), (cx, y + d), (cx - d, y)],
                 (255, 240, 214), 0.95)


# ---------------------------------------------------------------- frame

def paint_frame(buf):
    # vintage travel-poster double border, warm cream
    for inset, thick in ((26, 3), (38, 1)):
        c = (250, 232, 190)
        fill_rect(buf, inset, inset, W - inset, inset + thick, *c, a=0.9)
        fill_rect(buf, inset, H - inset - thick, W - inset, H - inset,
                  *c, a=0.9)
        fill_rect(buf, inset, inset, inset + thick, H - inset, *c, a=0.9)
        fill_rect(buf, W - inset - thick, inset, W - inset, H - inset,
                  *c, a=0.9)


# ---------------------------------------------------------------- scene

def render():
    buf = new_canvas()
    paint_sky(buf)
    paint_sky_wisps(buf)

    # sun low near the horizon, in the open gap between the two
    # big islands so its disc and glow stay visible
    paint_sun(buf, 575, 565, 62)

    # far island, small, near the horizon (depth cue)
    island_top(buf, 455, 612, 62, 20)
    jagged_rock(buf, 398, 512, 616, 672, 0.5)
    bush(buf, 438, 602, 8)
    bush(buf, 474, 604, 6)

    # one more island, much farther and fainter, sinking into the
    # cloud sea at the lower right — depth for the empty third below
    distant_island(buf, 905, 700, 54, 14, 752)

    # middle island, right, with the lighthouse
    island_top(buf, 780, 452, 150, 44)
    jagged_rock(buf, 640, 920, 458, 640, 0.7)
    tree(buf, 700, 442, 34)
    tree(buf, 850, 446, 28)
    bush(buf, 736, 440, 12)
    bush(buf, 820, 442, 10)
    lighthouse(buf, 782, 428, 58)

    # main island, near, left — the hero, with its waterfall
    island_top(buf, 288, 520, 210, 58)
    jagged_rock(buf, 88, 488, 528, 742, 0.9)
    tree(buf, 170, 508, 52)
    tree(buf, 250, 500, 64)
    tree(buf, 330, 508, 46)
    tree(buf, 400, 514, 38)
    bush(buf, 130, 512, 14)
    bush(buf, 372, 506, 12)
    bush(buf, 452, 516, 10)
    # waterfall pouring off the island's left edge into the clouds —
    # wider now, with a clearer mist billow where it lands
    waterfall(buf, 118, 548, 705, 62)

    # sea of clouds below the horizon
    paint_cloud_sea(buf)

    # mist kissing the islands where they meet the clouds
    draw_ellipse(buf, 288, 742, 190, 30, (255, 246, 230), 0.5, soft=0.7)
    draw_ellipse(buf, 780, 640, 150, 24, (255, 246, 230), 0.45, soft=0.7)
    # fresh mist where the waterfall lands in the cloud sea
    draw_ellipse(buf, 118, 706, 88, 34, (255, 248, 236), 0.65, soft=0.7)
    draw_ellipse(buf, 152, 714, 56, 22, (255, 248, 236), 0.5, soft=0.7)

    # airship for scale, high on the right
    airship(buf, 800, 268, 0.85)

    # birds
    for (bx, by, s) in [(330, 250, 12), (392, 218, 9), (452, 262, 10),
                        (600, 190, 9), (180, 340, 10), (540, 300, 8)]:
        bird(buf, bx, by, s)

    # the name, top third, centred
    draw_text(buf, "KAIROVEL", W // 2, 96, 14, 26)
    draw_rule(buf, W // 2, 226, 150)

    paint_frame(buf)
    return buf


# ---------------------------------------------------------------- png

def write_png(path, buf, w, h):
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)  # filter: none
        raw += buf[y * stride:(y + 1) * stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(typ, data):
        out = struct.pack(">I", len(data)) + typ + data
        out += struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        return out

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return len(png)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "./out"
    os.makedirs(out_dir, exist_ok=True)
    buf = render()
    size = write_png(os.path.join(out_dir, "entry.png"), buf, W, H)
    print(f"wrote {os.path.join(out_dir, 'entry.png')} "
          f"{W}x{H} {size} bytes")


if __name__ == "__main__":
    main()
