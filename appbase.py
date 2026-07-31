#!/usr/bin/env python3
"""AppBase — standard framebuffer App SDK for kvm_ui sub-apps.

Pure stdlib (mmap/struct/fcntl). Opens /dev/fb0, probes geometry via fbdev
ioctls (falling back to 284x240 RGB565), and offers pixel/rect/line/text
drawing plus an embedded 8x8 bitmap font.

This module is the canonical base for sub-apps. Each App keeps metadata in
app.json and drives its UI through the AppContext's ctx.run() loop:

    from appbase import app, rgb565

    @app()
    def main(ctx):
        def tick(dt):
            ctx.fb.clear(0)
            ctx.fb.text_center(ctx.width // 2, ctx.height // 2,
                               "Hello", 0xFFFF)

        ctx.run(tick, fps=20, on_tap=lambda x, y: None)

Two env knobs, both optional:
  APPBASE_FB_DEVICE   framebuffer device (default /dev/fb0)
  APPBASE_FB_ROTATE   0/90/180/270 logical rotation applied at the pixel-write path,
                      so screen orientation can be calibrated on-device without code
                      changes. Default 0.

Apps live in one directory per App under /etc/kvm/apps. Each directory contains
main.py, app.json, and optional resources. The shared appbase.py and
appbase.pyi remain in /etc/kvm/apps.
"""

from __future__ import annotations

import dataclasses
import fcntl
import json
import mmap
import os
import re
import select
import struct
import time
from types import MappingProxyType
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

FBIOGET_VSCREENINFO = 0x4600
FBIOGET_FSCREENINFO = 0x4602

FALLBACK_W = 284
FALLBACK_H = 240
FALLBACK_BPP = 16


def rgb565(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)


