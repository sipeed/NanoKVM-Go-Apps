# Hello World

This is the minimal `hello-world` example from
`sipeed_wiki/docs/hardware/zh/kvm/NanoKVM_Go/custom_app.md`.

It demonstrates:

- clearing the RGB565 framebuffer through `ctx.fb`;
- centering text with `text_center()`; and
- using `ctx.run()` for a paced App lifecycle.

The App SDK opens and closes the framebuffer and touch devices through
`@app()`. Exit with the host's reserved left-edge swipe gesture.
