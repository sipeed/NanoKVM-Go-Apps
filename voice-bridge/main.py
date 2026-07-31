#!/usr/bin/env python3
"""NanoKVM framebuffer App: localhost MCP/WebRTC <-> Qwen Audio Realtime."""

import asyncio
import base64
import json
import signal
import ssl
import sys
import threading
import time
import urllib.request
from fractions import Fraction
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR / "python"))

from aiortc import AudioStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.sdp import candidate_from_sdp
from av import AudioFrame, AudioResampler
from websockets.asyncio.client import connect as websocket_connect

from appbase import BLACK, CYAN, DKGRAY, GREEN, RED, WHITE, YELLOW, app

MCP_URL = "https://127.0.0.1/api/mcp"
QWEN_INPUT_BYTES = 16000 * 2 // 10
DEFAULT_QWEN_ROTATE_SECONDS = 120
APP_ENV = {}


class Status:
    def __init__(self):
        self.lock = threading.Lock()
        self.state = "STARTING"
        self.detail = "Loading configuration"
        self.user = ""
        self.qwen = ""
        self.user_updated = time.monotonic()
        self.qwen_updated = time.monotonic()
        self.input_level = 0
        self.output_level = 0

    def set(self, state=None, detail=None, user=None, qwen=None):
        with self.lock:
            if state is not None:
                self.state = state
            if detail is not None:
                self.detail = detail
            if user is not None:
                self.user = user
                self.user_updated = time.monotonic()
            if qwen is not None:
                self.qwen = qwen
                self.qwen_updated = time.monotonic()

    def snapshot(self):
        with self.lock:
            return (self.state, self.detail, self.user, self.qwen,
                    self.user_updated, self.qwen_updated,
                    self.input_level, self.output_level)


class MCPClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.session_id = ""
        self.request_id = 0
        self.ssl_context = ssl._create_unverified_context()

    def _request(self, method, params=None, initialize=False, notification=False, timeout=15):
        self.request_id += 1
        payload = {"jsonrpc": "2.0", "method": method}
        if not notification:
            payload["id"] = self.request_id
        if params is not None:
            payload["params"] = params
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if not initialize:
            headers["Mcp-Session-Id"] = self.session_id
        request = urllib.request.Request(MCP_URL, json.dumps(payload).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(request, context=self.ssl_context, timeout=timeout) as response:
            if initialize:
                self.session_id = response.headers.get("Mcp-Session-Id", "")
                if not self.session_id:
                    raise RuntimeError("MCP returned no session ID")
            body = response.read().decode()
        for line in body.splitlines():
            if line.startswith("data:"):
                body = line[5:].strip()
                break
        if notification and not body.strip():
            return None
        result = json.loads(body)
        if result.get("error"):
            raise RuntimeError("MCP: " + str(result["error"]))
        return result.get("result")

    async def initialize(self):
        await asyncio.to_thread(self._request, "initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "nanokvm-voice-app", "version": "0.1.0"},
        }, True)
        await asyncio.to_thread(self._request, "notifications/initialized", {}, False, True)

    def _call(self, name, arguments, timeout=15):
        result = self._request(
            "tools/call", {"name": name, "arguments": arguments}, timeout=timeout
        )
        if result.get("isError"):
            raise RuntimeError(result.get("content", [{}])[0].get("text", name + " failed"))
        text = result.get("content", [{}])[0].get("text", "{}")
        return json.loads(text)

    async def create_media(self):
        return await asyncio.to_thread(self._call, "media_session_create", {
            "speakerReceive": True, "micSend": True, "ttlSeconds": 600,
        })

    async def close_media(self, token):
        try:
            await asyncio.to_thread(
                self._call, "media_session_close", {"token": token}, 0.25
            )
        except Exception:
            pass


def pcm_peak(data):
    peak = 0
    for index in range(0, len(data) - 1, 2):
        value = int.from_bytes(data[index:index + 2], "little", signed=True)
        peak = max(peak, abs(value))
    return peak / 32768