def _probe_screeninfo(fd):
    """Return (xres, yres, bpp, line_length) via fbdev ioctls, with fallback."""
    try:
        vinfo = fcntl.ioctl(fd, FBIOGET_VSCREENINFO, b"\x00" * 160)
        xres, yres = struct.unpack_from("II", vinfo, 0)
        bpp = struct.unpack_from("I", vinfo, 24)[0]
        finfo = fcntl.ioctl(fd, FBIOGET_FSCREENINFO, b"\x00" * 80)
        line_length = struct.unpack_from("I", finfo, 48)[0]
        if not (0 < xres <= 4096 and 0 < yres <= 4096 and bpp in (16, 24, 32)):
            raise ValueError("implausible vinfo")
        if not (0 < line_length <= xres * (bpp // 8) * 4):
            line_length = xres * (bpp // 8)
        return xres, yres, bpp, line_length
    except Exception:
        return (FALLBACK_W, FALLBACK_H, FALLBACK_BPP,
                FALLBACK_W * (FALLBACK_BPP // 8))

def _env_rotate():
    """Read rotation from APPBASE_FB_ROTATE."""
    value = os.environ.get("APPBASE_FB_ROTATE")
    if value:
        try:
            return int(value)
        except ValueError:
            pass
    return 0



class FrameBuffer:
    """RGB565 framebuffer with optional logical rotation."""

    def __init__(self, device=None, rotate=None):
        self.device = device or os.environ.get("APPBASE_FB_DEVICE", "/dev/fb0")
        if rotate is None:
            rotate = _env_rotate()
        self.rotate = rotate % 360
        self._fd = os.open(self.device, os.O_RDWR)
        self.phys_w, self.phys_h, self.bpp, self.stride = _probe_screeninfo(
            self._fd)
        # stride is bytes per physical row; phys_w from ioctl may differ from
        # stride/2, so trust the stride for pixel addressing.
        self.row_px = self.stride // 2
        self._size = self.stride * self.phys_h
        self._mm = mmap.mmap(self._fd, self._size, mmap.MAP_SHARED,
                             mmap.PROT_READ | mmap.PROT_WRITE)
        # Off-screen back buffer: draw the whole frame here, then flush() copies
        # it to the framebuffer in one shot so the panel never shows a partial
        # frame (avoids flicker/ghosting from incremental writes).
        self._buf = bytearray(self._size)
        if self.rotate in (90, 270):
            self.width, self.height = self.phys_h, self.phys_w
        else:
            self.width, self.height = self.phys_w, self.phys_h

    # -- lifecycle --
    def close(self):
        try:
            self._mm.close()
        finally:
            os.close(self._fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- coordinate transform (logical -> physical) --
    def _phys(self, x, y):
        r = self.rotate
        if r == 90:
            return self.phys_w - 1 - y, x
        if r == 180:
            return self.phys_w - 1 - x, self.phys_h - 1 - y
        if r == 270:
            return y, self.phys_h - 1 - x
        return x, y

    # -- presentation --
    def flush(self):
        """Copy the back buffer to the framebuffer in one operation."""
        self._mm[:] = self._buf

    # -- drawing (all targets the back buffer; call flush() to present) --
    def put_pixel(self, x, y, color):
        if x < 0 or y < 0 or x >= self.width or y >= self.height:
            return
        px, py = self._phys(x, y)
        off = py * self.stride + px * 2
        self._buf[off:off + 2] = struct.pack("<H", color)

    def fill_rect(self, x, y, w, h, color):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.width, x + w)
        y1 = min(self.height, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        packed = struct.pack("<H", color)
        r = self.rotate
        # For each rotation a filled rect maps to contiguous physical-row runs
        # (iterating the right axis), so we write whole spans instead of pixels.
        if r == 90:
            run = packed * (y1 - y0)
            base = (self.phys_w - y1) * 2
            for vx in range(x0, x1):
                off = vx * self.stride + base
                self._buf[off:off + len(run)] = run
        elif r == 270:
            run = packed * (y1 - y0)
            base = y0 * 2
            for vx in range(x0, x1):
                off = (self.phys_h - 1 - vx) * self.stride + base
                self._buf[off:off + len(run)] = run
        elif r == 180:
            run = packed * (x1 - x0)
            base = (self.phys_w - x1) * 2
            for vy in range(y0, y1):
                off = (self.phys_h - 1 - vy) * self.stride + base
                self._buf[off:off + len(run)] = run
        else:  # 0
            run = packed * (x1 - x0)
            for vy in range(y0, y1):
                off = vy * self.stride + x0 * 2
                self._buf[off:off + len(run)] = run

    def clear(self, color=0):
        # Orientation-independent: fill the whole physical buffer.
        row = struct.pack("<H", color) * self.row_px
        for yy in range(self.phys_h):
            off = yy * self.stride
            self._buf[off:off + len(row)] = row

    def draw_line(self, x0, y0, x1, y1, color):
        x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.put_pixel(x0, y0, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def draw_vline(self, x, y0, y1, color):
        if y1 < y0:
            y0, y1 = y1, y0
        self.fill_rect(x, y0, 1, y1 - y0 + 1, color)

    def draw_text(self, x, y, text, color, scale=1):
        cx = x
        for ch in text:
            glyph = _FONT.get(ch)
            if glyph is None:
                glyph = _FONT.get(ch.upper())
            if glyph is not None:
                for row in range(8):
                    bits = glyph[row]
                    for col in range(8):
                        if bits & (1 << col):
                            self.fill_rect(cx + col * scale,
                                           y + row * scale, scale, scale,
                                           color)
            cx += 8 * scale

    def text_width(self, text, scale=1):
        return len(text) * 8 * scale

    def draw_sprite(self, x, y, rows, palette, scale=1):
        """Blit pixel art. `rows` is a list of equal-length strings; each char
        maps to an rgb565 color in `palette` (missing/space = transparent)."""
        for j, row in enumerate(rows):
            run_c = None
            run_i = 0
            for i, ch in enumerate(row + "\0"):
                c = palette.get(ch) if ch != "\0" else None
                if c == run_c:
                    continue
                if run_c is not None:
                    self.fill_rect(x + run_i * scale, y + j * scale,
                                   (i - run_i) * scale, scale, run_c)
                run_c = c
                run_i = i

    def text_center(self, cx, y, text, color, scale=1):
        self.draw_text(cx - self.text_width(text, scale) // 2, y, text,
                       color, scale)

    # Map a raw evdev (rx, ry) to this canvas's visual coords (inverse of the
    # rotation used for drawing), so a tap lands where the user sees it.
    def touch_to_visual(self, rx, ry):
        r = self.rotate
        if r == 90:
            return ry, self.phys_w - 1 - rx
        if r == 270:
            return self.phys_h - 1 - ry, rx
        if r == 180:
            return self.phys_w - 1 - rx, self.phys_h - 1 - ry
        return rx, ry


class TouchReader:
    """Reads /dev/input/event0 directly (sub-apps don't get host-forwarded
    input yet) and reports gestures mapped to the canvas's visual coordinates.

    poll() returns a list of (kind, x, y) where kind is "tap", "up", "down",
    "left" or "right" (swipe direction), and (x, y) is the touch-down point.

    The host reads the same device for its exit gesture; evdev delivers a copy
    to every open fd, so both coexist. While the host freezes the app for the
    exit gesture (SIGSTOP), this simply stops polling until resumed.
    """

    _EV_SYN, _EV_KEY, _EV_ABS = 0x00, 0x01, 0x03
    _SYN_REPORT = 0x00
    _BTN_TOUCH = 0x14A
    _ABS_X, _ABS_Y = 0x00, 0x01
    _ABS_MT_X, _ABS_MT_Y = 0x35, 0x36
    _FMT = "llHHi"
    _SZ = struct.calcsize("llHHi")
    _TAP_MAX = 14   # movement (px) still counted as a tap
    _SWIPE_MIN = 24  # movement (px) to register a swipe

    def __init__(self, fb, device=None):
        self.fb = fb
        dev = device or os.environ.get("APPBASE_TOUCH_DEVICE", "/dev/input/event0")
        try:
            self._fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            self._fd = -1
        self._rx = 0
        self._ry = 0
        self._pressed = False
        self._want_down = False
        self._dx = 0
        self._dy = 0

    def close(self):
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def poll(self):
        """Return a list of (kind, x, y) gestures since the last call."""
        events = []
        if self._fd < 0:
            return events
        while True:
            r, _, _ = select.select([self._fd], [], [], 0)
            if not r:
                break
            try:
                data = os.read(self._fd, self._SZ * 64)
            except OSError:
                break
            if not data:
                break
            for off in range(0, len(data) - self._SZ + 1, self._SZ):
                _, _, et, code, val = struct.unpack_from(self._FMT, data, off)
                if et == self._EV_ABS:
                    if code in (self._ABS_X, self._ABS_MT_X):
                        self._rx = val
                    elif code in (self._ABS_Y, self._ABS_MT_Y):
                        self._ry = val
                elif et == self._EV_KEY and code == self._BTN_TOUCH:
                    now = bool(val)
                    if now and not self._pressed:
                        self._want_down = True  # set down point at next SYN
                    elif (not now) and self._pressed:
                        ex, ey = self.fb.touch_to_visual(self._rx, self._ry)
                        dx, dy = ex - self._dx, ey - self._dy
                        adx, ady = abs(dx), abs(dy)
                        if adx < self._TAP_MAX and ady < self._TAP_MAX:
                            events.append(("tap", self._dx, self._dy))
                        elif ady >= adx and ady >= self._SWIPE_MIN:
                            events.append(("down" if dy > 0 else "up",
                                           self._dx, self._dy))
                        elif adx >= self._SWIPE_MIN:
                            events.append(("right" if dx > 0 else "left",
                                           self._dx, self._dy))
                    self._pressed = now
                elif et == self._EV_SYN and code == self._SYN_REPORT:
                    if self._want_down:
                        self._dx, self._dy = self.fb.touch_to_visual(
                            self._rx, self._ry)
                        self._want_down = False
        return events




# ---------------------------------------------------------------------------
# App metadata and lifecycle
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class AppInfo:
    """Declarative metadata loaded from an App's app.json.

    Fields
    ------
    app_id: stable reverse-domain package name matching the App directory.
    name: display name of the app.
    creator: author / team.
    create_time: creation date (free-form string, e.g. ISO 8601).
    version: semantic version string.
    desc: short description.
    category: optional grouping hint.
    icon: optional icon name / identifier.
    """
    app_id: str
    name: str
    creator: str
    create_time: str
    version: str
    desc: str = ""
    category: str = ""
    icon: str = ""

    def as_dict(self) -> Dict[str, str]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle with hit-testing, for touch targets."""
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2


@dataclasses.dataclass
class AppContext:
    """Runtime context handed to an @app-decorated main function.

    Holds the framebuffer and the touch reader, and exposes commonly used
    convenience methods so app code can focus on content rather than setup.
    """
    fb: FrameBuffer
    touch: TouchReader
    env: Mapping[str, str] = dataclasses.field(
        default_factory=lambda: MappingProxyType({}))

    @property
    def width(self) -> int:
        return self.fb.width

    @property
    def height(self) -> int:
        return self.fb.height

    def poll(self) -> List[Tuple[str, int, int]]:
        """Return pending touch gestures since the last call."""
        return self.touch.poll()

    def flush(self) -> None:
        """Present the back buffer to the panel."""
        self.fb.flush()

    def taps(self) -> List[Tuple[int, int]]:
        """Return only tap positions since the last poll (drops swipes)."""
        return [(x, y) for kind, x, y in self.poll() if kind == TAP]

    def button(self, rect: Rect, label: str, bg: int, fg: int = 0xFFFF,
               scale: int = 2) -> Rect:
        """Draw a filled, labeled touch target and return its Rect."""
        self.fb.fill_rect(rect.x, rect.y, rect.w, rect.h, bg)
        self.fb.text_center(rect.cx, rect.cy - 4 * scale, label, fg, scale)
        return rect

    def run(self, tick: Callable[..., Any], fps: float = 20.0,
            on_tap: Optional[Callable[[int, int], Any]] = None,
            on_swipe: Optional[Callable[[str, int, int], Any]] = None) -> None:
        """Paced main loop: dispatch gestures, call tick(dt), auto-flush.

        tick(dt) receives the elapsed seconds since the previous frame and is
        called once per frame; returning False stops the loop. Gestures are
        dispatched first: taps to on_tap(x, y), swipes to on_swipe(kind, x, y).
        The frame is flushed after tick, and the loop sleeps to hold `fps`.
        KeyboardInterrupt (host terminating the app) exits quietly.
        """
        period = 1.0 / fps if fps > 0 else 0.0
        last = time.monotonic()
        try:
            while True:
                for kind, x, y in self.poll():
                    if kind == TAP:
                        if on_tap is not None:
                            on_tap(x, y)
                    elif on_swipe is not None:
                        on_swipe(kind, x, y)
                now = time.monotonic()
                dt, last = now - last, now
                if tick(dt) is False:
                    return
                self.flush()
                spend = time.monotonic() - now
                if period > spend:
                    time.sleep(period - spend)
        except KeyboardInterrupt:
            pass


def app() -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Load App metadata and wrap the main function with lifecycle setup.

    Metadata is read from app.json beside the decorated module.

    The decorated function receives an AppContext::

        @app()
        def main(ctx: AppContext) -> None:
            ctx.fb.clear(0)
            ctx.fb.text_center(ctx.width // 2, ctx.height // 2, "Hi", 0xFFFF)
            ctx.flush()
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        module_file = func.__globals__.get("__file__", "")
        manifest_path = os.path.join(os.path.dirname(
            os.path.abspath(module_file)), "app.json")
        manifest: Dict[str, Any] = {}
        if os.path.isfile(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as stream:
                loaded = json.load(stream)
            if not isinstance(loaded, dict):
                raise ValueError("app.json must contain a JSON object")
            manifest = loaded

        def metadata(field: str) -> str:
            value = manifest.get(field, "")
            if not isinstance(value, str):
                raise ValueError("app.json field %s must be a string" % field)
            return value

        info = AppInfo(
            metadata("app_id"),
            metadata("name"),
            metadata("creator"),
            metadata("create_time"),
            metadata("version"),
            metadata("desc"),
            metadata("category"),
            metadata("icon"),
        )
        for required in ("app_id", "name", "creator", "create_time", "version"):
            if not getattr(info, required):
                raise ValueError("missing required App metadata: %s" % required)
        if re.fullmatch(r"[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*){2,}", info.app_id) is None:
            raise ValueError("invalid reverse-domain app_id: %s" % info.app_id)
        directory = os.path.basename(os.path.dirname(os.path.abspath(module_file)))
        if info.app_id.rsplit(".", 1)[-1] != directory.replace("-", "_"):
            raise ValueError("app_id does not match App directory: %s" % directory)

        environment: Dict[str, str] = {}
        env_specs = manifest.get("env", {})
        if not isinstance(env_specs, dict):
            raise ValueError("app.json field env must be an object")
        for name, spec in env_specs.items():
            if not isinstance(name, str) or re.fullmatch(
                    r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
                raise ValueError("invalid App environment name: %s" % name)
            if not isinstance(spec, dict):
                raise ValueError("App environment spec must be an object: %s" % name)
            value = os.environ.get(name, spec.get("value", ""))
            if not value:
                value = spec.get("default", "")
            if not isinstance(value, str):
                raise ValueError("App environment value must be a string: %s" % name)
            if spec.get("required", False) and not value.strip():
                raise ValueError("required App environment is not configured: %s" % name)
            environment[name] = value
        readonly_environment = MappingProxyType(environment)

        def wrapper() -> Any:
            with FrameBuffer() as fb:
                touch = TouchReader(fb)
                ctx = AppContext(fb, touch, readonly_environment)
                try:
                    return func(ctx)
                except KeyboardInterrupt:
                    return None  # host terminated the app; exit quietly
                finally:
                    touch.close()

        wrapper.__app_info__ = info  # type: ignore[attr-defined]
        wrapper.__wrapped__ = func  # type: ignore[attr-defined]
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Gesture constants
# ---------------------------------------------------------------------------

TAP = "tap"
UP = "up"
DOWN = "down"
LEFT = "left"
RIGHT = "right"

# 8x8 bitmap font (subset of the public-domain font8x8_basic). Each glyph is 8
# bytes (top row first); within a byte bit 0 (LSB) is the leftmost pixel.
_FONT = {
    " ": [0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],
    "$": [0x18, 0x3E, 0x60, 0x3C, 0x06, 0x7C, 0x18, 0x00],
    "%": [0x00, 0x63, 0x66, 0x0C, 0x18, 0x33, 0x63, 0x00],
    "-": [0x00, 0x00, 0x00, 0x3F, 0x00, 0x00, 0x00, 0x00],
    ".": [0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x18, 0x00],
    "/": [0x00, 0x60, 0x30, 0x18, 0x0C, 0x06, 0x03, 0x00],
    ":": [0x00, 0x18, 0x18, 0x00, 0x00, 0x18, 0x18, 0x00],
    "0": [0x3E, 0x63, 0x73, 0x7B, 0x6F, 0x67, 0x3E, 0x00],
    "1": [0x0C, 0x0E, 0x0C, 0x0C, 0x0C, 0x0C, 0x3F, 0x00],
    "2": [0x1E, 0x33, 0x30, 0x1C, 0x06, 0x33, 0x3F, 0x00],
    "3": [0x1E, 0x33, 0x30, 0x1C, 0x30, 0x33, 0x1E, 0x00],
    "4": [0x38, 0x3C, 0x36, 0x33, 0x7F, 0x30, 0x78, 0x00],
    "5": [0x3F, 0x03, 0x1F, 0x30, 0x30, 0x33, 0x1E, 0x00],
    "6": [0x1C, 0x06, 0x03, 0x1F, 0x33, 0x33, 0x1E, 0x00],
    "7": [0x3F, 0x33, 0x30, 0x18, 0x0C, 0x0C, 0x0C, 0x00],
    "8": [0x1E, 0x33, 0x33, 0x1E, 0x33, 0x33, 0x1E, 0x00],
    "9": [0x1E, 0x33, 0x33, 0x3E, 0x30, 0x18, 0x0E, 0x00],
    "A": [0x0C, 0x1E, 0x33, 0x33, 0x3F, 0x33, 0x33, 0x00],
    "B": [0x3F, 0x66, 0x66, 0x3E, 0x66, 0x66, 0x3F, 0x00],
    "C": [0x3C, 0x66, 0x03, 0x03, 0x03, 0x66, 0x3C, 0x00],
    "D": [0x1F, 0x36, 0x66, 0x66, 0x66, 0x36, 0x1F, 0x00],
    "E": [0x7F, 0x46, 0x16, 0x1E, 0x16, 0x46, 0x7F, 0x00],
    "F": [0x7F, 0x46, 0x16, 0x1E, 0x16, 0x06, 0x0F, 0x00],
    "G": [0x3C, 0x66, 0x03, 0x03, 0x73, 0x66, 0x7C, 0x00],
    "H": [0x33, 0x33, 0x33, 0x3F, 0x33, 0x33, 0x33, 0x00],
    "I": [0x1E, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x1E, 0x00],
    "J": [0x78, 0x30, 0x30, 0x30, 0x33, 0x33, 0x1E, 0x00],
    "K": [0x67, 0x66, 0x36, 0x1E, 0x36, 0x66, 0x67, 0x00],
    "L": [0x0F, 0x06, 0x06, 0x06, 0x46, 0x66, 0x7F, 0x00],
    "M": [0x63, 0x77, 0x7F, 0x7F, 0x6B, 0x63, 0x63, 0x00],
    "N": [0x63, 0x67, 0x6F, 0x7B, 0x73, 0x63, 0x63, 0x00],
    "O": [0x1C, 0x36, 0x63, 0x63, 0x63, 0x36, 0x1C, 0x00],
    "P": [0x3F, 0x66, 0x66, 0x3E, 0x06, 0x06, 0x0F, 0x00],
    "Q": [0x1E, 0x33, 0x33, 0x33, 0x3B, 0x1E, 0x38, 0x00],
    "R": [0x3F, 0x66, 0x66, 0x3E, 0x36, 0x66, 0x67, 0x00],
    "S": [0x1E, 0x33, 0x07, 0x0E, 0x38, 0x33, 0x1E, 0x00],
    "T": [0x3F, 0x2D, 0x0C, 0x0C, 0x0C, 0x0C, 0x1E, 0x00],
    "U": [0x33, 0x33, 0x33, 0x33, 0x33, 0x33, 0x3F, 0x00],
    "V": [0x33, 0x33, 0x33, 0x33, 0x33, 0x1E, 0x0C, 0x00],
    "W": [0x63, 0x63, 0x63, 0x6B, 0x7F, 0x77, 0x63, 0x00],
    "X": [0x63, 0x63, 0x36, 0x1C, 0x1C, 0x36, 0x63, 0x00],
    "Y": [0x33, 0x33, 0x33, 0x1E, 0x0C, 0x0C, 0x1E, 0x00],
    "Z": [0x7F, 0x63, 0x31, 0x18, 0x4C, 0x66, 0x7F, 0x00],
}

# Handy RGB565 constants.
BLACK = rgb565(0, 0, 0)
WHITE = rgb565(255, 255, 255)
RED = rgb565(255, 40, 40)
GREEN = rgb565(40, 220, 90)
BLUE = rgb565(60, 120, 255)
YELLOW = rgb565(255, 200, 40)
GRAY = rgb565(120, 120, 120)
DKGRAY = rgb565(40, 40, 40)
ORANGE = rgb565(255, 140, 40)
CYAN = rgb565(40, 200, 220)
MAGENTA = rgb565(230, 60, 200)
NAVY = rgb565(10, 12, 22)
