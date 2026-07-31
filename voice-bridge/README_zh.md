# Voice Bridge 设备端应用

[English](./README.md) | [简体中文](./README_zh.md)

这是一个运行在 NanoKVM Go 屏幕上的前台应用。应用通过设备本机的 MCP 服务申请权限受限的短期媒体会话，建立双向 WebRTC 音频轨道，并将其桥接到 Qwen Audio Realtime。

打开应用后开始语音桥接；退出应用时会关闭 Qwen WebSocket、WebRTC PeerConnection 和 MCP media session，不会在后台继续播放或接收音频。

本应用使用最新版 NanoKVM Go Apps 目录规范：

```text
/kvmcomm/apps/
├── appbase.py
├── appbase.pyi
└── voice-bridge/
    ├── app.json
    ├── main.py
    └── python/              # App 私有 Python 依赖
```

目标设备必须已经升级到支持 `app.json` 和无参数 `@app()` 的新版 App SDK。安装器会检测旧版单文件 App SDK；版本不兼容时会停止安装并提示先升级 NanoKVM Go。

## 使用前准备

在 NanoKVM Go 上启用以下功能：

1. 在网页端进入 `Settings > Device > Virtual Audio`，打开虚拟音频；
2. 在网页端进入 `Settings > AI > MCP Service`，打开 MCP 服务；也可以通过设备触摸屏第二页打开 MCP Service；
3. 确认 `/etc/kvm/kvm_ui.toml` 中 `launcher.enabled = true`；
4. 记录 MCP API key，后续在网页 Apps 配置中填写。

手机通话媒体目前无法通过 DP 音频通道传输，需要启用 USB 虚拟音频才能由 NanoKVM Go 接收。

还需要准备 Qwen Audio Realtime 的 Workspace ID 和 API key。

## 音频与连接约定

- MCP 地址：`https://127.0.0.1/api/mcp`；
- 扬声器方向：NanoKVM → App，WebRTC Opus 解码后转换为 Qwen 所需的 S16LE、16 kHz、单声道 PCM；
- 麦克风方向：Qwen 输出 S16LE、24 kHz、单声道 PCM，由 aiortc 转换并通过 WebRTC Opus/RTP 发送；
- aiortc 负责 Opus 编码和 RTP 发送节拍；
- 配置：`app.json` 内的 `env` 表，由网页 Settings > Apps 编辑；
- Python 依赖安装在 App 私有目录 `/kvmcomm/apps/voice-bridge/python`，不覆盖系统 Python 包。

MCP 只负责认证、创建和关闭短期媒体会话，连续音频始终通过 WebRTC 传输。

## 部署

在网页 **Settings > Apps** 中从 Sipeed 官方 App Server 安装 Voice Bridge。
`app.json` 声明的 `pre_script` 会自动安装 apt 编译依赖，并把固定版本的
Python 依赖安装到 App 私有 `python/` 目录。用户不需要使用 SSH，也不需要
手动运行 apt 或 pip。

设备上的最终目录为：

```text
/kvmcomm/apps/voice-bridge/app.json
/kvmcomm/apps/voice-bridge/main.py
/kvmcomm/apps/voice-bridge/python/
```

## 配置

网页安装过程中直接填写 Voice Bridge 的环境变量。主要配置项：

必填凭据是 `NANOKVM_MCP_KEY`、`QWEN_WORKSPACE_ID` 和 `QWEN_API_KEY`。其他运行参数及原示例值已经作为 `app.json.env` 的默认值提供。

`INTERACT_TYPE` 支持 `server_vad` 和 `smart_turn`。多行或包含特殊字符的 instructions 可以使用 UTF-8 Base64 编码后写入 `QWEN_INSTRUCTIONS_B64`。

Launcher 将网页保存的值注入 App 进程，`@app()` 再以只读 `ctx.env` 暴露给应用。Voice Bridge 不再读取任何 `.env` 文件。

等待应用出现在 NanoKVM Go 屏幕的 Apps 页面后打开 `Voice Bridge`，无需重启 `kvmcomm`。

Apps 主进程会设置 framebuffer 方向、接管触摸退出手势，并在应用结束后恢复 NanoKVM Go 主界面。不要在主界面运行期间手动执行 `main.py`，否则两个进程会同时操作 framebuffer 和触摸设备。

## Qwen 会话轮换

Qwen WebSocket 可能因长时间没有生成回复而触发空闲超时。应用默认每 120 秒主动创建新的 Qwen session：

```text
MCP media session       保持
WebRTC PeerConnection   保持
speaker/microphone 轨道 保持
Qwen WebSocket          单独轮换
```

可通过 `QWEN_SESSION_ROTATE_SECONDS` 调整轮换周期。轮换 Qwen session 会清空云端对话上下文，但不会中断 NanoKVM 音频轨道。

## 当前限制

- 应用是前台程序，退出后不会继续提供语音桥接；
- 当前设备端版本没有应用层 AEC；如果模型回复会回灌到输入，应避免被控机扬声器回放，或使用带 AEC 的外部 Bridge；
- 轮换 Qwen session 后不会自动恢复之前的云端对话上下文；
- `pre_script` 中的 ARM wheel 和依赖版本与目标系统 Python ABI 有关，升级系统后需要重新验证。

## 故障排查

### 应用没有收到手机声音

确认 `Virtual Audio` 已打开，并检查手机是否把通话音频路由到 USB 音频设备。

### MCP 初始化失败

确认 MCP Service 已打开，并在网页 Settings > Apps 中确认 `NANOKVM_MCP_KEY` 已正确配置。

### Apps 页面没有 Voice Bridge

确认 `/kvmcomm/apps/voice-bridge/main.py`、`app.json` 和共享 `appbase.py` 都存在，并确认 `launcher.enabled = true`，然后等待最多 10 秒自动刷新。

### Qwen 能识别但被控机听不到回复

先确认被控系统已经选择 NanoKVM Go UAC2 虚拟麦克风，再检查 Qwen 是否产生音频输出以及 WebRTC PeerConnection 是否仍处于 connected 状态。
