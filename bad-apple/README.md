# Bad Apple

This App plays a silent monochrome Bad Apple animation directly on the NanoKVM
RGB565 framebuffer. The animation loops automatically. Tap the screen to start
again from the first frame. The video uses a full-screen cover layout: it keeps
the original aspect ratio and crops the sides when necessary, so there are no
static black bars around the animation. Use the host's edge swipe gesture to
exit.

## Asset Format

`assets/frames.bin` is a `BAP2` container holding 240x180, 30 FPS, 1-bit frames
(6572 of them, about 3 minutes 39 seconds). Frames are packed in chunks of 32
and every chunk is compressed on its own with LZMA2. Grouping frames before
compressing is what keeps the asset small: the 33.8 MiB of raw bitmaps shrink
to 1.6 MiB, while compressing each frame in isolation needs 2.9 MiB because it
cannot see the neighbouring frames.

At startup the player reads the header and the chunk table. It then unpacks
only the chunk that holds the frame it is about to draw and reuses it for the
rest of that chunk, so displaying a frame costs at most one ~170 KiB chunk
instead of the whole animation. The player precomputes the crop and scale
mappings, then uses horizontal runs for unrotated framebuffers and vertical
runs for the usual 90/270-degree framebuffer orientations.

### Regenerating the asset

Frames are packed from binary PBM images. ffmpeg's `monob` pixel format
produces the 1-bit ordered-dither look the App renders:

```sh
ffmpeg -i bad-apple.mp4 -vf "fps=30,scale=240:180,format=monob" frames/%06d.pbm
tools/pack_frames.py --output assets/frames.bin --fps 30 frames/*.pbm
```

`tools/pack_frames.py` documents the container layout and accepts any PBM `P4`
frames that share one size, so the animation can also be re-cut at another
resolution or frame rate.

## Source

The source video supplied for this App is:

https://www.youtube.com/watch?v=FtutLA63Cp8

