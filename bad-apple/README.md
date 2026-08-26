# Bad Apple

This App plays a silent monochrome Bad Apple animation directly on the NanoKVM
RGB565 framebuffer. The animation loops automatically. Tap the screen to start
again from the first frame. The video uses a full-screen cover layout: it keeps
the original aspect ratio and crops the sides when necessary, so there are no
static black bars around the animation. Use the host's edge swipe gesture to
exit.

## Asset Format

`assets/frames.bin` contains 240x180, 30 FPS, 1-bit frames. Each frame is
compressed independently with zlib and has an index entry, so the player can
seek to the frame matching the current playback time instead of decoding a
video stream on the device.

At startup, the compressed payload is loaded into memory to avoid per-frame
file seeks. The player precomputes the crop and scale mappings, then uses
horizontal runs for unrotated framebuffers and vertical runs for the usual
90/270-degree framebuffer orientations.

## Source

The source video supplied for this App is:

https://www.youtube.com/watch?v=FtutLA63Cp8

