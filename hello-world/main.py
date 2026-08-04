#!/usr/bin/env python3
"""Minimal Hello World App from the NanoKVM Go custom App guide."""

from appbase import AppContext, WHITE, app


@app()
def main(ctx: AppContext) -> None:
    def tick(dt: float) -> None:
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
