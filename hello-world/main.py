#!/usr/bin/env python3
"""Minimal Hello World App from the NanoKVM Go custom App guide."""

from appbase import AppContext, DKGRAY, Rect, WHITE, app

# Pre-rendered 216x64 monochrome bitmap for these four lines. appbase's
# built-in 8x8 font is ASCII-only, so embedding the small bitmap keeps this
# example dependency-free on the device.
#
# 退出：从左边缘右滑并按住，
# 进度条填满后松开
# 取消：右滑按住后向左移回，
# 进度条分开后松开
ZH_GUIDE_WIDTH = 216
ZH_GUIDE_ROWS = (
    "000000000000000000000000000000000000000000000000000000",
    "0000000006000000000200010088004031f8204106011000000000",
    "000033f80600000108020041008f80c00908108102031000000000",
    "0000130846200001080200610110808001c818813fc20800000000",
    "00000bf846208001083ffc2ff15f0fff0148fff3e046ff00000000",
    "0000030846208003080400011241018027fc108124461800000000",
    "00003bf846200002080400c213bfc1001c041081040e1800000000",
    "00000b047fe0000318040042108c010007fc10813fc61800000000",
    "00000b7806000002980ffc421134c3fe020810814886ff00000000",
    "00000b10c6300002d408404433c787020bf8fff399861800000000",
    "00000bc8c63000065418404c221a8d020a08108119061818000000",
    "00000b04c630000426104048e046890213f810810f06181c000000",
    "00003c00c6308004622040e0018a41021208208107061804000000",
    "000023fcfff08008410ffc98023241fe220860810c87ff08000000",
    "00000000003000080000008ff00601020238808330460010000000",
    "000000000000000000000000000000000000000000000000000000",
    "000000000000000000000000000000000000000000000000000000",
    "000000000000001200400400830012001c10200000000000000000",
    "000000000000061200400fe09fe2ff8fe01121ffe0000000000000",
    "00000000000003120ffe1840820112080011102100000000000000",
    "000000000000007f890864808fc00008007d102100000000000000",
    "00000000000000120ffe0301e840ff8ffe12182100000000000000",
    "000000000000001209080fc08fc614080032c82100000000000000",
    "0000000000000712090870388840ff88003889ffe0000000000000",
    "000000000000017f89f803008fc09488005c802100000000000000",
    "000000000000013208003ff08fc1948bfc50802100000000000000",
    "00000000000001220ffc0300e843ae8a0451102100000000000000",
    "000000000000016211080b41dfe2a58a0491104100000000000000",
    "000000000000078010f0132004828892041238c100000000000000",
    "000000000000047f90f0231008648093fc13e98100000000000000",
    "0000000000000000170e0600102083920410010100000000000000",
    "000000000000000000000000000000000000000000000000000000",
    "000000000000000000000000000000000000000000000000000000",
    "00000000018000004031f8418044000e0100080002000000000000",
    "00003f0069900000c009084080c407f001000801c40fff00000000",
    "000012fc25a000008001c84ff0820400030008028f880100000000",
    "000012440180800fff0148f811bfc4003ffcfff0b1880100000000",
    "00001e448ff080018027fc49118607ff20041003c709f900000000",
    "0000124848300001001c044103860400200410018d090900000000",
    "00001248083000010007fc4ff186040027e4100192090900000000",
    "00001e280ff00003fe02085221bfc40024243ff1c7c90900000000",
    "0000123028300007020bf8e6618605fe24242102cc490900000000",
    "000012302830000d020a084641860502242461029489f918000000",
    "00001f306ff000090213f843c186050227e441048388011c000000",
    "000032684830800102120841c18609022404810083080104000000",
    "000002ccc8308001fe22084321ffc9fe20043ff08c0fff08000000",
    "0000028488600001020238cc1180090220380000b0080110000000",
    "000000000000000000000000000000000000000000000000000000",
    "000000000000000000000000000000000000000000000000000000",
    "000000000000001200400400000000001c10200000000000000000",
    "000000000000061200400fe02107ff8fe01121ffe0000000000000",
    "00000000000003120ffe1840218084080011102100000000000000",
    "000000000000007f8908648040808408007d102100000000000000",
    "00000000000000120ffe0300c040840ffe12182100000000000000",
    "000000000000001209080fc1806084080032c82100000000000000",
    "0000000000000712090870397fa7ff88003889ffe0000000000000",
    "000000000000017f89f8030010808408005c802100000000000000",
    "000000000000013208003ff01080840bfc50802100000000000000",
    "00000000000001220ffc03001080840a0451102100000000000000",
    "000000000000016211080b403081040a0491104100000000000000",
    "000000000000078010f0132020830412041238c100000000000000",
    "000000000000047f90f0231040860413fc13e98100000000000000",
    "0000000000000000170e0601870404120410010100000000000000",
    "000000000000000000000000000000000000000000000000000000",
)

