# NanoKVM framebuffer App SDK (`appbase`)

[中文开发指南](README_zh.md)

`apps/appbase.py` is the shared standard library for Python Apps launched from the `kvm_ui` Apps page. Each App has its own directory containing `main.py`, `app.json`, and optional resources. Apps draw RGB565 frames directly to fbdev and read evdev touch input without embedding LVGL.

The implementation is `appbase.py`; the public type contract is `appbase.pyi`. Keep both synchronized when changing a public name, field, signature, or return type.

## Contents

- [Requirements](#requirements)
- [Discovery](#discovery)
- [Quick start](#quick-start)
- [Host and App lifecycle](#host-and-app-lifecycle)
- [Coordinates and the dead area](#coordinates-and-the-dead-area)
- [Touch and the host exit gesture](#touch-and-the-host-exit-gesture)
- [SDK reference](#sdk-reference)
- [Examples](#examples)
- [Environment variables](#environment-variables)
- [Deployment](#deployment)
- [Debug screenshots](#debug-screenshots)
- [Validation and troubleshooting](#validation-and-troubleshooting)

## Requirements

- A target device with a compatible fbdev, normally `/dev/fb0` in RGB565 mode.
- A readable evdev touch device, normally `/dev/input/event0`.
- Python 3 with the standard-library modules used by `appbase` (`mmap`, `fcntl`, `struct`, `select`, `os`, `time`, and typing support).
- `launcher.enabled=true` in [`kvm_ui.toml`](../configuration.md#launcher).
- App directories, plus shared `appbase.py` and `appbase.pyi`, in the configured `launcher.apps_dir`, default `/etc/kvm/apps`.

The host refuses to start an App session when touch is disabled or unavailable because it needs touch input for the reserved exit gesture.

## Discovery

The host scans direct child directories of `launcher.apps_dir` once during UI startup. A launchable entry must:

1. be a directory whose name does not start with `_`;
2. contain a regular `main.py` file;
3. contain a valid `app.json` JSON object;
4. provide a reverse-domain `app_id` matching the directory name;
5. provide a non-empty string `name` in `app.json`.

Use a lowercase directory name with words separated by hyphens, for example
`hello-world`. The directory name is the stable filesystem identifier; `name`
is the user-facing label.

Example layout:

```text
apps/
├── appbase.py
├── appbase.pyi
└── hello-world/
    ├── app.json
    ├── main.py
    └── icon.png          # optional resource
```

Example `app.json`:

```json
{
  "app_id": "com.example.hello_world",
  "name": "Hello",
  "creator": "Your Name",
  "create_time": "2026-07-01",
  "version": "1.0.0",
  "desc": "Minimal framebuffer App.",
  "category": "demo",
  "icon": "icon.png",
  "pre_script": "scripts/pre-install.sh",
  "post_script": "scripts/post-install.sh"
}
```

`app_id`, `name`, `creator`, `create_time`, and `version` are required by `@app()` at runtime. The reverse-domain `app_id` has at least three components and its final component equals the directory name with `-` replaced by `_`; official Apps use `com.sipeed.*`. `desc`, `category`, and `icon` are optional.

Upload and download ZIPs contain exactly one top-level App directory, with `app.json`, `main.py`, and optional resources inside it. Root-level files and multi-App ZIPs are rejected.

Deployment settings declared by `app.json.env` are injected by the Launcher
and exposed by `@app()` as the read-only `ctx.env` mapping. Apps must not use a
separate `.env` file.

Apps may declare optional `pre_script` and `post_script` paths. The Server runs
these App-relative scripts as root during installation and provides
`NANOKVM_APP_DIR`, `NANOKVM_APP_ID`, `NANOKVM_APP_PHASE`, and configured `env`
values. Scripts are limited to 15 minutes and 64 KiB of captured output. A
failed pre-script prevents installation; a failed post-script removes the new
App directory. Install Apps with scripts only from trusted sources.

The host rescans the Apps directory every 10 seconds. Adding, removing, or renaming an App, or changing its `app.json`, does not require a service restart.

## Quick start

`hello-world/main.py`:

```python
#!/usr/bin/env python3

from appbase import WHITE, app


@app()
def main(ctx):
    def tick(dt):
        ctx.fb.clear(0)
        ctx.fb.text_center(
            ctx.width // 2,
            ctx.height // 2,
            "HELLO",
            WHITE,
            2,
        )

    ctx.run(tick, fps=10)


if __name__ == "__main__":
    main()
```

A normal App has:

- an `app.json` manifest;
- a `main.py` entry point;
- `@app()` loading metadata from the adjacent manifest;
- `main(ctx)` using `AppContext`;
- a `__main__` guard.

`@app()` wraps the function but does not execute it during import. Keep the
guard so metadata and development tools can import the module without opening
framebuffer or touch devices:

```python
if __name__ == "__main__":
    main()
```

The host changes the child working directory to the App directory, so relative
resource paths such as `assets/icon.png` work. For modules that may also be
imported or tested from another working directory, resolve resources from
`__file__` instead:

```python
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
icon_path = APP_DIR / "assets" / "icon.png"
```

## Host and App lifecycle

When a user selects an App, the host:

1. verifies Launcher and touch are available;
2. requires a non-empty selected App script path;
3. maps current panel orientation to `APPBASE_FB_ROTATE` (`90` normally, `270` when manually reversed) and prepends `launcher.apps_dir` to `PYTHONPATH` for the shared `appbase` module;
4. detaches the touch fd from the normal LVGL input path;
5. changes the child working directory to the App directory, then forks and runs `launcher.python_bin <absolute-script-path>`;
6. supervises the child and the reserved exit gesture;
7. terminates/waits for the child when exit is confirmed or shutdown begins;
8. clears the complete physical framebuffer, reattaches normal touch handling, and forces an LVGL redraw.

The host currently sets only `APPBASE_FB_ROTATE`. `APPBASE_FB_DEVICE` and `APPBASE_TOUCH_DEVICE` use their defaults unless they are already present in the parent process environment. If `kvm_ui.toml` uses non-default device paths, configure matching `APPBASE_*` variables for the UI service or App process.

Inside the child, the decorator:

1. opens `FrameBuffer`;
2. probes geometry and mmaps the complete framebuffer;
3. opens `TouchReader`;
4. creates `AppContext` and calls the decorated function;
5. closes touch and framebuffer on normal return or exception;
6. treats `KeyboardInterrupt` as a quiet host-requested exit.

App code using `@app` must not open or close the same framebuffer/touch devices independently.

## Coordinates and the dead area

The physical framebuffer is `284x240`. The panel cannot display the physical leftmost 14 columns, leaving a `270x240` visible physical area.

`FrameBuffer.width` and `height` describe the complete framebuffer after logical rotation, not the always-visible area:

| `rotate` | Logical size | Logical edge mapped to the 14px physical dead area | Visible logical rectangle |
| ---: | --- | --- | --- |
| `0` | `284x240` | left 14 columns | `x=14..283`, `y=0..239` |
| `90` | `240x284` | bottom 14 rows | `x=0..239`, `y=0..269` |
| `180` | `284x240` | right 14 columns | `x=0..269`, `y=0..239` |
| `270` | `240x284` | top 14 rows | `x=0..239`, `y=14..283` |

The host normally launches Apps with `rotate=90`, so the visible logical canvas is `240x270` at the top of the full `240x284` buffer. Manual reverse uses `rotate=270`, moving the hidden rows to the top.

Use `ctx.width`, `ctx.height`, and `ctx.fb.rotate`; do not hard-code a `270x240` App canvas. A small helper can derive the visible rectangle for the default panel:

```python
from appbase import Rect


def visible_rect(fb):
    if fb.rotate == 90:
        return Rect(0, 0, fb.width, fb.height - 14)
    if fb.rotate == 270:
        return Rect(0, 14, fb.width, fb.height - 14)
    if fb.rotate == 180:
        return Rect(0, 0, fb.width - 14, fb.height)
    return Rect(14, 0, fb.width - 14, fb.height)
```

Drawing helpers clip partially out-of-bounds primitives. `flush()` copies the whole off-screen buffer to the mmap in one operation.

Raw Apps do not use the C++ UI's ST7789P3 RGB565 flush wrapper. That wrapper is currently an identity transform, so neither path provides software color correction. Verify colors on the target panel.

## Touch and the host exit gesture

`TouchReader.poll()` returns `(kind, x, y)` tuples in the same rotated logical coordinate space used for drawing. The coordinate is the touch-down position.

| Constant | String | Meaning |
| --- | --- | --- |
| `TAP` | `"tap"` | movement stays below the tap threshold |
| `UP` | `"up"` | upward swipe |
| `DOWN` | `"down"` | downward swipe |
| `LEFT` | `"left"` | leftward swipe |
| `RIGHT` | `"right"` | rightward swipe |

The host and child observe separate reads of the same evdev stream. The host reserves this gesture:

1. press inside the logical left-edge zone (`launcher.exit_gesture_zone_px`, default `40`);
2. swipe right to about 45% of screen width;
3. keep holding while the host pauses the child and fills a progress strip for `launcher.exit_gesture_hold_ms` (default `1200ms`);
4. release at full progress to terminate the App;
5. release early or slide back to cancel, restore overwritten pixels, and resume the child.

Because evdev readers each receive events, an App may observe the initial edge press before the host pauses it. Treat the left-edge zone as reserved: avoid destructive one-tap controls there and do not implement another competing exit gesture.

## SDK reference

### Metadata decorator

```python
@app()
```

The decorator reads metadata from the adjacent `app.json`, validates the four
required fields, owns framebuffer and touch setup/cleanup, and calls the
decorated function with one `AppContext`. Metadata is available as:

```python
print(main.__app_info__.as_dict())
```

`AppInfo` is a frozen dataclass.

### `AppContext`

```python
class AppContext:
    fb: FrameBuffer
    touch: TouchReader

    @property
    def width(self) -> int: ...

    @property
    def height(self) -> int: ...

    def poll(self): ...
    def flush(self): ...
    def taps(self): ...
    def button(self, rect, label, bg, fg=WHITE, scale=2): ...
    def run(self, tick, fps=20.0, on_tap=None, on_swipe=None): ...
```

- `poll()` delegates to `TouchReader.poll()`.
- `taps()` drops swipe events and returns only `(x, y)` positions.
- `button()` draws a filled `Rect` with a centered label and returns the same rect for hit testing.
- `run()` dispatches gestures, calls `tick(dt)`, flushes, and sleeps for the remaining frame period. Returning `False` from `tick` exits.

### `Rect`

```python
@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def contains(self, px, py) -> bool: ...

    @property
    def cx(self) -> int: ...

    @property
    def cy(self) -> int: ...
```

Use the same `Rect` for drawing and touch hit testing.

### `FrameBuffer`

Public geometry fields:

```python
device: str
rotate: int
phys_w: int
phys_h: int
bpp: int
stride: int
row_px: int
width: int
height: int
```

Drawing methods:

```python
flush()
clear(color=0)
put_pixel(x, y, color)
fill_rect(x, y, w, h, color)
draw_line(x0, y0, x1, y1, color)
draw_vline(x, y0, y1, color)
draw_text(x, y, text, color, scale=1)
text_width(text, scale=1)
text_center(cx, y, text, color, scale=1)
draw_sprite(x, y, rows, palette, scale=1)
touch_to_visual(raw_x, raw_y)
```

`draw_sprite` treats characters missing from `palette` and spaces as transparent.

### Colors

Use `rgb565(r, g, b)` or the predefined constants:

```text
BLACK WHITE RED GREEN BLUE YELLOW GRAY DKGRAY
ORANGE CYAN MAGENTA NAVY
```

## Examples

### Button and tap handling

```python
#!/usr/bin/env python3

from appbase import GREEN, RED, Rect, app


@app()
def main(ctx):
    state = {"count": 0}
    button = Rect(70, 80, 100, 48)

    def on_tap(x, y):
        if button.contains(x, y):
            state["count"] += 1

    def tick(dt):
        ctx.fb.clear(0)
        ctx.button(button, "ADD", GREEN)
        ctx.fb.text_center(
            ctx.width // 2,
            145,
            str(state["count"]),
            RED,
            2,
        )

    ctx.run(tick, fps=20, on_tap=on_tap)


if __name__ == "__main__":
    main()
```

### Pixel-art sprite

```python
from appbase import rgb565

palette = {
    "R": rgb565(255, 0, 0),
    "G": rgb565(0, 255, 0),
}
sprite = [
    "RR  GG",
    "RR  GG",
]

ctx.fb.draw_sprite(10, 10, sprite, palette, scale=2)
```

Repository examples:

| App | Pattern |
| --- | --- |
| `pomodoro-timer/main.py` | buttons, taps, countdown state |
| `conways-game-of-life/main.py` | paced animation loop |
| `nyan-cat/main.py` | pixel-art data and animation |
| `crypto-candlestick/main.py` | network fetch with synthetic fallback and swipe navigation |

## Environment variables

| Variable | Default | Notes |
| --- | --- | --- |
| `APPBASE_FB_DEVICE` | `/dev/fb0` | framebuffer path |
| `APPBASE_FB_ROTATE` | `0` | supported logical rotations: `0`, `90`, `180`, `270`; host sets `90` or `270` |
| `APPBASE_TOUCH_DEVICE` | `/dev/input/event0` | evdev touch path |

When running an App manually, set rotation explicitly or the framebuffer will use `0`:

```bash
PYTHONPATH=/etc/kvm/apps APPBASE_FB_ROTATE=90 \
  python3 /etc/kvm/apps/my-app/main.py
```

Manual execution while the host UI is active causes both processes to draw/read the same devices without normal Launcher supervision. Use the Apps page for expected lifecycle behavior.

## Deployment

Copy the shared SDK and complete App directory into the configured directory:

```bash
scp apps/appbase.py apps/appbase.pyi root@<device-ip>:/etc/kvm/apps/
scp -r apps/my-app root@<device-ip>:/etc/kvm/apps/
```

For a single new App, existing `appbase.py`/`appbase.pyi` on the device may be reused only when they match the App's expected SDK contract. Copy the whole App directory so resource paths relative to `main.py` remain intact.

Wait up to 10 seconds after deployment for the Apps list to refresh automatically. This project does not define a standalone package/install command for `/etc/kvm/apps`.

## Debug screenshots

In a `./builder.sh build debug` host, sending `SIGUSR1` to the main `kvm_ui` process captures the current App framebuffer to `/root/snapshot/*.ppm`. The parent temporarily stops a running child for an untorn copy and resumes it on every recoverable path.

```bash
kill -USR1 <kvm-ui-pid>
```

This is a host debug feature, not an App SDK method or HTTP endpoint. Non-debug builds ignore the signal and do not create a file.

## Validation and troubleshooting

Host syntax check:

```bash
python3 -m py_compile \
  apps/appbase.py \
  apps/crypto-candlestick/main.py \
  apps/conways-game-of-life/main.py \
  apps/nyan-cat/main.py \
  apps/pomodoro-timer/main.py
```

Build and test the simulator with the local Clang toolchain:

```bash
./builder.sh simulator_clean
CC=clang CXX=clang++ ./builder.sh simulator
./builder.sh simulator_test
```

Host checks do not validate fbdev, evdev, panel orientation, color, frame pacing, or the exit gesture.

### App does not appear

- Check the App directory contains both `main.py` and valid `app.json`.
- Check `app.json.name` is a non-empty string and the directory name does not start with `_`.
- Check `launcher.enabled` and `launcher.apps_dir`.
- Wait up to 10 seconds for the automatic Apps rescan.

### App launches with wrong orientation

- Launch through the Apps page so the host sets `APPBASE_FB_ROTATE`.
- For manual runs, set it to `90` or `270` as appropriate.
- Use the safe-area table above rather than assuming a logical left dead strip.

### No touch events

- Confirm the host was able to open configured touch input; otherwise it refuses the App session.
- Confirm `APPBASE_TOUCH_DEVICE` matches the target device when using a non-default path.
- `TouchReader` degrades to an empty event stream if it cannot open its device.

### Text or controls are clipped

- Layout against the visible rectangle, not the complete rotated buffer.
- Keep destructive controls outside the host's logical left-edge exit zone.
- Remember text uses the embedded 8x8 bitmap font scaled by integer factors.

### Colors differ from the LVGL UI

Raw Apps write RGB565 directly and bypass the C++ UI wrapper. Because that wrapper is currently an identity transform, a difference does not come from a wrapper color correction; verify panel output and App color values on target hardware if exact matching is required.

### UI does not return cleanly

- Prefer the host exit gesture instead of killing only the child from another shell.
- Check `launcher.child_term_timeout_ms` and host logs.
- Confirm the parent can clear `/dev/fb0`, reattach touch, and redraw LVGL after child exit.