class QwenOutputTrack(AudioStreamTrack):
    kind = "audio"

    def __init__(self, status):
        super().__init__()
        self.status = status
        self.queue = asyncio.Queue(maxsize=25)
        self.pending = bytearray()
        self.pts = 0

    def push(self, pcm):
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.queue.put_nowait(pcm)

    def flush(self):
        self.pending.clear()
        while True:
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def recv(self):
        samples = 480  # 20 ms at Qwen's 24 kHz output rate.
        needed = samples * 2
        while len(self.pending) < needed:
            try:
                self.pending.extend(await asyncio.wait_for(self.queue.get(), 0.02))
            except asyncio.TimeoutError:
                self.pending.extend(b"\0" * (needed - len(self.pending)))
        data = bytes(self.pending[:needed])
        del self.pending[:needed]
        self.status.output_level = pcm_peak(data)
        frame = AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(data)
        frame.sample_rate = 24000
        frame.pts = self.pts
        frame.time_base = Fraction(1, 24000)
        self.pts += samples
        return frame


class QwenSession:
    def __init__(self, status, output_track):
        self.status = status
        self.output_track = output_track
        self.ws = None
        self.send_queue = asyncio.Queue(maxsize=12)
        self.responding = False

    async def open(self):
        workspace = required("QWEN_WORKSPACE_ID")
        api_key = required("QWEN_API_KEY")
        region = env_value("QWEN_REGION", "cn-beijing")
        model = env_value("QWEN_MODEL", "qwen-audio-3.0-realtime-flash")
        endpoint = "wss://%s.%s.maas.aliyuncs.com/api-ws/v1/realtime?model=%s" % (workspace, region, model)
        self.ws = await websocket_connect(endpoint, additional_headers={"Authorization": "Bearer " + api_key}, ping_interval=30, ping_timeout=30)
        event = json.loads(await self.ws.recv())
        if event.get("type") != "session.created":
            raise RuntimeError("expected session.created: " + str(event))
        instructions = env_value("QWEN_INSTRUCTIONS", "You are a concise voice assistant.")
        if env_value("QWEN_INSTRUCTIONS_B64"):
            instructions = base64.b64decode(env_value("QWEN_INSTRUCTIONS_B64")).decode("utf-8")
        await self.ws.send(json.dumps({"type": "session.update", "session": {
            "modalities": ["text", "audio"],
            "voice": env_value("QWEN_VOICE", "longanqian"),
            "instructions": instructions,
            "input_audio_format": "pcm", "output_audio_format": "pcm",
            "turn_detection": {"type": env_value("INTERACT_TYPE", "server_vad")},
        }}))

    def push_input(self, pcm):
        if self.send_queue.full():
            try:
                self.send_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        self.send_queue.put_nowait(pcm)

    async def writer(self):
        while True:
            pcm = await self.send_queue.get()
            await self.ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()}))

    async def reader(self):
        async for raw in self.ws:
            event = json.loads(raw)
            kind = event.get("type", "")
            if kind == "response.created":
                self.responding = True
            elif kind == "response.audio.delta":
                data = base64.b64decode(event.get("delta", ""))
                if data:
                    self.output_track.push(data)
            elif kind in ("response.done", "response.cancelled"):
                self.responding = False
            elif kind == "input_audio_buffer.speech_started":
                self.output_track.flush()
                if self.responding:
                    await self.ws.send(json.dumps({"type": "response.cancel"}))
                self.status.set(detail="User speaking / Qwen interrupted")
            elif kind == "conversation.item.input_audio_transcription.completed":
                self.status.set(user=str(event.get("transcript", "")))
            elif kind == "response.audio_transcript.done":
                self.status.set(qwen=str(event.get("transcript", "")))
            elif kind == "error":
                self.status.set(detail="Qwen error: " + str(event.get("error", "")))

    async def close(self):
        if self.ws:
            await self.ws.close()


class QwenInputRouter:
    """Keeps the WebRTC receive track stable while Qwen sessions rotate."""

    def __init__(self):
        self.session = None

    def attach(self, session):
        self.session = session

    def detach(self, session):
        if self.session is session:
            self.session = None

    def push_input(self, pcm):
        if self.session is not None:
            self.session.push_input(pcm)