ZH_BUTTON_ROWS = (
    "0180", "0180", "0180", "3ffc",
    "2184", "2184", "2184", "2184",
    "2184", "3ffc", "2184", "0180",
    "0180", "0180", "0180", "0180",
)

EN_GUIDE = (
    "Exit: Swipe right from the",
    "left edge and hold.",
    "Release when the progress",
    "bar is full.",
    "Cancel: While holding after",
    "the swipe, move left until",
    "the bars separate, then",
    "release.",
)


def draw_hex_bitmap(fb, x, y, width, rows, color, scale=1):
    """Draw hexadecimal bitmap rows as horizontal runs."""
    for row_index, encoded in enumerate(rows):
        bits = int(encoded, 16)
        run_start = None
        for column in range(width + 1):
            filled = column < width and bits & (1 << (width - column - 1))
            if filled and run_start is None:
                run_start = column
            elif not filled and run_start is not None:
                fb.fill_rect(x + run_start * scale, y + row_index * scale,
                             (column - run_start) * scale, scale, color)
                run_start = None


def visible_vertical_bounds(ctx):
    """Exclude the panel's 14-pixel hidden edge after rotation."""
    if ctx.fb.rotate == 90:
        return 0, ctx.height - 14
    if ctx.fb.rotate == 270:
        return 14, ctx.height
    return 0, ctx.height


def draw_language_button(ctx, button, show_chinese):
    """Draw the language that tapping the button will switch to."""
    fb = ctx.fb
    fb.fill_rect(button.x, button.y, button.w, button.h, DKGRAY)
    fb.fill_rect(button.x, button.y, button.w, 1, WHITE)
    fb.fill_rect(button.x, button.y + button.h - 1, button.w, 1, WHITE)
    fb.fill_rect(button.x, button.y, 1, button.h, WHITE)
    fb.fill_rect(button.x + button.w - 1, button.y, 1, button.h, WHITE)
    if show_chinese:
        fb.text_center(button.cx, button.y + 12, "En", WHITE, 2)
    else:
        draw_hex_bitmap(fb, button.cx - 16, button.y + 4,
                        16, ZH_BUTTON_ROWS, WHITE, 2)


@app()
def main(ctx: AppContext) -> None:
    top, bottom = visible_vertical_bounds(ctx)
    language_button = Rect(ctx.width - 64, top + 8, 56, 40)
    state = {"chinese": False}

    def switch_language(x: int, y: int) -> None:
        if language_button.contains(x, y):
            state["chinese"] = not state["chinese"]

    def tick(dt: float) -> None:
        ctx.fb.clear(0)
        draw_language_button(ctx, language_button, state["chinese"])

        if state["chinese"]:
            guide_height = len(ZH_GUIDE_ROWS)
        else:
            guide_height = len(EN_GUIDE) * 10
        guide_y = bottom - guide_height - 8

        ctx.fb.text_center(
            ctx.width // 2,
            (top + bottom) // 2 - 8,
            "HELLO",
            WHITE,
            2,
        )

        if state["chinese"]:
            draw_hex_bitmap(
                ctx.fb,
                (ctx.width - ZH_GUIDE_WIDTH) // 2,
                guide_y,
                ZH_GUIDE_WIDTH,
                ZH_GUIDE_ROWS,
                WHITE,
            )
        else:
            for index, line in enumerate(EN_GUIDE):
                ctx.fb.text_center(
                    ctx.width // 2,
                    guide_y + index * 10,
                    line,
                    WHITE,
                )

    ctx.run(tick, fps=10, on_tap=switch_language)


if __name__ == "__main__":
    main()
