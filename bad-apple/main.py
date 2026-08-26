#!/usr/bin/env python3
"""Play a preprocessed, silent Bad Apple animation on the framebuffer."""

import struct
import time
import zlib
from pathlib import Path

from appbase import BLACK, WHITE, app

APP_DIR = Path(__file__).resolve().parent
FRAME_PATH = APP_DIR / "assets" / "frames.bin"
MAGIC = b"BAP1"
HEADER = struct.Struct("<4sHHHHI")
INDEX_ENTRY = struct.Struct("<II")


class FrameStore:
    """Read independently compressed monochrome frames from memory."""

    def __init__(self, path):
        self.file = open(path, "rb")
        header = self.file.read(HEADER.size)
        if len(header) != HEADER.size:
            self.close()
            raise ValueError("Bad Apple frame asset has a truncated header")

        magic, self.width, self.height, self.fps_num, self.fps_den, self.count = (
            HEADER.unpack(header)
        )
        if magic != MAGIC or self.fps_num == 0 or self.fps_den == 0:
            self.close()
            raise ValueError("Bad Apple frame asset has an invalid header")
        if self.count == 0:
            self.close()
            raise ValueError("Bad Apple frame asset contains no frames")

        self.row_bytes = (self.width + 7) // 8
        self.frame_bytes = self.row_bytes * self.height
        self.index = []
        for _ in range(self.count):
            entry = self.file.read(INDEX_ENTRY.size)
            if len(entry) != INDEX_ENTRY.size:
                self.close()
                raise ValueError("Bad Apple frame asset has a truncated index")
            self.index.append(INDEX_ENTRY.unpack(entry))

        # The compressed payload is only about 3 MB. Keeping it in memory
        # removes one seek/read pair from every displayed frame.
        self.payload = self.file.read()
        self.close()
        for offset, length in self.index:
            if offset + length > len(self.payload):
                raise ValueError("Bad Apple frame asset has an invalid index")

    @property
    def fps(self):
        return self.fps_num / self.fps_den

    def read(self, frame_number):
        offset, length = self.index[frame_number]
        compressed = self.payload[offset:offset + length]
        frame = zlib.decompress(compressed)
        if len(frame) != self.frame_bytes:
            raise ValueError("Bad Apple frame asset contains an invalid frame")
        return frame

    def close(self):
        if getattr(self, "file", None) is not None:
            self.file.close()
            self.file = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def visible_rect(ctx):
    """Return the visible logical framebuffer area, excluding the hidden edge."""
    if ctx.fb.rotate == 90:
        return 0, 0, ctx.width, ctx.height - 14
    if ctx.fb.rotate == 270:
        return 0, 14, ctx.width, ctx.height - 14
    if ctx.fb.rotate == 180:
        return 0, 0, ctx.width - 14, ctx.height
    return 14, 0, ctx.width - 14, ctx.height


def build_render_plan(fb, source_width, source_height,
                      dest_x, dest_y, dest_width, dest_height):
    """Precompute the center-crop and nearest-neighbor coordinate mappings."""
    if dest_width <= 0 or dest_height <= 0:
        raise ValueError("Bad Apple destination must be visible")

    if dest_width * source_height > dest_height * source_width:
        crop_width = source_width
        crop_height = max(1, dest_height * source_width // dest_width)
    else:
        crop_width = max(1, dest_width * source_height // dest_height)
        crop_height = source_height

    crop_x = (source_width - crop_width) // 2
    crop_y = (source_height - crop_height) // 2
    row_bytes = (source_width + 7) // 8

    # Source pixel boundaries map exactly to the old run-based scaler. Y uses
    # ceil boundaries because playback samples source rows with floor mapping.
    x_bounds = [column * dest_width // crop_width
                for column in range(crop_width + 1)]
    y_bounds = [((row * dest_height) + crop_height - 1) // crop_height
                for row in range(crop_height + 1)]
    row_starts = [(crop_y + row) * row_bytes
                  for row in range(crop_height)]
    column_bytes = [(crop_x + column) // 8
                    for column in range(crop_width)]
    column_masks = [0x80 >> ((crop_x + column) % 8)
                    for column in range(crop_width)]

    return {
        "x": dest_x,
        "y": dest_y,
        "width": dest_width,
        "height": dest_height,
        "crop_width": crop_width,
        "crop_height": crop_height,
        "x_bounds": x_bounds,
        "y_bounds": y_bounds,
        "row_starts": row_starts,
        "column_bytes": column_bytes,
        "column_masks": column_masks,
        "vertical_runs": fb.rotate in (90, 270),
    }


def draw_frame(fb, frame, plan):
    """Draw one frame using runs aligned with the framebuffer rotation."""
    crop_width = plan["crop_width"]
    crop_height = plan["crop_height"]
    x_bounds = plan["x_bounds"]
    y_bounds = plan["y_bounds"]
    row_starts = plan["row_starts"]
    column_bytes = plan["column_bytes"]
    column_masks = plan["column_masks"]
    dest_x = plan["x"]
    dest_y = plan["y"]
    vertical_runs = plan["vertical_runs"]

    if vertical_runs:
        # For rotate=90/270, a logical vertical rect is contiguous in the
        # physical framebuffer. Scan each source column once and reuse its
        # scaled run for every destination column covered by that source col.
        for column in range(crop_width):
            run_start = None
            byte_offset = column_bytes[column]
            mask = column_masks[column]
            for row in range(crop_height + 1):
                filled = False
                if row < crop_height:
                    filled = frame[row_starts[row] + byte_offset] & mask != 0
                if filled and run_start is None:
                    run_start = row
                elif not filled and run_start is not None:
                    x0 = x_bounds[column]
                    x1 = x_bounds[column + 1]
                    y0 = y_bounds[run_start]
                    y1 = y_bounds[row]
                    if x1 > x0 and y1 > y0:
                        fb.fill_rect(dest_x + x0, dest_y + y0,
                                     x1 - x0, y1 - y0, WHITE)
                    run_start = None
        return

    # For rotate=0/180, a logical horizontal rect is contiguous. Cache the
    # source-row work by scanning each source row once, even when it scales to
    # multiple destination rows.
    for row in range(crop_height):
        run_start = None
        row_start = row_starts[row]
        for column in range(crop_width + 1):
            filled = False
            if column < crop_width:
                filled = frame[row_start + column_bytes[column]] & column_masks[column] != 0
            if filled and run_start is None:
                run_start = column
            elif not filled and run_start is not None:
                x0 = x_bounds[run_start]
                x1 = x_bounds[column]
                y0 = y_bounds[row]
                y1 = y_bounds[row + 1]
                if x1 > x0 and y1 > y0:
                    fb.fill_rect(dest_x + x0, dest_y + y0,
                                 x1 - x0, y1 - y0, WHITE)
                run_start = None

@app()
def main(ctx):
    with FrameStore(FRAME_PATH) as frames:
        visible_x, visible_y, visible_w, visible_h = visible_rect(ctx)
        render_plan = build_render_plan(
            ctx.fb, frames.width, frames.height,
            visible_x, visible_y, visible_w, visible_h,
        )
        state = {"started": time.monotonic()}

        def restart(_x=0, _y=0):
            state["started"] = time.monotonic()

        def tick(_dt):
            elapsed = max(0.0, time.monotonic() - state["started"])
            frame_number = int(elapsed * frames.fps) % frames.count
            frame = frames.read(frame_number)
            ctx.fb.clear(BLACK)
            draw_frame(ctx.fb, frame, render_plan)

        ctx.run(tick, fps=frames.fps, on_tap=restart)


if __name__ == "__main__":
    main()
