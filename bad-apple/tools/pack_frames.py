#!/usr/bin/env python3
"""Pack 1-bit PBM frames into the Bad Apple ``frames.bin`` asset.

The container is ``BAP2``: a fixed header, a chunk table, and LZMA2 chunks that
hold a group of raw 1-bit frames. Chunking keeps the asset small (the compressor
still sees whole frames as context) while the player only has to unpack one
chunk per displayed group, so decoding stays cheap on the NanoKVM CPU.

Frame layout is one bit per pixel, MSB first, each row padded to a byte
boundary -- the same layout PBM ``P4`` uses, so frames can be fed straight from
ffmpeg:

    ffmpeg -i bad-apple.mp4 -vf "fps=30,scale=240:180,format=monob" \
        frames/%06d.pbm
    tools/pack_frames.py --output assets/frames.bin --fps 30 frames/*.pbm
"""

from __future__ import annotations

import argparse
import lzma
import struct
import sys
from fractions import Fraction
from pathlib import Path

MAGIC = b"BAP2"
HEADER = struct.Struct("<4sHHHHHI")
CHUNK_ENTRY = struct.Struct("<II")
DEFAULT_CHUNK_FRAMES = 32

# 64 KiB of history is enough for a 32 frame chunk (each frame is 5.4 KB) and
# keeps the decoder window small on the device.
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 6, "dict_size": 1 << 16}]
WHITESPACE = b" \t\r\n\v\f"
DIGITS = b"0123456789"


def read_pbm(path):
    """Return (width, height, row_bytes, payload) of a binary PBM ``P4``."""
    data = path.read_bytes()
    if not data.startswith(b"P4"):
        raise ValueError(f"{path}: expected a binary PBM (P4) file")

    position = 2
    values = []
    while len(values) < 2:
        if position >= len(data):
            raise ValueError(f"{path}: truncated PBM header")
        byte = data[position]
        if byte in WHITESPACE:
            position += 1
            continue
        if byte == ord("#"):
            while position < len(data) and data[position] not in (10, 13):
                position += 1
            continue
        start = position
        while position < len(data) and data[position] in DIGITS:
            position += 1
        if start == position:
            raise ValueError(f"{path}: truncated PBM header")
        values.append(int(data[start:position]))
    position += 1  # one whitespace byte separates the header from the raster

    width, height = values
    if width <= 0 or height <= 0:
        raise ValueError(f"{path}: invalid PBM size {width}x{height}")
    row_bytes = (width + 7) // 8
    expected = row_bytes * height
    payload = data[position:]
    if len(payload) != expected:
        raise ValueError(
            f"{path}: expected {expected} bytes of bitmap data, "
            f"found {len(payload)}")
    return width, height, row_bytes, payload


def pack(frames, width, height, fps_num, fps_den, chunk_frames):
    """Build a ``BAP2`` container from raw 1-bit frames."""
    if not frames:
        raise ValueError("no frames to pack")
    if chunk_frames <= 0:
        raise ValueError("chunk size must be positive")
    row_bytes = (width + 7) // 8
    frame_bytes = row_bytes * height
    for index, frame in enumerate(frames):
        if len(frame) != frame_bytes:
            raise ValueError(f"frame {index} is not {frame_bytes} bytes")

    chunk_count = (len(frames) + chunk_frames - 1) // chunk_frames
    table = bytearray()
    payload = bytearray()
    for chunk in range(chunk_count):
        group = frames[chunk * chunk_frames:(chunk + 1) * chunk_frames]
        blob = lzma.compress(b"".join(group), format=lzma.FORMAT_XZ,
                             filters=LZMA_FILTERS)
        table += CHUNK_ENTRY.pack(len(payload), len(blob))
        payload += blob

    header = HEADER.pack(MAGIC, width, height, fps_num, fps_den, chunk_frames,
                         len(frames))
    return header + bytes(table) + bytes(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frames", nargs="+", type=Path,
                        help="PBM P4 frames, ordered by playback time")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fps", type=float, required=True,
                        help="playback rate of the packed frames")
    parser.add_argument("--chunk-frames", type=int,
                        default=DEFAULT_CHUNK_FRAMES,
                        help="frames grouped into one LZMA2 chunk")
    args = parser.parse_args(argv)

    frame_rate = Fraction(args.fps).limit_denominator(0xFFFF)
    fps_num, fps_den = frame_rate.numerator, frame_rate.denominator
    if fps_num <= 0 or fps_num > 0xFFFF or fps_den > 0xFFFF:
        parser.error("--fps must be a positive rate that fits the header")

    raws = []
    size = None
    for path in args.frames:
        width, height, row_bytes, payload = read_pbm(path)
        if size is None:
            size = (width, height, row_bytes)
        elif size != (width, height, row_bytes):
            raise SystemExit(f"{path}: frame is {width}x{height}, "
                             f"expected {size[0]}x{size[1]}")
        raws.append(payload)

    width, height, row_bytes = size
    blob = pack(raws, width, height, fps_num, fps_den, args.chunk_frames)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(blob)

    raw_bytes = row_bytes * height * len(raws)
    print(f"{args.output}: {len(raws)} frames {width}x{height} @ "
          f"{frame_rate.numerator / frame_rate.denominator:g} FPS, "
          f"{raw_bytes / 1048576:.1f} MiB -> "
          f"{len(blob) / 1048576:.2f} MiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
