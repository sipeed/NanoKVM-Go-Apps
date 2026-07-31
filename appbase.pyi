"""Type stubs for appbase.py — public interface contract for kvm_ui sub-apps."""

import dataclasses
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

# ---------------------------------------------------------------------------
# Color / pixel format
# ---------------------------------------------------------------------------

def rgb565(r: int, g: int, b: int) -> int: ...

# ---------------------------------------------------------------------------
# Framebuffer
# ---------------------------------------------------------------------------

class FrameBuffer:
    device: str
    rotate: int
    phys_w: int
    phys_h: int
    bpp: int
    stride: int
    row_px: int
    width: int
    height: int

    def __init__(
        self, device: Optional[str] = None, rotate: Optional[int] = None
    ) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> FrameBuffer: ...
    def __exit__(self, *exc: Any) -> None: ...
    def flush(self) -> None: ...
    def clear(self, color: int = 0) -> None: ...
    def put_pixel(self, x: int, y: int, color: int) -> None: ...
    def fill_rect(self, x: int, y: int, w: int, h: int, color: int) -> None: ...
    def draw_line(self, x0: int, y0: int, x1: int, y1: int, color: int) -> None: ...
    def draw_vline(self, x: int, y0: int, y1: int, color: int) -> None: ...
    def draw_text(
        self, x: int, y: int, text: str, color: int, scale: int = 1
    ) -> None: ...
    def text_width(self, text: str, scale: int = 1) -> int: ...
    def text_center(
        self, cx: int, y: int, text: str, color: int, scale: int = 1
    ) -> None: ...
    def draw_sprite(
        self,
        x: int,
        y: int,
        rows: List[str],
        palette: Dict[str, int],
        scale: int = 1,
    ) -> None: ...
    def touch_to_visual(self, rx: int, ry: int) -> Tuple[int, int]: ...

# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class TouchReader:
    def __init__(
        self, fb: FrameBuffer, device: Optional[str] = None
    ) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> TouchReader: ...
    def __exit__(self, *exc: Any) -> None: ...
    def poll(self) -> List[Tuple[str, int, int]]: ...

# Gesture kinds
TAP: str
UP: str
DOWN: str
LEFT: str
RIGHT: str

# ---------------------------------------------------------------------------
# Metadata and lifecycle
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class AppInfo:
    app_id: str
    name: str
    creator: str
    create_time: str
    version: str
    desc: str = ""
    category: str = ""
    icon: str = ""

    def as_dict(self) -> Dict[str, str]: ...


@dataclasses.dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    def contains(self, px: int, py: int) -> bool: ...
    @property
    def cx(self) -> int: ...
    @property
    def cy(self) -> int: ...


@dataclasses.dataclass
class AppContext:
    fb: FrameBuffer
    touch: TouchReader
    env: Mapping[str, str]

    @property
    def width(self) -> int: ...
    @property
    def height(self) -> int: ...
    def poll(self) -> List[Tuple[str, int, int]]: ...
    def flush(self) -> None: ...
    def taps(self) -> List[Tuple[int, int]]: ...
    def button(
        self, rect: Rect, label: str, bg: int, fg: int = ..., scale: int = 2
    ) -> Rect: ...
    def run(
        self,
        tick: Callable[..., Any],
        fps: float = 20.0,
        on_tap: Optional[Callable[[int, int], Any]] = None,
        on_swipe: Optional[Callable[[str, int, int], Any]] = None,
    ) -> None: ...


def app() -> Callable[[Callable[..., Any]], Callable[..., Any]]: ...

# ---------------------------------------------------------------------------
# Color constants
# ---------------------------------------------------------------------------

BLACK: int
WHITE: int
RED: int
GREEN: int
BLUE: int
YELLOW: int
GRAY: int
DKGRAY: int
ORANGE: int
CYAN: int
MAGENTA: int
NAVY: int
