import asyncio
import json

import pytest
from api.ws import session as session_module
from fastapi.testclient import TestClient
from main import app
from starlette.websockets import WebSocketDisconnect

client = TestClient(app)
ORIGIN_HEADERS = {"origin": "http://localhost:3000"}


class FakeAPIWrapper:
    """A network-free stand-in for OpenAIRealtimeAPIWrapper.

    Mirrors just the public surface AudioStreamSession relies on so tests
    can exercise the WebSocket message-handling/session lifecycle without
    opening a real connection to the OpenAI Realtime API.
    """

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.recording = False
        self._transcript_items: list[tuple[str, dict]] = []

    async def run(self):
        self.recording = True
        while self.recording:
            await asyncio.sleep(0.01)

    def stop(self):
        self.recording = False

    def consume_barge_in(self) -> bool:
        return False

    def write_client_pcm(self, pcm_bytes):
        pass

    def read_client_pcm(self, nsamples, partial=True):
        return None

    def transcript_snapshot(self):
        return list(self._transcript_items)

    def set_model(self, model):
        self.model = model

    def set_voice(self, voice):
        self.voice = voice

    def set_instructions(self, instructions):
        self.instructions = instructions

    def reset_streams(self):
        pass


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


def test_config_updates_model():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "config", "model": "gpt-realtime"}))
        data = ws.receive_json()
        assert data == {"type": "status", "message": "Model updated"}


def test_config_updates_voice():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "config", "voice": "verse"}))
        data = ws.receive_json()
        assert data == {"type": "status", "message": "Voice updated"}


def test_config_unknown_model_is_reported():
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "config", "model": "does-not-exist"}))
        data = ws.receive_json()
        assert data["type"] == "status"
        assert "not found" in data["message"]


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
        ws.send_text(json.dumps({"type": "config", "model": "gpt-realtime"}))
        data = ws.receive_json()
        assert data == {"type": "status", "message": "Model updated"}


def test_start_and_stop_conversation(monkeypatch):
    monkeypatch.setattr(
        session_module, "OpenAIRealtimeAPIWrapper", FakeAPIWrapper
    )
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
        session_module, "OpenAIRealtimeAPIWrapper", FakeAPIWrapperWithBargeIn
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


class FakeAPIWrapperSelfEnding(FakeAPIWrapper):
    """Finishes its run on its own, as end_conversation / the timeout would.

    ``run`` returns without the client ever sending "stop", mirroring the
    assistant's ``end_conversation`` tool (or the session timeout) ending the
    call server-side. ``recording`` is left True to also cover the timeout
    path, where the API wrapper's own flag stays set.
    """

    async def run(self):
        self.recording = True
        await asyncio.sleep(0.05)


def test_server_ended_conversation_notifies_client(monkeypatch):
    monkeypatch.setattr(
        session_module, "OpenAIRealtimeAPIWrapper", FakeAPIWrapperSelfEnding
    )
    with client.websocket_connect("/ws/audio", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(json.dumps({"type": "control", "action": "start"}))
        assert ws.receive_json() == {
            "type": "status", "message": "Starting conversation..."
        }

        # The run finishes on its own; once buffered audio is flushed the
        # session tells the client so it can reset its UI (ignore any audio).
        msg = ws.receive_json()
        while msg.get("type") != "conversation_ended":
            msg = ws.receive_json()
        assert msg == {"type": "conversation_ended"}


class FakeAPIWrapperWithItems(FakeAPIWrapper):
    """Exposes preset transcript items so the monitor forwards them once."""

    async def run(self):
        self.recording = True
        self._transcript_items = [
            ("user_1", {"role": "user", "text": "Hello", "seq": 0,
                        "status": "done"}),
            ("asst_1", {"role": "assistant", "text": "Hi there", "seq": 1,
                        "status": "done"}),
        ]
        while self.recording:
            await asyncio.sleep(0.01)


def test_monitor_forwards_seq_keyed_transcripts(monkeypatch):
    monkeypatch.setattr(
        session_module, "OpenAIRealtimeAPIWrapper", FakeAPIWrapperWithItems
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