async def supervise_qwen(router, status, output_track):
    rotate_seconds = max(30, int(env_value(
        "QWEN_SESSION_ROTATE_SECONDS", str(DEFAULT_QWEN_ROTATE_SECONDS))))
    retry_seconds = 1
    while True:
        qwen = QwenSession(status, output_track)
        tasks = []
        started = time.monotonic()
        try:
            status.set(detail="Connecting Qwen realtime")
            await qwen.open()
            router.attach(qwen)
            status.set(detail="NanoKVM + Qwen online")
            writer = asyncio.create_task(qwen.writer())
            reader = asyncio.create_task(qwen.reader())
            rotation = asyncio.create_task(asyncio.sleep(rotate_seconds))
            tasks = [writer, reader, rotation]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if rotation in done:
                status.set(detail="Refreshing Qwen session")
                retry_seconds = 1
            else:
                for task in done:
                    await task
                raise RuntimeError("Qwen WebSocket ended")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            status.set(detail="Qwen retry in %ds: %s" % (retry_seconds, shorten(str(error), 20)))
            if time.monotonic() - started > 30:
                retry_seconds = 1
            await asyncio.sleep(retry_seconds)
            retry_seconds = min(16, retry_seconds * 2)
        finally:
            router.detach(qwen)
            output_track.flush()
            for task in tasks:
                task.cancel()
            close_task = asyncio.create_task(qwen.close())
            _, pending = await asyncio.wait([close_task], timeout=0.3)
            for task in pending:
                task.cancel()
            await asyncio.gather(*(tasks + [close_task]), return_exceptions=True)


async def receive_speaker(track, router, status):
    resampler = AudioResampler(format="s16", layout="mono", rate=16000)
    pending = bytearray()
    while True:
        frame = await track.recv()
        for converted in resampler.resample(frame):
            data = bytes(converted.planes[0])[: converted.samples * 2]
            status.input_level = pcm_peak(data)
            pending.extend(data)
            while len(pending) >= QWEN_INPUT_BYTES:
                router.push_input(bytes(pending[:QWEN_INPUT_BYTES]))
                del pending[:QWEN_INPUT_BYTES]


async def connect_media(session, status, output_track):
    pc = RTCPeerConnection()
    speaker_tasks = []
    qwen_router = QwenInputRouter()
    pc.addTransceiver("audio", direction="recvonly")
    pc.addTrack(output_track)

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            speaker_tasks.append(asyncio.create_task(receive_speaker(track, qwen_router, status)))

    path = session["signalingPath"]
    signal_url = "wss://127.0.0.1" + path
    ws = await websocket_connect(signal_url, ssl=ssl._create_unverified_context(), ping_interval=30, ping_timeout=30)
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    await ws.send(json.dumps({"event": "offer", "data": json.dumps({"type": pc.localDescription.type, "sdp": pc.localDescription.sdp})}))

    async def signaling():
        async for raw in ws:
            message = json.loads(raw)
            data = json.loads(message.get("data", "{}"))
            if message.get("event") == "answer":
                await pc.setRemoteDescription(RTCSessionDescription(sdp=data["sdp"], type=data["type"]))
                status.set(state="CONNECTED", detail="NanoKVM + Qwen online")
            elif message.get("event") == "candidate" and data.get("candidate"):
                candidate = candidate_from_sdp(data["candidate"].split(":", 1)[-1])
                candidate.sdpMid = data.get("sdpMid")
                candidate.sdpMLineIndex = data.get("sdpMLineIndex")
                await pc.addIceCandidate(candidate)
        raise RuntimeError("WebRTC signaling ended")

    tasks = [asyncio.create_task(signaling()), asyncio.create_task(supervise_qwen(qwen_router, status, output_track))]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks + speaker_tasks:
            task.cancel()
        close_tasks = [
            asyncio.create_task(ws.close()),
            asyncio.create_task(pc.close()),
        ]
        _, pending = await asyncio.wait(close_tasks, timeout=0.5)
        for task in pending:
            task.cancel()
        await asyncio.gather(*(tasks + speaker_tasks + close_tasks), return_exceptions=True)


def required(name):
    value = env_value(name).strip()
    if not value:
        raise RuntimeError(name + " is missing from App environment configuration")
    return value


def env_value(name, default=""):
    return APP_ENV.get(name, default)


