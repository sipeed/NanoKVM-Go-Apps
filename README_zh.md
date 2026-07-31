# NanoKVM Python App 开发指南

[English](README.md)

NanoKVM Python App 是由 `kvm_ui` Apps 页面启动的全屏应用。App 使用共享库 `appbase.py` 直接绘制 RGB565 framebuffer，并从 evdev 读取触摸事件，不需要嵌入 LVGL。

本文档描述首版 App 目录规范、运行模型、公共 API、验证及部署流程。英文版见 [README.md](README.md)。

## 1. 开发前提

- Python 3；
- NanoKVM framebuffer，默认 `/dev/fb0`；
- NanoKVM 触摸设备，默认 `/dev/input/event0`；
- `kvm_ui.toml` 中 `launcher.enabled = true`；
- App 安装目录默认为 `/kvmcomm/apps`。

共享文件 `appbase.py` 是 SDK 实现，`appbase.pyi` 是公共类型声明。修改公共类、函数、字段或返回类型时，必须同步维护二者。

## 2. 创建 App

每个 App 使用一个独立目录。目录名建议使用小写英文单词，并用连字符 `-` 分隔：

```text
apps/
├── appbase.py
├── appbase.pyi
└── hello-world/
    ├── main.py
    ├── app.json
    └── assets/                  # 可选资源
        └── icon.png
```

启动器在 UI 启动时扫描 `launcher.apps_dir` 的直接子目录。一个 App 必须满足：

1. 目录名不以 `_` 开头；
2. `main.py` 是普通文件；
3. `app.json` 是合法 JSON 对象；
4. `app.json.app_id` 是合法倒置域名包名，并与目录名对应；
5. `app.json.name` 是非空字符串。

扫描结果按 `name` 排序。`kvm_ui` 每 10 秒重新扫描一次；安装、删除、重命名或修改 `app.json` 后无需重启服务。

### 2.1 编写 app.json

```json
{
  "app_id": "com.example.hello_world",
  "name": "Hello World",
  "creator": "Your Name",
  "create_time": "2026-07-30",
  "version": "1.0.0",
  "desc": "A minimal NanoKVM App.",
  "category": "demo",
  "icon": "assets/icon.png",
  "pre_script": "scripts/pre-install.sh",
  "post_script": "scripts/post-install.sh"
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `app_id` | 是 | 稳定包名；目录 `hello-world` 对应 `com.example.hello_world` |
| `name` | 是 | Apps 页面显示名称 |
| `creator` | 是 | 作者或团队名称 |
| `create_time` | 是 | 创建日期，建议使用 `YYYY-MM-DD` |
| `version` | 是 | App 版本，建议使用语义化版本 |
| `desc` | 否 | 简短描述 |
| `category` | 否 | 分类标识 |
| `icon` | 否 | 图标资源相对路径 |
| `pre_script` | 否 | 部署前执行的 App 内相对脚本 |
| `post_script` | 否 | 部署后执行的 App 内相对脚本 |

`app_id` 至少包含三段，最后一段必须等于目录名将 `-` 替换为 `_` 后的结果；Sipeed 官方 App 使用 `com.sipeed.*`。`@app()` 会校验该规则。

`app.json.env` 声明的部署配置由 Launcher 注入，并由 `@app()` 以只读 `ctx.env` 映射提供给应用；不要创建独立 `.env` 文件。

Server 会以 root 身份执行可选安装脚本，并提供 `NANOKVM_APP_DIR`、`NANOKVM_APP_ID`、`NANOKVM_APP_PHASE` 和已配置的 `env`。脚本限制为 15 分钟和 64 KiB 日志；前置脚本失败则不安装，后置脚本失败则移除新 App 目录。只安装可信来源中包含脚本的 App。

上传和下载 ZIP 固定包含一个顶层 App 目录，其内才是 `app.json`、`main.py` 和可选资源；不接受文件直接位于 ZIP 根目录或一个 ZIP 包含多个 App。

### 2.2 编写 main.py

```python
#!/usr/bin/env python3

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
```

`@app()` 是 App 的标准入口包装器，负责：

1. 读取同目录的 `app.json` 并校验必填元数据；
2. 打开 framebuffer；
3. 打开触摸设备；
4. 创建 `AppContext` 并调用 `main(ctx)`；
5. 在正常返回、异常或主机终止 App 时释放设备资源。

不要在使用 `@app()` 的 App 中再次独立打开或关闭同一个 framebuffer、触摸设备。

装饰后的入口会通过 `main.__app_info__` 暴露只读的 `AppInfo`：

```python
print(main.__app_info__.as_dict())
```

`@app()` 只包装函数，不会在模块导入时自动执行。`main.py` 仍应保留：

```python
if __name__ == "__main__":
    main()
