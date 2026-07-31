#!/usr/bin/env python3
"""Pomodoro timer with touch setup.

Pick a duration (5 / 15 / 25 min) and tap START to begin the countdown; tap
anywhere during the countdown to cancel back to selection. When it reaches
zero it returns to the picker. Exit with the host's left-edge gesture.

Reference app for the AppContext helpers: Rect hit-testing, ctx.taps(),
ctx.button() drawn touch targets.
"""

import time

from appbase import GRAY, WHITE, Rect, app, rgb565

BG = rgb565(12, 12, 16)
ACCENT = rgb565(255, 120, 90)
SEL = rgb565(60, 210, 120)
BTN = rgb565(44, 44, 54)
BAR_BG = rgb565(40, 40, 48)

DURATIONS = [5, 15, 25]


def layout(ctx):
    """Return ([(minutes, Rect)], start Rect) for the picker screen."""
    w = ctx.width
    bw, bh, gap = 64, 56, 16
    x0 = (w - (3 * bw + 2 * gap)) // 2
    nums = [(d, Rect(x0 + i * (bw + gap), 96, bw, bh))
            for i, d in enumerate(DURATIONS)]
    sw, sh = 140, 48
    return nums, Rect((w - sw) // 2, 172, sw, sh)


def draw_select(ctx, sel):
    fb = ctx.fb
    fb.clear(BG)
    fb.text_center(ctx.width // 2, 30, "POMODORO", ACCENT, 3)
    nums, start = layout(ctx)
    for d, r in nums:
        ctx.button(r, str(d), SEL if d == sel else BTN, scale=3)
    ctx.button(start, "START", ACCENT)
    fb.text_center(ctx.width // 2, ctx.height - 16, "MINUTES", GRAY, 1)
    fb.flush()


def draw_run(ctx, remaining, total, first):
    fb = ctx.fb
    w, h = ctx.width, ctx.height
    if first:
        fb.clear(BG)
        fb.fill_rect(12, h - 22, w - 24, 10, BAR_BG)
    txt = "%02d:%02d" % (remaining // 60, remaining % 60)
    scale = 6
    while fb.text_width(txt, scale) > w - 8 and scale > 1:
        scale -= 1
    tw, th = fb.text_width(txt, scale), 8 * scale
    tx, ty = (w - tw) // 2, (h - th) // 2
    fb.fill_rect(tx, ty, tw, th, BG)
    fb.draw_text(tx, ty, txt, WHITE, scale)
    done = 0.0 if total == 0 else (total - remaining) / total
    fb.fill_rect(12, h - 22, int((w - 24) * done), 10, SEL)
    fb.flush()


@app()
def main(ctx):
    state = "select"
    sel = 25
    total = 0
    end = 0.0
    last_sec = None
    draw_select(ctx, sel)
    while True:
        taps = ctx.taps()
        if state == "select":
            nums, start = layout(ctx)
            for px, py in taps:
                hit = next((d for d, r in nums if r.contains(px, py)), None)
                if hit is not None:
                    sel = hit
                    draw_select(ctx, sel)
                elif start.contains(px, py):
                    total = sel * 60
                    end = time.monotonic() + total
                    last_sec = None
                    state = "run"
            time.sleep(0.05)
        else:
            if taps:  # tap cancels back to the picker
                state = "select"
                draw_select(ctx, sel)
                time.sleep(0.05)
                continue
            remaining = max(0, int(round(end - time.monotonic())))
            if remaining != last_sec:
                draw_run(ctx, remaining, total, last_sec is None)
                last_sec = remaining
            if remaining <= 0:
                time.sleep(0.8)
                state = "select"
                draw_select(ctx, sel)
                last_sec = None
            time.sleep(0.1)


if __name__ == "__main__":
    main()
