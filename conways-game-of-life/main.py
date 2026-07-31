#!/usr/bin/env python3
"""Conway's Game of Life.

Cycles through classic patterns (random, glider, lightweight spaceship, pulsar,
Gosper glider gun, beacon) on a toroidal grid, with a live generation /
population / pattern readout. Adapted from the Sipeed conway demo. Tap the
screen to skip to the next pattern; exit with the host's left-edge gesture.

Reference app for the AppContext ctx.run() paced main loop.
"""

import random

from appbase import app, rgb565

BG = rgb565(8, 10, 20)
CELL = rgb565(0, 240, 130)
INFO = rgb565(200, 205, 220)

PATTERNS = ["RANDOM", "GLIDER", "SPACESHIP", "PULSAR", "GLIDER GUN", "BEACON"]

GLIDER = [[0, 1, 0], [0, 0, 1], [1, 1, 1]]
LWSS = [[0, 1, 1, 1, 1], [1, 0, 0, 0, 1], [0, 0, 0, 0, 1], [1, 0, 0, 1, 0]]
PULSAR = [
    [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 1, 0, 0],
]
# fmt: off
GUN = [
 [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0],
 [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0],
 [0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,1,1],
 [0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,1,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,1,1],
 [1,1,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
 [1,1,0,0,0,0,0,0,0,0,1,0,0,0,1,0,1,1,0,0,0,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0],
 [0,0,0,0,0,0,0,0,0,0,1,0,0,0,0,0,1,0,0,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0],
 [0,0,0,0,0,0,0,0,0,0,0,1,0,0,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
 [0,0,0,0,0,0,0,0,0,0,0,0,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0],
]
# fmt: on
BEACON = [[1, 1, 0, 0], [1, 1, 0, 0], [0, 0, 1, 1], [0, 0, 1, 1]]


@app()
def main(ctx):
    fb = ctx.fb
    w, h = fb.width, fb.height
    info_h = 16
    cell = 4
    cols = w // cell
    rows = (h - info_h) // cell
    ox = (w - cols * cell) // 2
    oy = info_h + (h - info_h - rows * cell) // 2
    life = Life(cols, rows)
    state = {"pi": 0}
    setup(life, PATTERNS[0])

    def next_pattern(_x=0, _y=0):
        state["pi"] = (state["pi"] + 1) % len(PATTERNS)
        setup(life, PATTERNS[state["pi"]])

    def tick(dt):
        fb.clear(BG)
        fb.draw_text(18, 4, "GEN %d  LIVE %d  %s" %
                     (life.gen, life.live(), PATTERNS[state["pi"]]), INFO, 1)
        g = life.g
        for y in range(rows):
            base = y * cols
            py = oy + y * cell
            for x in range(cols):
                if g[base + x]:
                    fb.fill_rect(ox + x * cell, py, cell - 1, cell - 1, CELL)
        life.step()
        if life.gen % 160 == 0:
            next_pattern()

    ctx.run(tick, fps=16, on_tap=next_pattern)


class Life:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.g = bytearray(w * h)
        self.gen = 0

    def randomize(self, d=0.2):
        self.g = bytearray(1 if random.random() < d else 0
                           for _ in range(self.w * self.h))

    def add(self, x, y, pat):
        for i, row in enumerate(pat):
            for j, c in enumerate(row):
                if c and 0 <= y + i < self.h and 0 <= x + j < self.w:
                    self.g[(y + i) * self.w + x + j] = 1

    def step(self):
        w, h, g = self.w, self.h, self.g
        n = bytearray(w * h)
        for y in range(h):
            yu = ((y - 1) % h) * w
            yd = ((y + 1) % h) * w
            yc = y * w
            for x in range(w):
                xl = (x - 1) % w
                xr = (x + 1) % w
                c = (g[yu + xl] + g[yu + x] + g[yu + xr] + g[yc + xl] +
                     g[yc + xr] + g[yd + xl] + g[yd + x] + g[yd + xr])
                n[yc + x] = 1 if (c == 3 or (g[yc + x] and c == 2)) else 0
        self.g = n
        self.gen += 1

    def live(self):
        return sum(self.g)


def setup(life, name):
    life.g = bytearray(life.w * life.h)
    life.gen = 0
    cx, cy = life.w // 2, life.h // 2
    if name == "RANDOM":
        life.randomize(0.2)
    elif name == "GLIDER":
        life.add(3, 3, GLIDER)
    elif name == "SPACESHIP":
        life.add(3, cy, LWSS)
    elif name == "PULSAR":
        life.add(cx - 6, cy - 6, PULSAR)
    elif name == "GLIDER GUN":
        life.add(2, 2, GUN)
    elif name == "BEACON":
        life.add(cx, cy, BEACON)


if __name__ == "__main__":
    main()
