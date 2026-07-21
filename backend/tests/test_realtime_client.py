import base64
import json

import pytest

from src.audio.audio_utils import pcm_audio_to_audio_frame
from src.realtime.config import (
    API_CHANNELS,
    API_SAMPLE_WIDTH,
    CLIENT_CHANNELS,
    CLIENT_SAMPLE_RATE,
    CLIENT_SAMPLE_WIDTH,
    FORMAT_MAPPING,
    LAYOUT_MAPPING,
)
from src.realtime.realtime_client import (
    OpenAIRealtimeAPIWrapper,
    TerminateTaskGroup,
)


class FakeWebSocket:
    """Feeds scripted events into receive() then ends the loop.

    receive() loops on ``await websocket.recv()`` and breaks on any
    exception, then raises TerminateTaskGroup. Raising once the script is
    exhausted makes receive() terminate so the test can assert on what was
    sent. ``send`` records each outbound message as a parsed dict.
    """

    def __init__(self, incoming):
        self._incoming = [
            m if isinstance(m, str) else json.dumps(m) for m in incoming
        ]
        self.sent: list[dict] = []

    async def recv(self):
        if self._incoming:
            return self._incoming.pop(0)
        raise EOFError("no more scripted messages")

    async def send(self, data):
        self.sent.append(json.loads(data))


def _client_frame(nsamples: int):
    """Build `nsamples` of silent client-format (48kHz stereo s16) audio."""
    pcm = b"\x00" * (nsamples * CLIENT_SAMPLE_WIDTH * CLIENT_CHANNELS)
    return pcm_audio_to_audio_frame(
        pcm,
        format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
        layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
        sample_rate=CLIENT_SAMPLE_RATE,
    )


def test_read_play_audio_counts_samples():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    wrapper._play_stream.write(_client_frame(480))

    assert wrapper._played_samples == 0
    out = wrapper.read_play_audio(480, partial=True)
    assert out is not None
    assert wrapper._played_samples == 480


async def test_audio_delta_tracks_item_and_resets_counter():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    wrapper._played_samples = 5000  # leftover from a previous item

    # 240 samples of API-format (24kHz mono s16) silence.
    pcm = b"\x00" * (240 * API_SAMPLE_WIDTH * API_CHANNELS)
    delta = base64.b64encode(pcm).decode("utf-8")
    ws = FakeWebSocket([
        {
            "type": "response.output_audio.delta",
            "delta": delta,
            "item_id": "item_B",
            "content_index": 0,
            "response_id": "resp_1",
        },
    ])

    with pytest.raises(TerminateTaskGroup):
        await wrapper.receive(ws)

    assert wrapper._current_item_id == "item_B"
    assert wrapper._current_content_index == 0
    assert wrapper._played_samples == 0
