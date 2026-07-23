import json

import pytest
from api.ws.messenger import ClientMessenger


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)


class _BrokenWS:
    async def send_text(self, text):
        raise RuntimeError("socket dead")


async def test_send_status_emits_expected_envelope():
    ws = _FakeWS()
    await ClientMessenger(ws).send_status("hello")
    assert json.loads(ws.sent[0]) == {
        "type": "status", "message": "hello"
    }


async def test_send_transcript_emits_expected_envelope():
    ws = _FakeWS()
    await ClientMessenger(ws).send_transcript("user", 3, "hi")
    assert json.loads(ws.sent[0]) == {
        "type": "transcript", "role": "user", "seq": 3, "delta": "hi"
    }


async def test_best_effort_send_swallows_failures():
    # Must not raise even though the socket errors.
    await ClientMessenger(_BrokenWS()).send_status("hello")


async def test_raising_send_propagates_failures():
    with pytest.raises(RuntimeError):
        await ClientMessenger(_BrokenWS()).send_audio("AAAA")


async def test_send_audio_emits_expected_envelope():
    ws = _FakeWS()
    await ClientMessenger(ws).send_audio("AAAA")
    assert json.loads(ws.sent[0]) == {"type": "audio", "data": "AAAA"}


async def test_send_clear_audio_emits_expected_envelope():
    ws = _FakeWS()
    await ClientMessenger(ws).send_clear_audio()
    assert json.loads(ws.sent[0]) == {"type": "clear_audio"}


async def test_send_conversation_ended_emits_expected_envelope():
    ws = _FakeWS()
    await ClientMessenger(ws).send_conversation_ended()
    assert json.loads(ws.sent[0]) == {"type": "conversation_ended"}
