import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


def load_app():
    for name in ("aiortc", "aiortc.sdp", "av", "websockets", "websockets.asyncio", "websockets.asyncio.client", "appbase"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["aiortc"].AudioStreamTrack = object
    sys.modules["aiortc"].RTCPeerConnection = object
    sys.modules["aiortc"].RTCSessionDescription = object
    sys.modules["aiortc.sdp"].candidate_from_sdp = lambda value: value
    sys.modules["av"].AudioFrame = object
    sys.modules["av"].AudioResampler = object
    sys.modules["websockets.asyncio.client"].connect = object
    appbase = sys.modules["appbase"]
    for name in ("BLACK", "CYAN", "DKGRAY", "GREEN", "RED", "WHITE", "YELLOW"):
        setattr(appbase, name, 0)
    appbase.app = lambda: lambda function: function
    main_path = Path(__file__).resolve().parent / "main.py"
    spec = importlib.util.spec_from_file_location("voice_bridge_app", main_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TextLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = load_app()

    def test_wraps_english_words_and_chinese_characters(self):
        self.assertEqual(self.app.wrap_text("one two three four", 8), ["one two", "three", "four"])
        self.assertEqual(self.app.wrap_text("一二三四五六七八", 4), ["一二三四", "五六七八"])

    def test_scrolls_two_line_window_then_stops_at_end(self):
        text = "1111 2222 3333 4444"
        with patch.object(self.app.time, "monotonic", return_value=100):
            self.assertEqual(self.app.scrolling_lines(text, 100, width=4), ["1111", "2222"])
        with patch.object(self.app.time, "monotonic", return_value=105):
            self.assertEqual(self.app.scrolling_lines(text, 100, width=4), ["3333", "4444"])

    def test_qwen_router_switches_without_replacing_media_track(self):
        class Session:
            def __init__(self):
                self.frames = []

            def push_input(self, frame):
                self.frames.append(frame)

        router = self.app.QwenInputRouter()
        first, second = Session(), Session()
        router.attach(first)
        router.push_input(b"one")
        router.detach(first)
        router.push_input(b"drop")
        router.attach(second)
        router.push_input(b"two")
        self.assertEqual(first.frames, [b"one"])
        self.assertEqual(second.frames, [b"two"])

    def test_latest_app_manifest(self):
        manifest_path = Path(__file__).resolve().parent / "app.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for field in ("app_id", "name", "creator", "create_time", "version"):
            self.assertIsInstance(manifest.get(field), str)
            self.assertTrue(manifest[field])
        self.assertEqual(manifest["name"], "Voice Bridge")
        self.assertEqual(manifest["app_id"], "com.sipeed.voice_bridge")
        self.assertEqual(manifest["pre_script"], "pre-install.sh")
        self.assertTrue((manifest_path.parent / manifest["pre_script"]).is_file())
        env = manifest["env"]
        for name in ("NANOKVM_MCP_KEY", "QWEN_WORKSPACE_ID", "QWEN_API_KEY"):
            self.assertTrue(env[name]["required"])
        self.assertTrue(env["NANOKVM_MCP_KEY"]["secret"])
        self.assertTrue(env["QWEN_API_KEY"]["secret"])
        self.assertEqual(env["QWEN_REGION"]["default"], "cn-beijing")
        self.assertEqual(env["QWEN_MODEL"]["default"], "qwen-audio-3.0-realtime-flash")
        self.assertEqual(env["QWEN_VOICE"]["default"], "longanqian")

    def test_runtime_configuration_comes_from_app_context_mapping(self):
        self.app.APP_ENV = {"QWEN_REGION": "test-region"}
        self.assertEqual(self.app.env_value("QWEN_REGION"), "test-region")
        self.assertEqual(self.app.env_value("MISSING", "fallback"), "fallback")
        with self.assertRaisesRegex(RuntimeError, "NANOKVM_MCP_KEY"):
            self.app.required("NANOKVM_MCP_KEY")


if __name__ == "__main__":
    unittest.main()
