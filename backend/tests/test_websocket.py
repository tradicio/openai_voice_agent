import asyncio
import json

import av
import pytest
from api import websocket as ws_module
from fastapi.testclient import TestClient
from main import app
from starlette.websockets import WebSocketDisconnect

from src.realtime.config import (
    API_CHANNELS,
    API_SAMPLE_RATE,
    API_SAMPLE_WIDTH,
    CLIENT_CHANNELS,
    CLIENT_SAMPLE_RATE,
    CLIENT_SAMPLE_WIDTH,
    FORMAT_MAPPING,
    LAYOUT_MAPPING,
)

client = TestClient(app)
ORIGIN_HEADERS = {"origin": "http://localhost:3000"}


class FakeAPIWrapper:
    """A network-free stand-in for OpenAIRealtimeAPIWrapper.

    Mirrors just the surface AudioStreamSession relies on so tests can
    exercise the WebSocket message-handling/session lifecycle without
    opening a real connection to the OpenAI Realtime API.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.recording = False
        self._items: dict[str, dict] = {}
        self._played_samples = 0
        self._resampler_for_api = av.audio.resampler.AudioResampler(
            format=FORMAT_MAPPING[API_SAMPLE_WIDTH],
            layout=LAYOUT_MAPPING[API_CHANNELS],
            rate=API_SAMPLE_RATE,
        )
        self._resampler_for_client = av.audio.resampler.AudioResampler(
            format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
            layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
            rate=CLIENT_SAMPLE_RATE,
        )
        self._record_stream = None
        self._play_stream = None

    async def run(self):
        self.recording = True
        while self.recording:
            await asyncio.sleep(0.01)

    def stop(self):
        self.recording = False

    def consume_barge_in(self) -> bool:
        return False

    def read_play_audio(self, nsamples, partial=True):
        frame = self._play_stream.read(nsamples, partial=partial)
        if frame:
            self._played_samples += frame.samples
        return frame

    def set_session_timeout(self, timeout):
        self.session_timeout = timeout

    def set_instructions(self, instructions):
        self.instructions = instructions


class FakeAPIWrapperWithBargeIn(FakeAPIWrapper):
    """Signals a single barge-in event on the first check."""

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self._barge_in_signaled = False

    def consume_barge_in(self) -> bool:
        if not self._barge_in_signaled:
            self._barge_in_signaled = True
            return True
        return False


@pytest.fixture(autouse=True)
def openai_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")


def test_rejects_missing_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        data = ws.receive_json()
        assert data["type"] == "status"
        assert "not set" in data["message"]


def test_rejects_disallowed_origin():
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/audio", headers={"origin": "http://evil.example.com"}
        ) as ws:
            ws.receive_text()


def test_rejects_malformed_message():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text("not valid json")
        data = ws.receive_json()
        assert data == {"type": "status", "message": "Invalid message"}


def test_rejects_unknown_message_type():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "not_a_real_type"}))
        data = ws.receive_json()
        assert data == {"type": "status", "message": "Invalid message"}


def test_rejects_oversized_message():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        oversized = json.dumps(
            {"type": "audio", "data": "a" * (200 * 1024)}
        )
        ws.send_text(oversized)
        data = ws.receive_json()
        assert data == {"type": "status", "message": "Message too large"}


def test_config_updates_timeout():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "config", "timeout": 200}))
        data = ws.receive_json()
        assert data == {"type": "status", "message": "Timeout updated"}


def test_config_unknown_prompt_key_is_reported():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(
            json.dumps({"type": "config", "prompt_key": "does-not-exist"})
        )
        data = ws.receive_json()
        assert data["type"] == "status"
        assert "not found" in data["message"]


def test_audio_frame_ignored_when_not_recording():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "audio", "data": "AAAA"}))
        # Frame is dropped (no active conversation); the config message
        # confirms the handler loop is still alive.
        ws.send_text(json.dumps({"type": "config", "timeout": 90}))
        data = ws.receive_json()
        assert data == {"type": "status", "message": "Timeout updated"}


def test_start_and_stop_conversation(monkeypatch):
    monkeypatch.setattr(ws_module, "OpenAIRealtimeAPIWrapper", FakeAPIWrapper)
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "control", "action": "start"}))
        assert ws.receive_json() == {
            "type": "status", "message": "Starting conversation..."
        }

        ws.send_text(json.dumps({"type": "control", "action": "stop"}))
        assert ws.receive_json() == {
            "type": "status", "message": "Conversation ended"
        }


def test_barge_in_triggers_clear_audio(monkeypatch):
    monkeypatch.setattr(
        ws_module, "OpenAIRealtimeAPIWrapper", FakeAPIWrapperWithBargeIn
    )
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "control", "action": "start"}))
        assert ws.receive_json() == {
            "type": "status", "message": "Starting conversation..."
        }

        assert ws.receive_json() == {"type": "clear_audio"}

        ws.send_text(json.dumps({"type": "control", "action": "stop"}))
        assert ws.receive_json() == {
            "type": "status", "message": "Conversation ended"
        }


class FakeAPIWrapperWithItems(FakeAPIWrapper):
    """Exposes preset transcript items so the monitor forwards them once."""

    async def run(self):
        self.recording = True
        self._items = {
            "user_1": {"role": "user", "text": "Hello", "seq": 0,
                       "status": "done"},
            "asst_1": {"role": "assistant", "text": "Hi there", "seq": 1,
                       "status": "done"},
        }
        while self.recording:
            await asyncio.sleep(0.01)


def test_monitor_forwards_seq_keyed_transcripts(monkeypatch):
    monkeypatch.setattr(
        ws_module, "OpenAIRealtimeAPIWrapper", FakeAPIWrapperWithItems
    )
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "control", "action": "start"}))
        assert ws.receive_json() == {
            "type": "status", "message": "Starting conversation..."
        }

        transcripts = {}
        # Collect the two forwarded transcript messages (ignore any audio).
        while len(transcripts) < 2:
            msg = ws.receive_json()
            if msg.get("type") == "transcript":
                transcripts[msg["seq"]] = msg

        assert transcripts[0] == {
            "type": "transcript", "role": "user", "seq": 0, "delta": "Hello"
        }
        assert transcripts[1] == {
            "type": "transcript", "role": "assistant", "seq": 1,
            "delta": "Hi there"
        }

        ws.send_text(json.dumps({"type": "control", "action": "stop"}))
