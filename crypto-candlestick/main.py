#!/usr/bin/env python3
"""Crypto candlestick viewer.

Auto-cycles through symbols, pulling real hourly OHLC from Binance's public
data API (no key needed); falls back to synthetic data when offline. Shows the
price, window change %, a scaled candlestick chart with price gridlines, and a
symbol counter. Adapted from the Sipeed coin demo. Pure animation; exit with
the host's left-edge gesture.
"""

import json
import random
import urllib.request

from appbase import DOWN as SWIPE_DOWN
from appbase import UP as SWIPE_UP
from appbase import WHITE, app, rgb565

BG = rgb565(10, 12, 22)
UP = rgb565(0, 230, 120)
DOWN = rgb565(255, 80, 80)
GRID = rgb565(42, 46, 64)
DIM = rgb565(150, 150, 165)
DIM = rgb565(150, 150, 165)

SYMBOLS = ["BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "LTC"]
HOST = "data-api.binance.vision"
SWITCH = 1.0
LIMIT = 36


@app()
def main(ctx):
    fb = ctx.fb
    n = len(SYMBOLS)
    cache = {}
    prefetch_all(fb, cache)  # fetch everything once, then run from cache

    st = {"idx": 0, "since": 0.0}

    def show():
        ohlc, live = cache[SYMBOLS[st["idx"]]]
        draw(fb, SYMBOLS[st["idx"]], st["idx"], ohlc, live)
        st["since"] = 0.0

    def page(step):
        st["idx"] = (st["idx"] + step) % n
        show()

    def on_swipe(kind, _x, _y):
        # swipe up -> next symbol, down -> previous (resets the auto timer)
        if kind == SWIPE_UP:
            page(1)
        elif kind == SWIPE_DOWN:
            page(-1)

    def tick(dt):
        st["since"] += dt
        if st["since"] >= SWITCH:  # auto carousel
            page(1)

    show()
    ctx.run(tick, fps=20, on_swipe=on_swipe)


def fetch(sym):
    url = ("https://%s/api/v3/klines?symbol=%sUSDT&interval=1h&limit=%d"
           % (HOST, sym, LIMIT))
    req = urllib.request.Request(url, headers={"User-Agent": "nanokvm-go"})
    with urllib.request.urlopen(req, timeout=6) as r:
        rows = json.loads(r.read().decode())
    ohlc = [(float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in rows]
    if not ohlc:
        raise ValueError("empty")
    return ohlc, True


def synth(sym):
    price = random.uniform(20, 60000)
    ohlc = []
    for _ in range(LIMIT):
        o = price
        c = max(0.01, o * (1 + random.gauss(0, 0.012)))
        hi = max(o, c) * (1 + abs(random.gauss(0, 0.006)))
        lo = min(o, c) * (1 - abs(random.gauss(0, 0.006)))
        ohlc.append((o, hi, lo, c))
        price = c
    return ohlc, False


def prefetch_all(fb, cache):
    """Fetch every symbol once at startup and cache it, showing progress.
    Falls back to synthetic data per symbol on failure."""
    n = len(SYMBOLS)
    for i, sym in enumerate(SYMBOLS):
        w, h = fb.width, fb.height
        fb.clear(BG)
        fb.text_center(w // 2, h // 2 - 20, "LOADING", DIM, 2)
        fb.text_center(w // 2, h // 2 + 8, "%s  %d/%d" % (sym, i + 1, n),
                       WHITE, 2)
        # simple progress bar
        bw = w - 80
        fb.fill_rect(40, h // 2 + 36, bw, 6, GRID)
        fb.fill_rect(40, h // 2 + 36, bw * (i + 1) // n, 6, UP)
        fb.flush()
        try:
            cache[sym] = fetch(sym)
        except Exception:
            cache[sym] = synth(sym)


def money(p):
    if p >= 1000:
        return "%.0f" % p
    if p >= 1:
        return "%.2f" % p
    return "%.4f" % p


def draw(fb, sym, idx, ohlc, live):
    fb.clear(BG)
    w, h = fb.width, fb.height
    # margin avoids the dead strip; corners are rounded, so keep content
    # (esp. the title) well clear of the top-left/right arcs.
    margin = 22
    top, bottom = 58, h - 22
    left = margin + 50
    right = w - 10
    ph = bottom - top

    his = [c[1] for c in ohlc]
    los = [c[2] for c in ohlc]
    hi, lo = max(his), min(los)
    rng = (hi - lo) or (hi * 0.1 or 1.0)
    hi += rng * 0.08
    lo -= rng * 0.08
    rng = hi - lo

    def ymap(p):
        return int(bottom - (p - lo) / rng * ph)

    # header (title pushed right of the rounded top-left corner)
    fb.draw_text(margin + 22, 6, "%s/USD" % sym, WHITE, 2)
    cnt = "%d/%d" % (idx + 1, len(SYMBOLS))
    fb.draw_text(right - fb.text_width(cnt, 1), 6, cnt, DIM, 1)
    last = ohlc[-1][3]
    first = ohlc[0][0]
    chg = (last - first) / first * 100 if first else 0.0
    col = UP if last >= first else DOWN
    ptxt = "$" + money(last)
    fb.draw_text(right - fb.text_width(ptxt, 2), 24, ptxt, col, 2)
    ctxt = ("%s %.1f%%" % ("UP" if chg >= 0 else "DN", abs(chg)))
    fb.draw_text(right - fb.text_width(ctxt, 1), 44, ctxt, col, 1)

    # price gridlines + labels
    for i in range(4):
        val = lo + rng * i / 3
        y = bottom - ph * i // 3
        fb.fill_rect(left, y, right - left, 1, GRID)
        fb.draw_text(margin, y - 3, money(val), DIM, 1)

    # candles
    n = len(ohlc)
    slot = max(2, (right - left) // n)
    bw = max(1, slot - 1)
    x = left
    for (o, ch, cl, cc) in ohlc:
        c = UP if cc >= o else DOWN
        cx = x + slot // 2
        fb.draw_vline(cx, ymap(ch), ymap(cl), c)
        yo, yc = ymap(o), ymap(cc)
        fb.fill_rect(x, min(yo, yc), bw, max(1, abs(yc - yo)), c)
        x += slot

    foot = ("BINANCE 1H" if live else "DEMO DATA")
    fb.draw_text(margin, h - 17, foot, DIM, 1)

    # page indicator dots (one per symbol; current highlighted)
    n = len(SYMBOLS)
    ds, gap = 5, 7
    x0 = (w - (n * ds + (n - 1) * gap)) // 2
    dy = h - 8
    for i in range(n):
        c = WHITE if i == idx else GRID
        fb.fill_rect(x0 + i * (ds + gap), dy, ds, ds, c)
    fb.flush()


if __name__ == "__main__":
    main()
