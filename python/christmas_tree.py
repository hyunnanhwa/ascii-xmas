"""ASCII Christmas Tree — pygame version.

Top: a 3D ASCII Christmas tree on a spinning turntable that builds itself step by step.
Bottom: the whole build script is shown; a highlight reads it line by line, and when it
reaches a line containing phase("name"), that step plays.

Everything on the turntable (tree, tinsel, ornaments, star, floor grid, presents) lives in 3D,
is rotated together, projected by a camera that looks down a little, and depth-tested per cell.

Keys: Space pause · R restart · 2 toggle 2x speed · S screenshot · Esc quit
Run:  python christmas_tree.py                     (needs: pip install pygame)
      python christmas_tree.py --shot 60           (render t=60s to christmas_tree.png and exit)
      python christmas_tree.py --video xmas.mp4    (render the whole show to a 1080x1920 MP4; needs ffmpeg)
      python christmas_tree.py --scale 2           (draw everything twice as big)
"""
import colorsys
import functools
import math
import os
import random
import re
import shutil
import subprocess
import sys

import pygame


def _arg(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        return sys.argv[i + 1] if i + 1 < len(sys.argv) else default
    return default


# ---------------------------------------------------------------- window
TITLE = "ASCII XMAS x NANA"
S = int(_arg("--scale", 2 if "--video" in sys.argv else 1))  # pixel scale (video renders at 2x for crisp text)
COLS, ROWS = 80, 56
CW, CH = 8 * S, 13 * S               # cell size in px
SCENE_W, SCENE_H = COLS * CW, ROWS * CH
BAR_H, CODE_H = 26 * S, 230 * S
W, H = SCENE_W, SCENE_H + BAR_H + CODE_H
FONT_PX = 14 * S
MONO = "consolas,cascadiamono,dejavusansmono,menlo,couriernew,monospace"
HANGUL = "malgungothic,applesdgothicneo,notosanskr,nanumgothic,gulim"

# ---------------------------------------------------------------- scene config
CX, YTOP, TH, R = 40, 6, 33, 27      # apex row, cone height (rows), base radius (cells)
YB = YTOP + TH                       # row of the base center
TILT = 6.5                           # rows a point R cells toward us drops: camera looks down
SCR = "01{}<>#%&$/\\"
DARK, MID, BRIGHT = ".:-~^", "vx*=o+%~", "W&#@%XM"
HOLD = {"sky": 1.0, "ground": 1.0, "tree": 4.0, "tinsel": 2.4, "baubles": 3.8,
        "star": 2.2, "gifts": 2.6, "lights": 1.2, "message": 2.0, "surprise": 6.0}
TREE_POINTS = 5200
TURN = 1.4                           # seconds the finale takes to bring the surprise box to the front
BLANK = "\u00a0"                     # occupies a cell (hides what is behind) but draws nothing
WIDE_PAD = "\0"                      # second cell of a double-width (Hangul) glyph

BG = (5, 7, 13)
GOLD = (255, 209, 102)
WHITE = (245, 241, 255)
RED = (255, 77, 94)

BUILD_SCRIPT = '''\
# christmas_tree.py — ascii renderer
# 80 x 56 cells · monospace · 30 fps

COLS, ROWS = 80, 56
scene = Scene(COLS, ROWS)

# 1. night sky + snow that never stops
for _ in range(160):
    scene.add(Twinkle(rand(COLS), rand(34)))
scene.add(Snow(count=260, layers=3))
scene.phase("sky")

# 2. turntable floor (rings + spokes) — everything on it spins
stage = Turntable(rings=[31, 39, 47, 55], spokes=16)
camera = Camera(pitch="slightly above", persp=1 / 6)
scene.phase("ground")

# 3. a 3D tree: dense inner foliage + glyph points on drooping branches
tree = stage.add(PointTree(height=33, radius=27, layers=15))
tree.fill(core=".:;~-^")
tree.glyphs(dark=".:-~^", mid="vx*=o+%", bright="W&#@%XM")
tree.lights(density=0.075, colors=[GOLD, AMBER, RED])
tree.grow(start="bottom", scramble="01{}<>#%&")
scene.phase("tree")

# 4. extra-thick tinsel: 5 strands, gold + white, wound bottom -> top
tinsel = spiral(tree, turns=3.2, strands=5, start="bottom")
scene.phase("tinsel")

# 5. big round baubles — red and gold only, each twinkles in
for i, p in enumerate(tree.scatter(14)):
    tree.hang(Bauble(p, [RED, GOLD][i % 2], size="XXL"), appear="twinkle")
scene.phase("baubles")

# 6. a 3D five-pointed star, seated on the tip
star = tree.apex.add(Star3D(points=5, bevel=True))
star.drop(then=star.rays)
scene.phase("star")

# 7. small 3D presents around the tree (ribbons, no bows)
gifts = [stage.add(Box3D(color=c, ribbon="cross", dist=34))
         for c in [RED, GREEN, BLUE, GOLD, PINK, ORANGE]]
stage.appear("sparkle")
scene.phase("gifts")

# 8. lights on, heavier snow
tree.lights_on()
tinsel.lights(every=6, blink=0.8)
scene.phase("lights")

# 9. greeting
scene.type("MERRY CHRISTMAS 2026", y=52)
scene.phase("message")

# 10. one present pops open... surprise!
box = next(g for g in gifts if g.facing_camera())
frog = box.lid.pop(then=lambda: box.release(Frog()))
frog.say("앙기모띠!!")
scene.phase("surprise")

# spin the whole turntable forever
while True:
    stage.rotation += 0.3 * dt
    scene.render(camera)
'''


# ---------------------------------------------------------------- helpers
def clamp(v, a=0.0, b=1.0):
    return a if v < a else b if v > b else v


def ease(x):
    return 1 - (1 - x) ** 3


def bounce(x):
    n, d = 7.5625, 2.75
    if x < 1 / d:
        return n * x * x
    if x < 2 / d:
        x -= 1.5 / d
        return n * x * x + .75
    if x < 2.5 / d:
        x -= 2.25 / d
        return n * x * x + .9375
    x -= 2.625 / d
    return n * x * x + .984375


def ihash(a, b):
    """integer hash -> [0, 1), deterministic per (a, b)"""
    n = (a * 374761393 + b * 668265263) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= n >> 16
    return n / 4294967296.0


@functools.lru_cache(maxsize=65536)
def _hsl(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h / 360, l / 100, s / 100)
    return (int(r * 255), int(g * 255), int(b * 255))


def hsl(h, s, l):
    """hue in degrees, saturation/lightness 0..1 — cached on whole-number values"""
    return _hsl(int(h) % 360, int(clamp(s) * 100), int(clamp(l) * 100))


def fade(col, a):
    """alpha over the dark background"""
    a = clamp(a)
    return (int(BG[0] + (col[0] - BG[0]) * a), int(BG[1] + (col[1] - BG[1]) * a), int(BG[2] + (col[2] - BG[2]) * a))


def hexc(s):
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def is_wide(c):
    o = ord(c[0])
    return 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F or 0xAC00 <= o <= 0xD7AF


def radius(h):
    return R * (0.04 + 0.96 * h ** 0.9)


# ---------------------------------------------------------------- static data
rng = random.Random(20261225)
N = COLS * ROWS
cell_rand = [rng.random() for _ in range(N)]

# 3D tree: points on drooping branches (h = height 0..1 from apex, th = angle, rr = distance from trunk)
LAYERS = 15
LIGHT_KINDS = (RED, GOLD, (255, 179, 71))
# mixed needle greens (hue, saturation, lightness offset): pine, forest, olive, blue spruce, fresh tips
GREENS = ((148, 0.48, -0.04), (128, 0.55, 0.0), (96, 0.42, 0.02), (168, 0.34, -0.02), (108, 0.62, 0.08))


def lump(th, h):
    """lumpy silhouette: bulges fixed to the tree, so they turn with it"""
    return 1 + 0.11 * math.sin(th * 5 + h * 17) + 0.07 * math.sin(th * 9 - h * 29) + 0.05 * math.sin(th * 3 + h * 41)


tree_pts = []
for _ in range(TREE_POINTS):
    layer = int(rng.random() ** 0.8 * LAYERS)
    spokes = 7 + layer
    spoke = rng.randrange(spokes)
    reach = 0.82 + 0.34 * ihash(spoke + 31, layer)        # every branch has its own length
    q = (0.42 + 0.64 * rng.random() ** 0.4) * reach
    h = min(1.0, (layer + 0.2 + rng.random() * 0.6) / LAYERS + q * q * 0.05)
    th = (spoke + 0.5 + (rng.random() - 0.5) * 0.6) / spokes * math.tau + layer * 0.9
    kind = rng.random()
    light = None
    if kind < 0.075:
        light = LIGHT_KINDS[0] if kind < 0.02 else LIGHT_KINDS[1] if kind < 0.05 else LIGHT_KINDS[2]
    fam = 4 if (q > 1.0 and rng.random() < 0.5) else int(ihash(spoke * 7 + layer, 3) * 4.999) % 4
    tree_pts.append((h, th, radius(h) * q * lump(th, h), q, rng.random(), light, 1.5 + rng.random() * 3,
                     rng.random() * 6.28, GREENS[fam]))

# 3D star: beveled five-pointed star sitting on the apex (u, v in row units)
STAR_R, STAR_IN = 3.3, 0.42
STAR_CY = YTOP - 2.5


def _star_points():
    poly = []
    for k in range(10):
        ang = -math.pi / 2 + k * math.pi / 5
        r = STAR_R * STAR_IN if k % 2 else STAR_R
        poly.append((math.cos(ang) * r, math.sin(ang) * r))

    def inside(x, y):
        c, j = False, 9
        for i in range(10):
            xi, yi = poly[i]
            xj, yj = poly[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                c = not c
            j = i
        return c

    pts, arm = [], math.tau / 5
    v = -STAR_R
    while v <= STAR_R:
        u = -STAR_R
        while u <= STAR_R:
            if inside(u, v):
                ang = math.atan2(v, u) + math.pi / 2
                rel = (ang % arm + arm) % arm - arm / 2
                pts.append((u, v, math.cos(rel * 2.4), 1 if rel > 0 else -1, math.hypot(u, v) / STAR_R))
            u += 0.12
        v += 0.2
    return pts


star_pts = _star_points()

stars = [(rng.randrange(COLS), rng.randrange(34), 0.6 + rng.random() * 2.2, rng.random() * 6.28) for _ in range(160)]
# big, plain round baubles in two colors only: red and gold (hue, saturation)
BAUBLE_HUES = ((355, 0.85), (44, 0.95))
baubles = [(0.22 + 0.72 * (i + rng.random() * 0.6) / 14, i * 2.39996 + rng.random() * 0.3, BAUBLE_HUES[i % 2]) for i in range(14)]
BALL = (" @@@@@ ", "@@@@@@@", "@@@@@@@", " @@@@@ ")
BALL_SIDE = (" @@@ ", "@@@@@", " @@@ ")
LIGHT_COLORS = [hexc(c) for c in ("#ff4d5e", "#ffd166", "#5aa8ff", "#ff8fd0", "#7dffb0")]
# presents: angle/distance from trunk, w/d (cells), h (rows), own yaw, paper hue/sat, ribbon hue/sat
GIFTS = [
    dict(ang=0.35, dist=33, w=7, d=6, h=3.2, yaw=0.55, hue=355, sat=0.75, rib=(45, 0.95)),
    dict(ang=-0.6, dist=34, w=6, d=6, h=2.8, yaw=-0.6, hue=140, sat=0.55, rib=(355, 0.85)),
    dict(ang=1.45, dist=34, w=5, d=5, h=2.6, yaw=0.9, hue=215, sat=0.70, rib=(0, 0.0)),
    dict(ang=2.6, dist=33, w=7, d=5, h=3.0, yaw=0.25, hue=45, sat=0.90, rib=(355, 0.85)),
    dict(ang=-2.0, dist=34, w=6, d=5, h=3.0, yaw=0.7, hue=300, sat=0.55, rib=(45, 0.95)),
    dict(ang=3.9, dist=36, w=5, d=4, h=2.4, yaw=-0.35, hue=15, sat=0.80, rib=(0, 0.0)),
]
BOX_FILL = "#%&@8$X"
LDIR = (-0.55 / math.hypot(0.55, 0.8), 0.8 / math.hypot(0.55, 0.8))
floor_dots = [(rng.random() * math.tau, 29 + rng.random() * 30) for _ in range(220)]
MSG = " ".join("MERRY CHRISTMAS 2026")
# a proper frog: bulging eyes on top, wide smile, red scarf, front legs and big feet (all greens, no black)
PAL = {"R": RED, "W": WHITE, "G": (182, 242, 90), "L": (228, 255, 138), "D": (134, 217, 74), "Y": GOLD}
FROG_BIG = (["  .--.    .--.  ",
             " (#OO#)##(#OO#) ",
             " /############\\ ",
             "|##\\________/##|",
             " \\##'~~~~~~'##/ ",
             " /_/########\\_\\ ",
             "(__)        (__)"],
            ["  GGGG    GGGG  ",
             " GLWWLGGGGLWWLG ",
             " GLLLLLLLLLLLLG ",
             "GLLDDDDDDDDDDLLG",
             " GLLRRRRRRRRLLG ",
             " GGGLLLLLLLLGGG ",
             "GGGG        GGGG"])
FROG_BLINK_ROW = " (#--#)##(#--#) "
BUBBLE_TEXT = ["앙", "기", "모", "띠", "!", "!"]
CORE = ".:;~-^"


def make_snow():
    out = []
    for _ in range(260):
        z = rng.random()
        out.append([rng.random() * COLS, rng.random() * ROWS - ROWS, z, 1.5 + z * 6, rng.random() * 6.28,
                    "*" if z > 0.8 else "'" if z > 0.45 else "."])
    return out


# ---------------------------------------------------------------- app
class App:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption(TITLE)
        self.screen = pygame.display.set_mode((W, H))
        self.font = pygame.font.SysFont(MONO, FONT_PX, bold=True)
        self.kfont = pygame.font.SysFont(HANGUL, FONT_PX, bold=True)
        self.code_font = pygame.font.SysFont(MONO, 13 * S)
        self.code_kfont = pygame.font.SysFont(HANGUL, 13 * S)
        self.hud_font = pygame.font.SysFont(MONO, 11 * S)
        self.title_font = pygame.font.SysFont(MONO, 13 * S, bold=True)
        self.glyphs = {}
        self.glows = {}
        self.src = BUILD_SCRIPT.rstrip("\n").split("\n")
        self.clock = pygame.time.Clock()
        self.speed = 1
        self.paused = False
        self.restart()

    # ---------------- state
    def restart(self):
        self.t = 0.0
        self.rot = 0.0
        self.phases = {}
        self.li = -1
        self.line_t = self.hold = 0.0
        self.snow = make_snow()
        self.lit = 0
        self.open_idx = -1
        self.rot_from = self.rot_to = self.star_to = 0.0

    def age(self, name):
        return self.t - self.phases[name] if name in self.phases else -1.0

    def prog(self, name, dur):
        return clamp((self.t - self.phases[name]) / dur) if name in self.phases else 0.0

    def update_rotation(self, dt):
        """the turntable spins; in the finale it eases the box nearest the front to face the camera"""
        sa = self.age("surprise")
        if sa < 0:
            if "ground" in self.phases:
                self.rot += dt * 0.3
            return
        if self.open_idx < 0:
            self.open_idx = max(range(len(GIFTS)), key=lambda i: math.cos(GIFTS[i]["ang"] + self.rot))
            self.rot_from = self.rot
            self.rot_to = -GIFTS[self.open_idx]["ang"]
            while self.rot_to < self.rot_from:
                self.rot_to += math.tau
            if self.rot_to - self.rot_from > math.pi * 1.2:
                self.rot_to -= math.tau
            self.star_to = math.ceil(self.rot_from / math.tau) * math.tau  # the star ends facing the camera
        k = clamp(sa / TURN)
        self.rot = self.rot_from + (self.rot_to - self.rot_from) * (1 - (1 - k) ** 3)

    # ---------------- grid with depth
    def clear(self):
        self.gc = [""] * N
        self.gcol = [BG] * N
        self.gglow = [False] * N
        self.gz = [-1e9] * N

    def put(self, x, y, c, col, glow=False, z=1e6):
        x, y = int(round(x)), int(round(y))
        if c == " " or x < 0 or y < 0 or x >= COLS or y >= ROWS:
            return False
        i = y * COLS + x
        if z < self.gz[i]:
            return False
        self.gc[i], self.gcol[i], self.gglow[i], self.gz[i] = c, col, glow, z
        if c > "ჿ" and is_wide(c) and x + 1 < COLS:
            self.gc[i + 1], self.gz[i + 1], self.gglow[i + 1] = WIDE_PAD, z, False
        return True

    # ---------------- camera
    def proj(self, h, th, rr):
        a = th + self.rot
        sx, cz = math.sin(a), math.cos(a)
        z = rr * cz
        persp = 1 + z / (R * 6)
        return CX + rr * sx * persp, YTOP + h * TH + TILT * (z / R), z, sx, cz, persp

    def on_tree(self, h, a, k=1.0):
        return self.proj(h, a, radius(h) * k)

    def on_floor(self, th, r):
        return self.proj(1.0, th, r)

    def to_view(self, x, z):
        c, s = math.cos(self.rot), math.sin(self.rot)
        return x * c + z * s, z * c - x * s

    def proj_w(self, wx, wz, up):
        """a point on the turntable, `up` rows above the floor -> screen x, y, depth"""
        vx, vz = self.to_view(wx, wz)
        persp = 1 + vz / (R * 6)
        return CX + vx * persp, YB + TILT * (vz / R) - up * persp, vz

    # ---------------- appear effect
    @staticmethod
    def sprite_cells(sp, x, y, z):
        out = []
        for r, row in enumerate(sp[0]):
            for k, c in enumerate(row):
                if c != " ":
                    out.append((x + k, y + r, c, PAL.get(sp[1][r][k], WHITE), False, z))
        return out

    def materialize(self, cells, a, seed, glow_white=False):
        """sparkle burst, then each glyph resolves out of a scramble, in place"""
        if a < 0 or not cells:
            return
        mx = sum(c[0] for c in cells) / len(cells)
        my = sum(c[1] for c in cells) / len(cells)
        mz = max(c[5] for c in cells)
        if a < 0.9:
            f = 1 - a / 0.9
            for j in range(8):
                ang = j / 8 * math.tau + seed + a * 2
                rad = 1.5 + a * 4 + (j % 2) * 1.2
                if math.sin(self.t * 25 + j * 2 + seed) > -0.2:
                    self.put(mx + math.cos(ang) * rad * 1.6, my + math.sin(ang) * rad * 0.6,
                             "*" if j % 3 == 0 else "+", fade((255, 246, 208), f), True, mz + 1)
        for k, cell in enumerate(cells):
            x, y, c, col, glow, z = cell[:6]
            show = 0.12 + cell_rand[(k * 31 + int(seed * 97)) % N] * 0.3
            if a < show:
                continue
            if a < show + 0.18:
                self.put(x, y, SCR[(k + int(self.t * 24)) % len(SCR)], (255, 255, 255), True, z)
            else:
                self.put(x, y, c, col, glow or (glow_white and col == WHITE), z)

    # ---------------- layers
    def draw_sky(self):
        p = self.prog("sky", 1.0)
        if not p:
            return
        for i, (x, y, sp, ph) in enumerate(stars):
            if i / len(stars) > p:
                break
            b = 0.5 + 0.5 * math.sin(self.t * sp + ph)
            self.put(x, y, "*" if b > 0.92 else "+" if b > 0.7 else ".", fade((200, 215, 255), 0.25 + b * 0.7), b > 0.92, -1e8)

    def draw_snow(self, dt, front):
        if self.age("sky") < 0:
            return
        density = 1.0 if self.age("lights") >= 0 else 0.55
        n = len(self.snow)
        for i, s in enumerate(self.snow):
            if front != (s[2] > 0.6):
                continue
            s[1] += s[3] * dt
            s[0] += (math.sin(self.t * 0.8 + s[4]) * 0.5 + 0.35) * dt * (0.6 + s[2])
            if s[1] > ROWS:
                s[1] = -1 - rng.random() * 4
                s[0] = rng.random() * COLS
            if s[0] > COLS:
                s[0] -= COLS
            if i / n > density or s[1] < 0:
                continue
            self.put(s[0], s[1], s[5], fade((235, 242, 255), 0.35 + s[2] * 0.6), s[2] > 0.92, 200 if front else -1e8 + 1)

    def draw_ground(self):
        p = self.prog("ground", 1.0)
        if not p:
            return
        reach = ease(p)

        def fl(q, c, a):
            depth = 0.5 + 0.5 * q[4]
            self.put(q[0], q[1], c, fade((150, 170, 215), a * (0.45 + 0.55 * depth)), False, -1e7 + q[2])

        for ri, r in enumerate((31, 39, 47, 55)):
            if ri / 4 > reach:
                continue
            th = 0.0
            while th < math.tau:
                fl(self.on_floor(th, r), "-", 0.42)
                th += 0.6 / r
        for k in range(16):
            th = k / 16 * math.tau
            r = 29.0
            while r < 29 + 28 * reach:
                fl(self.on_floor(th, r), ".", 0.4)
                r += 1.3
        for i, (th, r) in enumerate(floor_dots):
            if i / len(floor_dots) < reach:
                fl(self.on_floor(th, r), "'", 0.3)
        th = 0.0
        while th < math.tau:  # soft shadow ring right under the branches
            fl(self.on_floor(th, R * 1.05), "~", 0.22)
            th += 0.03

    def draw_core(self, p):
        """dense inner foliage behind the branch points, so the tree never looks hollow"""
        z = -R * 0.4 - 2
        rot_key = int(self.rot * 6)
        y = YTOP + 1
        while y <= YTOP + TH + TILT * 0.8:
            h = min(1.0, (y - YTOP) / TH)
            if p >= (1 - h) * 0.8 + 0.16:
                r = radius(h) * 0.8
                for x in range(math.ceil(CX - r), math.floor(CX + r) + 1):
                    u = (x - CX) / r
                    front = math.sqrt(max(0.0, 1 - u * u))
                    if h >= 1 and (y - YTOP - TH) > TILT * 0.8 * front:
                        continue
                    hv = ihash(x * 7 + rot_key, y)
                    l = 7 + (0.5 - u * 0.3) * 14 * front + hv * 5
                    g0 = GREENS[int(ihash(x, y * 5 + 1) * 4)]
                    self.put(x, y, CORE[int(hv * len(CORE))], hsl(g0[0], g0[1], l / 100), False, z)
            y += 1

    def draw_tree(self):
        a = self.age("tree")
        if a < 0:
            return
        p = a / 3.4
        lights_on = self.age("lights") >= 0
        self.lit = 0
        self.draw_core(p)
        t, rot = self.t, self.rot
        put = self.put
        sin, cos = math.sin, math.cos
        for i, (h, th, rr, q, g, light, tw_sp, ph, green) in enumerate(tree_pts):
            thr = (1 - h) * 0.8 + g * 0.2
            if p < thr:
                continue
            ang = th + rot
            sx, cz = sin(ang), cos(ang)
            z = rr * cz
            persp = 1 + z / (R * 6)
            x = CX + rr * sx * persp
            y = YTOP + h * TH + TILT * (z / R)
            if p - thr < 0.06:
                put(x, y, SCR[(i + int(t * 30)) % len(SCR)], (125, 255, 176), True, z)
                continue
            diff = max(0.0, -0.5 * sx + 0.75 * cz + 0.25)
            depth = 0.5 + 0.5 * cz
            b = clamp((0.2 + 0.8 * diff * (0.7 + 0.3 * g)) * (0.5 + 0.5 * depth) * (0.8 + 0.3 * q))
            if light:
                tw = 0.5 + 0.5 * sin(t * tw_sp + ph)
                lit = lights_on and tw > 0.35
                front = cz > -0.1
                if lit and front:
                    self.lit += 1
                if lit:
                    put(x, y, "@" if (tw > 0.8 and front) else "*", light if front else fade((255, 190, 90), 0.45), front, z)
                else:
                    put(x, y, "o", fade((255, 190, 90), 0.2 + b * 0.5), False, z)
                continue
            s = BRIGHT if b > 0.55 else MID if b > 0.3 else DARK
            hue, sat, lo = green
            put(x, y, s[int(g * len(s))],
                hsl(hue + (g - 0.5) * 12, sat + depth * 0.12, clamp(0.05 + b * 0.55 + lo - (1 - min(1.0, q)) * 0.06, 0.04, 0.7)),
                False, z)

    def draw_tinsel(self):
        """extra-thick tinsel: five strands side by side, gold + white, wound from the bottom up"""
        p = self.prog("tinsel", 2.2)
        if not p:
            return
        lights_on = self.age("lights") >= 0
        s, k = 0.0, 0
        while s <= p:
            for strand in (-2, -1, 0, 1, 2):
                x, y, z, _, cz, _ = self.on_tree(0.98 - s * 0.92 + strand * 0.0095, s * math.tau * 3.2, 1.05 + abs(strand) * 0.006)
                front = cz > 0
                shade = 0.3 + 0.7 * (0.5 + 0.5 * cz)
                if strand == 0 and lights_on and k % 6 == 0:
                    if math.sin(self.t * 3 + k * 1.7) > -0.3:
                        if self.put(x, y, "@" if front else "*", LIGHT_COLORS[(k // 6) % 5], front, z + 0.8) and front:
                            self.lit += 1
                    continue
                shimmer = math.sin(s * 90 - self.t * 7 + strand)
                if shimmer > 0.9 and front:
                    self.put(x, y, "*", (255, 255, 255), True, z + 0.6)
                    continue
                edge = abs(strand) == 2
                if strand == 0:
                    base = (255, 240, 180)
                else:
                    base = (255, 252, 240) if (k + strand) % 2 else (255, 222, 120)
                ch = "~" if edge else ("#" if (strand == 0 and shimmer > 0.5) else "=")
                self.put(x, y, ch, fade(base, shade * (0.8 if edge else 1)), front and cz > 0.6 and not edge, z + 0.6)
            s += 0.002
            k += 1
        if p < 1:
            x, y, z, _, _, _ = self.on_tree(0.98 - p * 0.92, p * math.tau * 3.2, 1.05)
            self.put(x, y, "@", (255, 246, 208), True, z + 1)

    def draw_baubles(self):
        a = self.age("baubles")
        if a < 0:
            return
        for i, (h, ang, (hue, sat)) in enumerate(baubles):
            ba = a - i * 0.2
            if ba < 0:
                continue
            x, y, z, _, cz, _ = self.on_tree(h, ang, 1.05)
            if cz <= -0.2:
                continue
            z += 1.5
            x, y = round(x), round(y)
            if ba < 0.9:  # twinkle-in: 4-point sparkle flares and spins, ball flashes white, then settles
                f = ba / 0.25 if ba < 0.25 else 1 - (ba - 0.25) / 0.65
                ln = 1 + f * 5
                rays = (((1, 1, "\\"), (-1, -1, "\\"), (1, -1, "/"), (-1, 1, "/")) if ba > 0.45
                        else ((1, 0, "-"), (-1, 0, "-"), (0, 1, "|"), (0, -1, "|")))
                for dx, dy, c in rays:
                    s = 1
                    while s <= ln:
                        self.put(x + dx * s * 1.6, y + dy * s * 0.7, "+" if s >= ln - 0.5 else c,
                                 fade((255, 246, 208), f * (1 - s / (ln + 1))), True, z + 0.5)
                        s += 1
                self.put(x, y, "*", (255, 255, 255), True, z + 1)
                if ba < 0.3:
                    continue
            flash = clamp(1 - (ba - 0.3) / 0.35)
            shape = BALL_SIDE if cz < 0.45 else BALL
            w, hgt = len(shape[0]), len(shape)
            for r, row in enumerate(shape):
                for k, ch in enumerate(row):
                    if ch == " ":
                        continue
                    nx = (k - (w - 1) / 2) / (w / 2)
                    ny = (r - (hgt - 1) / 2) / (hgt / 2)
                    light = clamp(0.62 - nx * 0.18 - ny * 0.2 + (cz - 0.5) * 0.12, 0.3, 0.75)
                    lum = light * 0.7 + flash * (0.95 - light * 0.7)
                    self.put(x - w // 2 + k, y - hgt // 2 + r, "@" if light > 0.6 else "#" if light > 0.45 else "%",
                             hsl(hue, sat * (1 - flash * 0.8), lum), True, z)
            if shape is BALL and math.sin(self.t * 1.7 + i * 2.1) > 0.94:
                self.put(x - 2, y - 1, "*", (255, 255, 255), True, z + 0.5)

    def draw_star(self):
        """beveled 3D star on the apex; turns with the tree (wide facing us, a sliver edge-on)"""
        a = self.age("star")
        if a < 0:
            return
        k = clamp(a / 1.0)
        cy = STAR_CY - (1 - bounce(k)) * 12
        phi = self.rot + (1 - k) * 6  # spins fast while falling
        sa = self.age("surprise")
        if sa >= 0 and self.open_idx >= 0:  # finale: turn to face us
            phi = self.rot_from + (self.star_to - self.rot_from) * ease(clamp(sa / TURN))
        cphi, sphi = math.cos(phi), math.sin(phi)
        back = cphi < 0
        facing = abs(cphi)
        for u, v, bevel, side, d in star_pts:
            hx = u * 1.62
            side_light = side * (1 if back else -1) * 0.12
            L = clamp((0.4 + 0.6 * facing) * (0.62 + 0.38 * bevel) + (1 - d) * 0.18 + side_light) * (0.85 if back else 1)
            self.put(CX + hx * cphi, cy + v, "@" if L > 0.78 else "#" if L > 0.62 else "*" if L > 0.46 else "+",
                     hsl(46 - (1 - L) * 8, 0.96, 0.30 + L * 0.50), L > 0.66, 500 + hx * sphi)
        fa = a - 1.0
        if fa > 0:
            burst = max(0.0, 1 - fa / 1.2)
            for j, (deg, ch) in enumerate([(-90, "|"), (-62, "/"), (-118, "\\"), (-35, "/"), (-145, "\\"), (0, "-"), (180, "-")]):
                ang = math.radians(deg)
                ln = (7 if deg == -90 else 7.5) * (0.75 + 0.25 * math.sin(self.t * 2.4 + j)) + burst * 10
                s = STAR_R + 1
                while s < ln + STAR_R:
                    self.put(CX + math.cos(ang) * s * 1.6, cy + math.sin(ang) * s, ch,
                             fade((255, 224, 150), (1 - (s - STAR_R) / ln) * (0.5 + 0.45 * burst)), s < STAR_R + 2, 400)
                    s += 0.8
        if 0 < fa < 0.9:
            rad, al = STAR_R + ease(fa / 0.9) * 14, 1 - fa / 0.9
            for j in range(48):
                ang = j / 48 * math.tau
                self.put(CX + math.cos(ang) * rad * 1.6, cy + math.sin(ang) * rad, "+" if j % 2 else "*", fade((255, 214, 120), al), True, 400)

    # ---------------- 3D presents
    def box_cells(self, g, gi, opened):
        """a real 3D box: visible side faces + lid sampled in 3D, ribbons crossing every face, no bows.
        cells are (x, y, char, color, glow, z, is_lid)"""
        cxw, czw = g["dist"] * math.sin(g["ang"]), g["dist"] * math.cos(g["ang"])
        cy, sy = math.cos(g["yaw"]), math.sin(g["yaw"])
        hw, hd, Hh = g["w"] / 2, g["d"] / 2, g["h"]
        rib_h, rib_s = g["rib"]
        out = []

        def P(lx, lz, up):
            return self.proj_w(cxw + lx * cy + lz * sy, czw - lx * sy + lz * cy, up)

        def paper(l):
            return hsl(g["hue"], g["sat"], l)

        def ribbon(l):
            return hsl(rib_h, rib_s, (0.5 + l * 0.45) if rib_s == 0 else (0.28 + l * 0.42))

        def sample(o, U, V, kind, light, lid):
            lu = math.hypot(U[0], U[1])
            lv = V[2] if kind == "side" else math.hypot(V[0], V[1])
            nu = math.ceil(lu * 2.2) + 1
            nv = math.ceil(lv * (2.6 if kind == "side" else 2.2)) + 1
            for a in range(nu):
                for b in range(nv):
                    u, v = (a + 0.5) / nu, (b + 0.5) / nv
                    x, y, z = P(o[0] + U[0] * u + V[0] * v, o[1] + U[1] * u + V[1] * v, o[2] + U[2] * u + V[2] * v)
                    hv = ihash(gi * 131 + a * 7 + (3 if kind == "top" else 0), b * 13 + 1)
                    rib_u = abs(u - 0.5) < 0.1
                    rib_v = abs(v - 0.5) < (0.14 if kind == "side" else 0.1)
                    edge_u = a == 0 or a == nu - 1
                    edge_v = b == 0 or b == nv - 1
                    if kind == "in":
                        c, col = ("." if hv < 0.5 else ":"), paper(0.12)
                    elif rib_u or rib_v:
                        c = "+" if (rib_u and rib_v) else "|" if rib_u else "="
                        col = ribbon(light)
                    elif kind == "side" and edge_u:
                        c, col = "|", paper(light * 0.48)
                    elif kind == "side" and b == nv - 1:
                        c, col = "-", paper(light * 0.7 + 0.12)
                    elif kind == "top" and (edge_u or edge_v):
                        c, col = "=", paper(0.72)
                    else:
                        c, col = BOX_FILL[int(hv * len(BOX_FILL))], paper(light * (0.52 + hv * 0.1))
                    out.append((x, y, c, col, False, z + (0.05 if kind == "top" else 0), lid))

        for o, U, V, n in (((-hw, hd, 0), (g["w"], 0, 0), (0, 0, Hh), (0, 1)),
                           ((hw, -hd, 0), (-g["w"], 0, 0), (0, 0, Hh), (0, -1)),
                           ((hw, hd, 0), (0, -g["d"], 0), (0, 0, Hh), (1, 0)),
                           ((-hw, -hd, 0), (0, g["d"], 0), (0, 0, Hh), (-1, 0))):
            vx, vz = self.to_view(n[0] * cy + n[1] * sy, -n[0] * sy + n[1] * cy)
            if vz <= 0.03:
                continue  # facing away
            sample(o, U, V, "side", 0.35 + 0.6 * max(0.0, vx * LDIR[0] + vz * LDIR[1]), False)
        if opened:
            sample((-hw, -hd, Hh - 0.05), (g["w"], 0, 0), (0, g["d"], 0), "in", 0, False)  # dark inside
        sample((-hw, -hd, Hh + 0.02), (g["w"], 0, 0), (0, g["d"], 0), "top", 0.95, True)    # lid
        return out

    def draw_bubble(self, ba, bx, top_row, frog_x, frog_y, z):
        """speech bubble above the box: thought puffs, bubble grows from its center, text types in"""
        if ba < 0:
            return
        inner = 12
        wb = inner + 2
        x0 = round(bx - wb / 2)
        y0 = max(1, top_row - 6)
        head_x, head_y = frog_x + 8, frog_y - 1
        for j, (f, c) in enumerate(((0.35, "."), (0.6, "o"), (0.85, "O"))):
            if ba >= j * 0.08:
                self.put(head_x + (x0 + wb - 3 - head_x) * f, head_y + (y0 + 3 - head_y) * f, c, WHITE, False, z)
        g = clamp((ba - 0.25) / 0.2)
        if g <= 0:
            return
        yy = y0 + (-1 if math.sin(self.t * 3) > 0.6 else 0)
        half = round(wb / 2 * g)
        cxb = x0 + wb / 2
        for x in range(round(cxb - half), round(cxb + half)):
            left, right = x == x0, x == x0 + wb - 1
            self.put(x, yy, "." if (left or right) else "-", WHITE, False, z)
            self.put(x, yy + 1, "(" if left else ")" if right else BLANK, WHITE, False, z)
            self.put(x, yy + 2, "'" if (left or right) else "-", WHITE, False, z)
        if g < 1:
            return
        self.put(x0 + wb - 4, yy + 3, "\\", WHITE, False, z)
        cx = x0 + 2
        for i, ch in enumerate(BUBBLE_TEXT):
            if ba - 0.5 < i * 0.14:
                break
            self.put(cx, yy + 1, ch, RED if ch == "!" else GOLD, True, z + 1)
            cx += 2 if is_wide(ch) else 1

    def draw_gifts(self):
        a = self.age("gifts")
        if a < 0:
            return
        sa = self.age("surprise") - TURN
        for i, g0 in enumerate(GIFTS):
            is_open = i == self.open_idx
            g = dict(g0, dist=g0["dist"] + 9 * ease(clamp(self.age("surprise") / TURN))) if is_open else g0
            opened = is_open and sa >= 0
            cells = self.box_cells(g, i, opened)
            if not opened:
                self.materialize(cells, a - i * 0.25, i * 2.3 + 5)
                continue
            body = [c for c in cells if not c[6]]
            top_row = min(round(c[1]) for c in body)
            box_l = min(round(c[0]) for c in body)
            box_r = max(round(c[0]) for c in body)
            box_bottom = max(round(c[1]) for c in body)
            box_cx, box_z = (box_l + box_r) / 2, max(c[5] for c in body)
            # lid pops straight up, then slides off to the left and lands on the floor
            k1, k2 = ease(clamp(sa / 0.45)), ease(clamp((sa - 0.45) / 0.6))
            lid_dx = -k2 * (box_r - box_l + 3)
            lid_dy = -k1 * 4 + k2 * (4 + box_bottom - top_row - 1)
            cells = [(c[0] + lid_dx, c[1] + lid_dy) + tuple(c[2:]) if c[6] else c for c in cells]
            self.materialize(cells, 5, 0)
            if sa < 1.6:  # confetti
                for j in range(22):
                    ang = -math.pi / 2 + (ihash(j, 3) - 0.5) * 2.4
                    spd = 6 + ihash(j, 9) * 10
                    self.put(box_cx + math.cos(ang) * spd * sa * 1.6, top_row + math.sin(ang) * spd * sa + 9 * sa * sa,
                             "*+o."[j % 4], LIGHT_COLORS[j % 5], True, box_z + 3)
            fk = clamp((sa - 0.4) / 1.0)  # frog leaps out on an arc and lands beside the box
            if fk <= 0:
                continue
            fh = len(FROG_BIG[0])
            sx, sy = box_cx - 8, top_row
            ex, ey = box_r + 3, box_bottom - fh + 1
            k = ease(fk)
            fx = sx + (ex - sx) * k
            fy = sy + (ey - sy) * k - math.sin(fk * math.pi) * 9 - (1 - fk) * fh * min(1.0, fk * 6)
            rows = FROG_BIG[0]
            if math.sin(self.t * 1.3) > 0.97:  # blink
                rows = [FROG_BLINK_ROW if j == 1 else r for j, r in enumerate(rows)]
            for (x, y, c, col, _, z) in self.sprite_cells((rows, FROG_BIG[1]), round(fx), round(fy), box_z + 4):
                if fk > 0.35 or y < top_row:  # hidden while still inside the box
                    self.put(x, y, c, col, True, z)
            if fk >= 1:
                self.draw_bubble(sa - 1.6, box_cx, top_row, round(fx), round(fy), 900)

    def draw_message(self):
        a = self.age("message")
        if a < 0:
            return
        x0 = CX - len(MSG) // 2
        cols = [RED, GOLD, (125, 255, 176), WHITE]
        for i, ch in enumerate(MSG):
            if a < i * 0.05:
                break
            fresh = a - i * 0.05 < 0.12
            self.put(x0 + i, 52, SCR[(i + int(self.t * 20)) % len(SCR)] if fresh else ch,
                     (255, 255, 255) if fresh else cols[(i + int(self.t * 1.5)) % 4], True, 1000)

    # ---------------- code reader
    @staticmethod
    def line_dur(s):
        tr = s.strip()
        return 0.2 + len(tr) * 0.007 if tr else 0.06

    def enter_line(self, i):
        self.li, self.line_t = i, 0.0
        if i < len(self.src):
            m = re.search(r'phase\("(\w+)"\)', self.src[i])
            if m:
                self.phases.setdefault(m.group(1), self.t)
                self.hold = HOLD.get(m.group(1), 1.0)

    def step_reading(self, dt):
        if self.li < 0:
            self.enter_line(0)
        left = dt
        while self.li < len(self.src) and left > 0:
            if self.hold > 0:
                u = min(self.hold, left)
                self.hold -= u
                left -= u
                continue
            need = self.line_dur(self.src[self.li]) - self.line_t
            if left < need:
                self.line_t += left
                return
            left -= need
            self.enter_line(self.li + 1)

    # ---------------- rendering
    def glyph(self, c, col):
        key = (c, col[0] >> 2, col[1] >> 2, col[2] >> 2)
        surf = self.glyphs.get(key)
        if surf is None:
            surf = (self.kfont if is_wide(c) else self.font).render(c, True, col)
            self.glyphs[key] = surf
        return surf

    def glow(self, col):
        key = (col[0] >> 4, col[1] >> 4, col[2] >> 4)
        surf = self.glows.get(key)
        if surf is None:
            size = CH * 2
            surf = pygame.Surface((size, size))
            surf.fill((0, 0, 0))
            for rr in range(size // 2, 0, -1):
                k = (1 - rr / (size / 2)) ** 2 * 0.55
                pygame.draw.circle(surf, (int(col[0] * k), int(col[1] * k), int(col[2] * k)), (size // 2, size // 2), rr)
            self.glows[key] = surf
        return surf

    def paint_scene(self):
        scr = self.screen
        scr.fill(BG, (0, 0, SCENE_W, SCENE_H))
        letters = 0
        for i in range(N):  # glow halos first (additive)
            if self.gglow[i] and self.gc[i]:
                scr.blit(self.glow(self.gcol[i]), ((i % COLS) * CW + CW // 2 - CH, (i // COLS) * CH + CH // 2 - CH),
                         special_flags=pygame.BLEND_ADD)
        for i in range(N):
            c = self.gc[i]
            if not c or c == WIDE_PAD or c == BLANK:
                continue
            letters += 1
            s = self.glyph(c, self.gcol[i])
            cell_w = CW * 2 if is_wide(c) else CW
            scr.blit(s, ((i % COLS) * CW + (cell_w - s.get_width()) // 2, (i // COLS) * CH + (CH - s.get_height()) // 2))
        return letters

    def paint_hud(self, letters, fps):
        dim, gold, green = (92, 106, 133), GOLD, (87, 214, 141)
        a = self.title_font.render("ASCII XMAS", True, gold)
        b = self.title_font.render(" × ", True, dim)
        c = self.title_font.render("NANA", True, (205, 214, 232))
        self.screen.blit(a, (8 * S, 5 * S))
        self.screen.blit(b, (8 * S + a.get_width(), 5 * S))
        self.screen.blit(c, (8 * S + a.get_width() + b.get_width(), 5 * S))
        deg = math.degrees(self.rot) % 360
        self.screen.blit(self.hud_font.render(f"rotation {deg:5.1f}° · lights {self.lit} · letters {letters:,}", True, dim), (8 * S, SCENE_H - 15 * S))
        clk = self.hud_font.render(f"● t {self.t:5.2f}s", True, gold)
        self.screen.blit(clk, (SCENE_W - clk.get_width() - 8 * S, 6 * S))
        y0 = SCENE_H
        pygame.draw.rect(self.screen, (14, 19, 32), (0, y0, W, BAR_H))
        pygame.draw.line(self.screen, (27, 35, 54), (0, y0), (W, y0), S)
        self.screen.blit(self.code_font.render("christmas_tree.py", True, (205, 214, 232)), (10 * S, y0 + 5 * S))
        done = self.li >= len(self.src)
        state = "|| paused" if self.paused else f"{'● done' if done else '● running'} · {fps:.0f} fps"
        if self.speed == 2:
            state += " · 2x"
        st = self.code_font.render(state, True, green if done and not self.paused else gold)
        self.screen.blit(st, (W - st.get_width() - 10 * S, y0 + 5 * S))

    KW = re.compile(r"^(for|in|while|True|False|None|def|return|import|from|if|else|lambda)$")
    TOK = re.compile(r'(#.*$)|("[^"]*"?)|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]\w*)(\s*\()?|(\s+|.)')

    def code_line(self, text, x, y, dim):
        def mix(col):
            if not dim:
                return col
            return tuple(int(14 + (v - 14) * dim) for v in col)

        for m in self.TOK.finditer(text):
            com, st, num, ident, call, other = m.groups()
            if ident:
                if ident == "phase":
                    col = GOLD
                elif self.KW.match(ident):
                    col = (199, 146, 234)
                elif call:
                    col = (130, 170, 255)
                else:
                    col = (205, 214, 232)
                parts = [(ident, col)] + ([(call, (205, 214, 232))] if call else [])
            elif com:
                parts = [(com, (92, 106, 133))]
            elif st:
                parts = [(st, (195, 232, 141))]
            elif num:
                parts = [(num, (247, 140, 108))]
            else:
                parts = [(other, (205, 214, 232))]
            for s, col in parts:
                f = self.code_kfont if any(is_wide(ch) for ch in s) else self.code_font
                surf = f.render(s, True, mix(col))
                self.screen.blit(surf, (x, y))
                x += surf.get_width()

    def paint_code(self):
        """the full script is visible; a highlight reads it one line at a time"""
        y0 = SCENE_H + BAR_H
        pygame.draw.rect(self.screen, (14, 19, 32), (0, y0, W, CODE_H))
        lh = 17 * S
        visible = CODE_H // lh
        cur = max(0, min(self.li, len(self.src) - 1))
        first = max(0, min(cur - int(visible * 0.4), len(self.src) - visible))
        for row in range(visible):
            idx = first + row
            if idx >= len(self.src):
                break
            y = y0 + 4 * S + row * lh
            active = idx == self.li
            if active:
                pygame.draw.rect(self.screen, (29, 39, 66), (0, y - S, W, lh))
                pygame.draw.rect(self.screen, GOLD, (0, y - S, 3 * S, lh))
            dim = None if active else (0.8 if idx < self.li else 0.38)
            self.screen.blit(self.code_font.render(f"{idx + 1:3d}", True, GOLD if active else (52, 64, 90)), (8 * S, y))
            self.code_line(self.src[idx], 50 * S, y, dim)

    # ---------------- frame
    def update(self, raw):
        dt = 0 if self.paused else raw * self.speed
        self.t += dt
        self.step_reading(dt)
        self.update_rotation(dt)
        self.clear()
        self.draw_sky()
        self.draw_snow(dt, False)
        self.draw_ground()
        self.draw_tree()
        self.draw_tinsel()
        self.draw_baubles()
        self.draw_gifts()
        self.draw_star()
        self.draw_snow(dt, True)
        self.draw_message()

    def render(self, fps):
        letters = self.paint_scene()
        self.paint_hud(letters, fps)
        self.paint_code()

    def screenshot(self, path):
        pygame.image.save(self.screen, path)
        print("saved", path)

    def export_video(self, path, fps=30):
        """render the whole show offline and encode a 1080x1920 (9:16) MP4 with ffmpeg"""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            sys.exit("ffmpeg not found. Install it (e.g. `winget install Gyan.FFmpeg`) and try again.")
        cmd = [ffmpeg, "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
               "-vf", "scale=1080:-2:flags=lanczos,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x05070d",
               "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
               "-movflags", "+faststart", path]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        dt, n = 1 / fps, 0
        tail = TURN + 6.5  # keep filming this long after the surprise starts
        while not ("surprise" in self.phases and self.age("surprise") >= tail):
            self.update(dt)
            self.render(fps)
            proc.stdin.write(pygame.image.tostring(self.screen, "RGB"))
            n += 1
            if n % (fps * 5) == 0:
                print(f"  {n / fps:5.1f}s rendered", flush=True)
        proc.stdin.close()
        proc.wait()
        print(f"saved {path}  ({n} frames, {n / fps:.1f}s)")

    def run(self, shot_at=None):
        if shot_at is not None:  # headless: step the timeline at 30 fps without drawing, save one frame
            while self.t < shot_at:
                dt = 1 / 30
                self.t += dt
                self.step_reading(dt)
                self.update_rotation(dt)
            self.update(0)
            self.render(30)
            self.screenshot(os.path.join(os.path.dirname(os.path.abspath(__file__)), "christmas_tree.png"))
            return
        while True:
            raw = min(0.05, self.clock.tick(30) / 1000)
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                    return
                if e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_SPACE:
                        self.paused = not self.paused
                    elif e.key == pygame.K_r:
                        self.restart()
                    elif e.key == pygame.K_2:
                        self.speed = 1 if self.speed == 2 else 2
                    elif e.key == pygame.K_s:
                        self.screenshot(f"christmas_tree_{int(self.t * 100):06d}.png")
            self.update(raw)
            self.render(self.clock.get_fps())
            pygame.display.flip()


def main():
    shot = _arg("--shot")
    video = _arg("--video")
    if shot is not None or video is not None:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # no window needed
    app = App()
    if video:
        app.export_video(video)
    else:
        app.run(float(shot) if shot is not None else None)
    pygame.quit()


if __name__ == "__main__":
    main()
