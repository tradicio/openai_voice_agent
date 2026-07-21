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
    """Feeds scripted events into receive(), then raises to end the loop.

    ``send`` records each outbound message as a parsed dict.
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


def test_reset_play_stream_drops_buffered_audio_on_barge_in():
    # On barge-in, reset_stream(play_stream_only=True) must drop buffered
    # assistant audio; if it no-ops, playback won't stop on interrupt.
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    wrapper._play_stream.write(_client_frame(480))
    assert wrapper._play_stream.samples == 480

    wrapper.reset_stream(play_stream_only=True)
    assert wrapper._play_stream.samples == 0


async def test_barge_in_stops_playback_during_audio_tail():
    # Audio outlasts the transcript by seconds, so a barge-in during the
    # audio tail must still stop playback and signal clear_audio.
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    wrapper._current_item_id = "item_A"
    wrapper._played_samples = 4800
    wrapper._play_stream.write(_client_frame(9600))  # buffered, not yet sent

    ws = FakeWebSocket([
        {"type": "input_audio_buffer.speech_started"},
    ])
    with pytest.raises(TerminateTaskGroup):
        await wrapper.receive(ws)

    # The WS layer learns to send clear_audio via consume_barge_in().
    assert wrapper.consume_barge_in() is True
    # And the server-side backlog must be dropped so it can't keep streaming.
    assert wrapper._play_stream.samples == 0


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


async def test_barge_in_sends_truncate_before_cancel():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    wrapper._current_item_id = "item_A"
    wrapper._current_content_index = 0
    wrapper._played_samples = 4800  # 100ms at 48kHz

    ws = FakeWebSocket([
        {
            "type": "response.output_audio_transcript.delta",
            "delta": "Hi",
            "response_id": "resp_1",
        },
        {"type": "input_audio_buffer.speech_started"},
    ])

    with pytest.raises(TerminateTaskGroup):
        await wrapper.receive(ws)

    types = [m["type"] for m in ws.sent]
    assert "conversation.item.truncate" in types
    assert "response.cancel" in types
    assert types.index("conversation.item.truncate") < types.index(
        "response.cancel"
    )
    truncate = next(
        m for m in ws.sent if m["type"] == "conversation.item.truncate"
    )
    assert truncate["item_id"] == "item_A"
    assert truncate["content_index"] == 0
    assert truncate["audio_end_ms"] == 100


async def test_barge_in_without_playback_skips_truncate():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    wrapper._current_item_id = "item_A"
    wrapper._current_content_index = 0
    wrapper._played_samples = 0  # nothing heard yet

    ws = FakeWebSocket([
        {
            "type": "response.output_audio_transcript.delta",
            "delta": "Hi",
            "response_id": "resp_1",
        },
        {"type": "input_audio_buffer.speech_started"},
    ])

    with pytest.raises(TerminateTaskGroup):
        await wrapper.receive(ws)

    types = [m["type"] for m in ws.sent]
    assert "conversation.item.truncate" not in types
    assert "response.cancel" in types


def test_get_or_create_item_assigns_incrementing_seq_once():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")

    first = wrapper._get_or_create_item("item_A", "user")
    second = wrapper._get_or_create_item("item_B", "assistant")
    again = wrapper._get_or_create_item("item_A", "user")

    assert first["seq"] == 0
    assert first["role"] == "user"
    assert first["status"] == "in_progress"
    assert second["seq"] == 1
    # Same id returns the same record; seq is not reassigned.
    assert again is first
    assert first["seq"] == 0
    # Insertion order is creation order.
    assert list(wrapper._items.keys()) == ["item_A", "item_B"]


async def test_user_row_created_before_assistant_reply():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    ws = FakeWebSocket([
        {"type": "input_audio_buffer.speech_started", "item_id": "user_1"},
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_1", "response_id": "resp_1", "delta": "Hi "},
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_1", "response_id": "resp_1", "delta": "there"},
        {"type": "response.output_audio_transcript.done",
         "item_id": "asst_1", "transcript": "Hi there"},
        {"type": "conversation.item.input_audio_transcription.completed",
         "item_id": "user_1", "transcript": "Hello"},
    ])

    with pytest.raises(TerminateTaskGroup):
        await wrapper.receive(ws)

    user = wrapper._items["user_1"]
    asst = wrapper._items["asst_1"]
    # User row was reserved first, so it sorts ahead of the assistant reply.
    assert user["seq"] < asst["seq"]
    assert user["role"] == "user"
    assert user["text"] == "Hello"
    assert user["status"] == "done"
    assert asst["role"] == "assistant"
    assert asst["text"] == "Hi there"
    assert asst["status"] == "done"


async def test_input_transcription_delta_accumulates():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    ws = FakeWebSocket([
        {"type": "input_audio_buffer.speech_started", "item_id": "user_1"},
        {"type": "conversation.item.input_audio_transcription.delta",
         "item_id": "user_1", "delta": "Hel"},
        {"type": "conversation.item.input_audio_transcription.delta",
         "item_id": "user_1", "delta": "lo"},
        {"type": "conversation.item.input_audio_transcription.completed",
         "item_id": "user_1", "transcript": "Hello"},
    ])

    with pytest.raises(TerminateTaskGroup):
        await wrapper.receive(ws)

    # Deltas already built the text; completed must not double it (append-only).
    assert wrapper._items["user_1"]["text"] == "Hello"
    assert wrapper._items["user_1"]["status"] == "done"


async def test_barge_in_marks_prior_assistant_row_interrupted_and_starts_new_row():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    wrapper._current_item_id = "asst_1"  # audio item currently playing
    ws = FakeWebSocket([
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_1", "response_id": "resp_1", "delta": "Let me expl"},
        {"type": "input_audio_buffer.speech_started", "item_id": "user_1"},
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_2", "response_id": "resp_2", "delta": "New answer"},
    ])

    with pytest.raises(TerminateTaskGroup):
        await wrapper.receive(ws)

    assert wrapper._items["asst_1"]["status"] == "interrupted"
    assert wrapper._items["asst_1"]["text"] == "Let me expl"
    # A distinct row for the new response; not merged into asst_1.
    assert "asst_2" in wrapper._items
    assert wrapper._items["asst_2"]["text"] == "New answer"
    assert wrapper._items["asst_1"]["seq"] != wrapper._items["asst_2"]["seq"]
    # response.cancel was sent on barge-in.
    assert any(m.get("type") == "response.cancel" for m in ws.sent)


async def test_valid_messages_orders_by_seq_and_drops_empty():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    ws = FakeWebSocket([
        {"type": "input_audio_buffer.speech_started", "item_id": "user_1"},
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_1", "response_id": "resp_1", "delta": "Hi"},
        {"type": "conversation.item.input_audio_transcription.completed",
         "item_id": "user_1", "transcript": "Hello"},
    ])

    with pytest.raises(TerminateTaskGroup):
        await wrapper.receive(ws)

    assert wrapper.valid_messages == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
    ]
