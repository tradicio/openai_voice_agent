import base64

from src.audio.formats import API_CHANNELS, API_SAMPLE_WIDTH
from src.realtime import OpenAIRealtimeAPIWrapper


class FakeWebSocket:
    """Records outbound messages as parsed dicts."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, data):
        import json
        self.sent.append(json.loads(data))


def _wired():
    """A started wrapper plus its dispatcher and a fake API socket."""
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.start()
    return wrapper, wrapper._dispatcher, FakeWebSocket()


def _rows(wrapper):
    return dict(wrapper.transcript_snapshot())


async def test_audio_delta_tracks_item_and_resets_counter():
    wrapper, d, ws = _wired()
    wrapper._audio.played_samples = 5000  # leftover from a previous item
    pcm = b"\x00" * (240 * API_SAMPLE_WIDTH * API_CHANNELS)
    await d.dispatch({
        "type": "response.output_audio.delta",
        "delta": base64.b64encode(pcm).decode("utf-8"),
        "item_id": "item_B",
        "content_index": 0,
        "response_id": "resp_1",
    }, ws)
    assert wrapper._turn.current_item_id == "item_B"
    assert wrapper._turn.current_content_index == 0
    assert wrapper._audio.played_samples == 0


async def test_barge_in_sends_truncate_before_cancel():
    wrapper, d, ws = _wired()
    wrapper._turn.current_item_id = "item_A"
    wrapper._turn.current_content_index = 0
    wrapper._audio.played_samples = 4800  # 100ms at 48kHz
    await d.dispatch({
        "type": "response.output_audio_transcript.delta",
        "delta": "Hi", "response_id": "resp_1",
    }, ws)
    await d.dispatch({"type": "input_audio_buffer.speech_started"}, ws)

    types = [m["type"] for m in ws.sent]
    assert "conversation.item.truncate" in types
    assert "response.cancel" in types
    assert types.index("conversation.item.truncate") < types.index("response.cancel")
    truncate = next(m for m in ws.sent if m["type"] == "conversation.item.truncate")
    assert truncate["item_id"] == "item_A"
    assert truncate["content_index"] == 0
    assert truncate["audio_end_ms"] == 100


async def test_barge_in_without_playback_skips_truncate():
    wrapper, d, ws = _wired()
    wrapper._turn.current_item_id = "item_A"
    wrapper._turn.current_content_index = 0
    wrapper._audio.played_samples = 0  # nothing heard yet
    await d.dispatch({
        "type": "response.output_audio_transcript.delta",
        "delta": "Hi", "response_id": "resp_1",
    }, ws)
    await d.dispatch({"type": "input_audio_buffer.speech_started"}, ws)

    types = [m["type"] for m in ws.sent]
    assert "conversation.item.truncate" not in types
    assert "response.cancel" in types


async def test_barge_in_stops_playback_during_audio_tail():
    wrapper, d, ws = _wired()
    wrapper._turn.current_item_id = "item_A"
    wrapper._audio.played_samples = 4800
    wrapper._audio.write_api_pcm(b"\x00" * (240 * API_SAMPLE_WIDTH * API_CHANNELS))
    await d.dispatch({"type": "input_audio_buffer.speech_started"}, ws)

    assert wrapper.consume_barge_in() is True
    assert wrapper._audio.play_buffer_seconds() == 0


async def test_user_row_created_before_assistant_reply():
    wrapper, d, ws = _wired()
    for event in [
        {"type": "input_audio_buffer.speech_started", "item_id": "user_1"},
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_1", "response_id": "resp_1", "delta": "Hi "},
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_1", "response_id": "resp_1", "delta": "there"},
        {"type": "response.output_audio_transcript.done",
         "item_id": "asst_1", "transcript": "Hi there"},
        {"type": "conversation.item.input_audio_transcription.completed",
         "item_id": "user_1", "transcript": "Hello"},
    ]:
        await d.dispatch(event, ws)

    rows = _rows(wrapper)
    assert rows["user_1"]["seq"] < rows["asst_1"]["seq"]
    assert rows["user_1"]["role"] == "user"
    assert rows["user_1"]["text"] == "Hello"
    assert rows["user_1"]["status"] == "done"
    assert rows["asst_1"]["role"] == "assistant"
    assert rows["asst_1"]["text"] == "Hi there"
    assert rows["asst_1"]["status"] == "done"


async def test_input_transcription_delta_accumulates():
    wrapper, d, ws = _wired()
    for event in [
        {"type": "input_audio_buffer.speech_started", "item_id": "user_1"},
        {"type": "conversation.item.input_audio_transcription.delta",
         "item_id": "user_1", "delta": "Hel"},
        {"type": "conversation.item.input_audio_transcription.delta",
         "item_id": "user_1", "delta": "lo"},
        {"type": "conversation.item.input_audio_transcription.completed",
         "item_id": "user_1", "transcript": "Hello"},
    ]:
        await d.dispatch(event, ws)

    rows = _rows(wrapper)
    assert rows["user_1"]["text"] == "Hello"
    assert rows["user_1"]["status"] == "done"


async def test_barge_in_marks_prior_assistant_row_interrupted_and_starts_new_row():
    wrapper, d, ws = _wired()
    wrapper._turn.current_item_id = "asst_1"  # audio item currently playing
    for event in [
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_1", "response_id": "resp_1", "delta": "Let me expl"},
        {"type": "input_audio_buffer.speech_started", "item_id": "user_1"},
        {"type": "response.output_audio_transcript.delta",
         "item_id": "asst_2", "response_id": "resp_2", "delta": "New answer"},
    ]:
        await d.dispatch(event, ws)

    rows = _rows(wrapper)
    assert rows["asst_1"]["status"] == "interrupted"
    assert rows["asst_1"]["text"] == "Let me expl"
    assert "asst_2" in rows
    assert rows["asst_2"]["text"] == "New answer"
    assert rows["asst_1"]["seq"] != rows["asst_2"]["seq"]
    assert any(m.get("type") == "response.cancel" for m in ws.sent)
