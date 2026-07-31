# Voice Bridge framebuffer App

[English](./README.md) | [简体中文](./README_zh.md)

This foreground NanoKVM-Go App creates a capability-scoped media session
through the device's localhost MCP endpoint, connects its bidirectional WebRTC
audio tracks, and bridges them to Qwen Audio Realtime. Closing the App closes
Qwen, WebRTC, and the MCP media session.

It targets the current NanoKVM Go App SDK directory layout:

```text
/kvmcomm/apps/
├── appbase.py
├── appbase.pyi
└── voice-bridge/
    ├── app.json
    ├── main.py
    └── python/              # App-private dependencies
```

The target must already run a NanoKVM Go build with the manifest-based App
SDK. The installer detects the older single-file / inline-metadata SDK and
stops with an update message instead of installing an incompatible App.

## Target contract

- NanoKVM MCP: `https://127.0.0.1/api/mcp`
- Speaker: WebRTC Opus, NanoKVM to App, decoded and resampled to Qwen PCM
  S16LE/16 kHz/mono.
- Microphone: Qwen PCM S16LE/24 kHz/mono, sent as an aiortc audio track. aiortc
  performs WebRTC Opus encoding and RTP pacing.
- Configuration: the `env` table in `app.json`, edited from web Settings > Apps.
- Python packages: isolated under `/kvmcomm/apps/voice-bridge/python`.
- App metadata: `voice-bridge/app.json`; runtime entry: `voice-bridge/main.py`.
- Only the Qwen WebSocket rotates every 120 seconds by default, before the
  Qwen response-idle timeout. The MCP media session and WebRTC tracks stay
  connected. Set `QWEN_SESSION_ROTATE_SECONDS` to adjust it.

## Deploy

Enable `launcher.enabled` in `/etc/kvm/kvm_ui.toml`. Also enable Virtual Audio
and MCP Service before launching Voice Bridge.

Install Voice Bridge from the official Sipeed App Server in web
**Settings > Apps**. Its `pre_script` automatically installs the required apt
packages and pinned Python dependencies into the App-private `python/`
directory. No SSH, manual apt command, or manual pip command is required.

During installation, fill the required MCP key, Qwen Workspace ID, and Qwen
API key. Defaults are declared directly by
`app.json.env`. The Launcher injects the configured values into the App
process, and `@app()` exposes the resulting read-only mapping as `ctx.env`.
Voice Bridge does not read a `.env` file.

The MCP service must be enabled. The MCP key is only used to create and close
the short-lived media session; audio never travels through MCP.

After it appears in **Apps > Voice Bridge**, open it. The host supplies the
framebuffer orientation, owns the reserved left-edge exit gesture, and restores
the normal UI after the App exits. Do not start `main.py` beside a running UI.