```

这样其他工具导入模块读取元数据时，不会意外打开 framebuffer 和触摸设备。

## 3. 运行环境与资源

启动 App 时，主机将：

1. 检查 Launcher 和触摸设备是否可用；
2. 把 `launcher.apps_dir` 加入 `PYTHONPATH`；
3. 根据当前面板方向设置 `APPBASE_FB_ROTATE`；
4. 暂停 LVGL 对触摸设备的读取；
5. 把工作目录切换到 App 目录；
6. 执行 `launcher.python_bin <App绝对路径>/main.py`；
7. 监控子进程和退出手势；
8. App 结束后清理 framebuffer、恢复触摸并强制重绘主界面。

因此 App 可以直接导入共享 SDK：

```python
from appbase import AppContext, app
```

也可以直接使用 App 目录内的相对资源路径：

```python
icon_path = "assets/icon.png"
```

如果代码会被其他模块调用，建议基于 `__file__` 构造路径，避免依赖当前工作目录：

```python
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
icon_path = APP_DIR / "assets" / "icon.png"
```

## 4. AppContext API

```python
class AppContext:
    fb: FrameBuffer
    touch: TouchReader
    width: int
    height: int

    def poll(self): ...
    def flush(self): ...
    def taps(self): ...
    def button(self, rect, label, bg, fg=WHITE, scale=2): ...
    def run(self, tick, fps=20.0, on_tap=None, on_swipe=None): ...
```

- `width`、`height`：旋转后的完整逻辑 framebuffer 尺寸；
- `poll()`：返回尚未处理的触摸事件；
- `flush()`：把后备缓冲提交到屏幕；
- `taps()`：只返回点击坐标，忽略滑动；
- `button()`：绘制按钮并返回用于命中检测的同一个 `Rect`；
- `run()`：执行限帧主循环，分发触摸事件，调用 `tick(dt)` 并自动刷新。

`tick(dt)` 的 `dt` 是距上一帧的秒数。返回 `False` 可以结束主循环。

### 4.1 Rect

```python
@dataclass(frozen=True)
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
```

同一个 `Rect` 可同时用于绘制和触摸命中检测。

### 4.2 点击按钮示例

```python
from appbase import AppContext, GREEN, RED, Rect, app


@app()
def main(ctx: AppContext) -> None:
    state = {"count": 0}
    add_button = Rect(70, 80, 100, 48)

    def on_tap(x: int, y: int) -> None:
        if add_button.contains(x, y):
            state["count"] += 1

    def tick(dt: float) -> None:
        ctx.fb.clear(0)
        ctx.button(add_button, "ADD", GREEN)
        ctx.fb.text_center(
            ctx.width // 2, 145, str(state["count"]), RED, 2
        )

    ctx.run(tick, fps=20, on_tap=on_tap)


if __name__ == "__main__":
    main()
```

## 5. 绘图 API

`FrameBuffer` 提供以下几何信息：

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

`ctx.fb` 提供以下公共方法：

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

颜色可通过 `rgb565(r, g, b)` 创建，也可使用预定义常量：

```text
BLACK WHITE RED GREEN BLUE YELLOW GRAY DKGRAY
ORANGE CYAN MAGENTA NAVY
```

`draw_sprite()` 使用字符串数组描述像素，空格和未出现在 `palette` 中的字符均为透明。

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

Python App 直接写入 RGB565，不使用 C++ UI 的 ST7789P3 绿色通道 LUT，因此相同 RGB565 数值的显示效果可能与 LVGL 界面不同。需要准确配色时应以设备实测为准。

## 6. 触摸与退出手势

`ctx.poll()` 返回 `(kind, x, y)`：

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `TAP` | `"tap"` | 点击 |
| `UP` | `"up"` | 向上滑动 |
| `DOWN` | `"down"` | 向下滑动 |
| `LEFT` | `"left"` | 向左滑动 |
| `RIGHT` | `"right"` | 向右滑动 |

主机保留左边缘退出手势：

1. 从逻辑左侧区域按下，默认宽度由 `launcher.exit_gesture_zone_px = 40` 决定；
2. 向屏幕宽度约 45% 的位置滑动；
3. 保持按下，主机会暂停 App 并显示进度，默认时长由 `launcher.exit_gesture_hold_ms = 1200` 决定；
4. 进度完成后松手退出；提前松手或滑回则取消并恢复 App。

App 应避免在左边缘放置具有破坏性的一次点击操作，也不应实现与主机竞争的退出手势。

触摸坐标与绘图使用相同的旋转后逻辑坐标系，事件坐标是按下位置。如果 `TouchReader` 无法打开设备，它会返回空事件流；正常从 Apps 页面启动时，主机发现触摸不可用会直接拒绝启动 App。

## 7. 屏幕尺寸与不可见区域

物理 framebuffer 为 `284x240`，其中物理最左侧 14 列不会显示：

| `rotate` | 逻辑尺寸 | 不可见区域 | 可见逻辑区域 |
| ---: | --- | --- | --- |
| `0` | `284x240` | 左侧 14 列 | `x=14..283, y=0..239` |
| `90` | `240x284` | 底部 14 行 | `x=0..239, y=0..269` |
| `180` | `284x240` | 右侧 14 列 | `x=0..269, y=0..239` |
| `270` | `240x284` | 顶部 14 行 | `x=0..239, y=14..283` |

主机通常以 `rotate=90` 启动 App，屏幕反转时使用 `rotate=270`。布局应基于 `ctx.width`、`ctx.height` 和 `ctx.fb.rotate`，不要假定固定方向。可以使用以下辅助函数计算可见区域：

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

绘图方法会裁剪部分越界的图形，`flush()` 会一次性把完整后备缓冲复制到 framebuffer。

## 8. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APPBASE_FB_DEVICE` | `/dev/fb0` | framebuffer 设备 |
| `APPBASE_FB_ROTATE` | `0` | `0`、`90`、`180` 或 `270`；主机通常设置为 `90` 或 `270` |
| `APPBASE_TOUCH_DEVICE` | `/dev/input/event0` | evdev 触摸设备 |