async def bridge(status, stop):
    mcp = MCPClient(required("NANOKVM_MCP_KEY"))
    status.set(state="STARTING", detail="Initializing localhost MCP")
    await mcp.initialize()
    retry_seconds = 1
    first_connection = True

    while not stop.is_set():
        token = ""
        tasks = []
        started = time.monotonic()
        try:
            status.set(state="STARTING" if first_connection else "RECONNECTING",
                       detail="Creating MCP media session")
            session = await mcp.create_media()
            token = session["token"]
            output_track = QwenOutputTrack(status)
            media_task = asyncio.create_task(connect_media(session, status, output_track))
            stop_task = asyncio.create_task(stop.wait())
            tasks = [media_task, stop_task]
            first_connection = False
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

            if stop_task in done:
                return
            if media_task in done:
                await media_task
                raise RuntimeError("media session ended")

        except asyncio.CancelledError:
            raise
        except Exception as error:
            status.set(state="RECONNECTING", detail="Retry in %ds: %s" % (retry_seconds, shorten(str(error), 24)))
            if time.monotonic() - started > 30:
                retry_seconds = 1
            try:
                await asyncio.wait_for(stop.wait(), retry_seconds)
                return
            except asyncio.TimeoutError:
                retry_seconds = min(16, retry_seconds * 2)
        finally:
            for task in tasks:
                task.cancel()
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=0.5)
                for task in pending:
                    task.cancel()
            if token:
                try:
                    await asyncio.wait_for(mcp.close_media(token), timeout=0.4)
                except asyncio.TimeoutError:
                    pass


def shorten(text, maximum=33):
    text = " ".join(text.split())
    return text if len(text) <= maximum else text[:maximum - 1] + "…"


def wrap_text(text, width):
    """Wrap English on words and CJK text on character boundaries."""
    remaining = " ".join(text.split())
    lines = []
    while remaining:
        if len(remaining) <= width:
            lines.append(remaining)
            break
        cut = width
        space = remaining.rfind(" ", 0, width + 1)
        if space >= width // 2:
            cut = space
        lines.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return lines or [""]


def scrolling_lines(text, updated, width=27, visible=2):
    lines = wrap_text(text, width)
    if len(lines) <= visible:
        return lines + [""] * (visible - len(lines))
    elapsed = max(0.0, time.monotonic() - updated - 1.5)
    first = min(int(elapsed / 1.2), len(lines) - visible)
    return lines[first:first + visible]


def draw(ctx, status):
    (state, detail, user, qwen, user_updated, qwen_updated,
     input_level, output_level) = status.snapshot()
    fb = ctx.fb
    fb.clear(BLACK)
    color = GREEN if state == "CONNECTED" else RED if state == "ERROR" else YELLOW
    left = 18 if fb.rotate == 0 else 10
    top = 18 if fb.rotate == 270 else 12
    right = ctx.width - (18 if fb.rotate == 180 else 10)
    fb.draw_text(left, top, "VOICE BRIDGE", WHITE, 2)
    fb.draw_text(left, top + 30, state, color, 2)
    detail_width = max(1, (right - left) // 8)
    fb.draw_text(left, top + 56, shorten(detail, detail_width), DKGRAY, 1)
    fb.draw_text(left, top + 79, "USER", CYAN, 1)
    for index, line in enumerate(scrolling_lines(user or "Listening...", user_updated)):
        fb.draw_text(left, top + 93 + index * 11, line, WHITE, 1)
    fb.draw_text(left, top + 127, "QWEN", YELLOW, 1)
    for index, line in enumerate(scrolling_lines(qwen or "Waiting...", qwen_updated)):
        fb.draw_text(left, top + 141 + index * 11, line, WHITE, 1)
    meter_x = left + 24
    meter_width = max(1, right - meter_x)
    fb.draw_text(left, top + 178, "IN", CYAN, 1)
    fb.fill_rect(meter_x, top + 179, int(meter_width * input_level), 7, CYAN)
    fb.draw_text(left, top + 198, "OUT", YELLOW, 1)
    fb.fill_rect(meter_x, top + 199, int(meter_width * output_level), 7, YELLOW)
    fb.flush()


@app()
def main(ctx):
    global APP_ENV
    APP_ENV = dict(ctx.env)
    status = Status()
    stop = asyncio.Event()

    def request_stop(_signum, _frame):
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    async def run():
        task = asyncio.create_task(bridge(status, stop))
        try:
            while not task.done():
                draw(ctx, status)
                await asyncio.sleep(0.1)
            await task
        except Exception as error:
            status.set(state="ERROR", detail=str(error))
            for _ in range(50):
                draw(ctx, status)
                await asyncio.sleep(0.1)
        finally:
            stop.set()

    asyncio.run(run())


if __name__ == "__main__":
    main()
