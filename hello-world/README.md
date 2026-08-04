# Hello World

This is the minimal `hello-world` example from
`sipeed_wiki/docs/hardware/zh/kvm/NanoKVM_Go/custom_app.md`.

It demonstrates:

- clearing the RGB565 framebuffer through `ctx.fb`;
- centering text with `text_center()`; and
- drawing a dependency-free embedded bitmap for Chinese text;
- using `ctx.run()` for a paced App lifecycle.

The App SDK opens and closes the framebuffer and touch devices through
`@app()`. The bottom guide explains how to complete or cancel the host's
reserved left-edge exit gesture. It defaults to English; tap the top-right
`中`/`En` button to switch languages.