手动运行时必须设置正确方向：

```bash
PYTHONPATH=/kvmcomm/apps APPBASE_FB_ROTATE=90 \
  python3 /kvmcomm/apps/hello-world/main.py
```

主界面运行时手动启动 App 会导致两个进程同时操作 framebuffer 和触摸设备。正常使用及设备验证应从 Apps 页面启动。

## 9. 本机验证

在 `kvm_ui/` 目录检查 Python 语法：

```bash
python3 -m py_compile \
  apps/appbase.py \
  apps/hello-world/main.py
```

使用 Clang 构建并测试 simulator：

```bash
./builder.sh simulator_clean
CC=clang CXX=clang++ ./builder.sh simulator
./builder.sh simulator_test
```

## 10. 部署

复制共享 SDK 和完整 App 目录：

```bash
scp apps/appbase.py apps/appbase.pyi root@DEVICE_IP:/kvmcomm/apps/
scp -r apps/hello-world root@DEVICE_IP:/kvmcomm/apps/
```

资源文件应随 App 目录一起复制。部署完成后等待最多 10 秒，Apps 列表会自动刷新。

设备上已有的 `appbase.py` 和 `appbase.pyi` 只有在其 SDK 契约满足 App 要求时才可复用；部署依赖新版 API 的 App 时应同步更新这两个共享文件。

## 11. 调试截图

使用 `./builder.sh build debug` 构建的设备版本支持向 `kvm_ui` 主进程发送 `SIGUSR1`，把当前 App framebuffer 保存到 `/root/snapshot/*.ppm`：

```bash
kill -USR1 KVM_UI_PID
```

抓取时主机会短暂停止 App，避免画面撕裂，随后恢复运行。该能力仅存在于设备 debug 构建中，不是 App SDK API；非 debug 构建会忽略此信号。

## 12. 排障

### App 未出现在列表

- 确认目录直接位于 `launcher.apps_dir` 下；
- 确认同时存在 `main.py` 和合法的 `app.json`；
- 确认 `app.json.name` 非空；
- 确认目录名不以 `_` 开头；
- 确认 `launcher.enabled = true`；
- 等待最多 10 秒让 Apps 列表自动刷新。

### 启动后方向错误

- 从 Apps 页面启动，让主机设置 `APPBASE_FB_ROTATE`；
- 手动启动时显式设置 `90` 或 `270`；
- 根据不可见区域调整布局。

### 没有触摸事件

- 检查主机是否成功打开触摸设备；
- 非默认设备需要设置 `APPBASE_TOUCH_DEVICE`；
- 查看 `kvm_ui` 日志中的 Launcher 和触摸错误。

### 文字或控件被裁切

- 按可见区域布局，不要只参考完整 framebuffer 尺寸；
- 避开主机保留的左边缘退出区域；
- 内置文字是 8x8 位图字体，只支持整数倍缩放。

### 颜色与主界面不一致

Python App 不使用 LVGL 的面板颜色 LUT。请在目标设备上调整 RGB565 颜色。

### UI 没有正常恢复

- 使用主机保留的退出手势；
- 检查 `launcher.child_term_timeout_ms`；
- 检查主机是否能重新打开 framebuffer、恢复触摸并重绘 LVGL。

## 13. 内置示例

| 目录 | 展示内容 |
| --- | --- |
| `pomodoro-timer` | 按钮、点击和倒计时状态 |
| `conways-game-of-life` | 限帧动画循环 |
| `nyan-cat` | 像素精灵与动画 |
| `crypto-candlestick` | 网络请求、模拟数据回退和滑动翻页 |
