# Barge-in Truncation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On barge-in, send `conversation.item.truncate` to the OpenAI Realtime API so the model's server-side history reflects how much of the assistant's audio the user actually heard.

**Architecture:** Track the current assistant audio item's `item_id`/`content_index` from `response.output_audio.delta` events, and count how many audio samples have been drained toward the client (`_played_samples`). On `input_audio_buffer.speech_started`, if a response was in progress and audio was played, send `conversation.item.truncate` (with `audio_end_ms` derived from `_played_samples`) *before* the existing `response.cancel`. Server-facing only — no client/browser protocol changes.

**Tech Stack:** Python 3.12, `websockets`, PyAV (`av`), FastAPI, pytest + pytest-asyncio (`asyncio_mode = "auto"`).

## Global Constraints

- Python `target-version = "py312"`; `line-length = 79` (ruff `E,F,I,UP,B`). Keep lines ≤ 79 chars.
- Tests live in `backend/tests/`; pytest config has `pythonpath = ["backend"]` and `asyncio_mode = "auto"` (async test functions need **no** decorator).
- Run tests from the repo root with `uv run pytest`.
- `audio_end_ms` is derived as `round(self._played_samples / CLIENT_SAMPLE_RATE * 1000)`. `CLIENT_SAMPLE_RATE` (48000) is already imported in `src/realtime/realtime_client.py`.
- Server-facing only: do **not** change `backend/api/models.py`, the frontend, or the `clear_audio` flow.

---

### Task 1: Count audio sent to the client

Add a `_played_samples` counter and a `read_play_audio()` wrapper around the play-FIFO drain, then route both drain sites through it. This is the "sent estimate" the truncate call will use.

**Files:**
- Modify: `src/realtime/realtime_client.py` (`__init__`; add `read_play_audio`; `audio_frame_callback:114`)
- Modify: `backend/api/websocket.py` (`_stream_audio_responses:214`)
- Test: `backend/tests/test_realtime_client.py` (create)

**Interfaces:**
- Produces: `OpenAIRealtimeAPIWrapper._played_samples: int` (client-domain sample count, i.e. 48 kHz), reset elsewhere in Task 2.
- Produces: `OpenAIRealtimeAPIWrapper.read_play_audio(nsamples: int, partial: bool = True) -> av.AudioFrame | None` — drains `_play_stream` and adds the returned frame's `.samples` to `_played_samples`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_realtime_client.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_realtime_client.py::test_read_play_audio_counts_samples -v`
Expected: FAIL with `AttributeError: 'OpenAIRealtimeAPIWrapper' object has no attribute '_played_samples'` (or `read_play_audio`).

- [ ] **Step 3: Add the counter and drain wrapper**

In `src/realtime/realtime_client.py` `__init__`, right after `self._barge_in_event = asyncio.Event()`:

```python
        self._played_samples = 0
```

Add this method to `OpenAIRealtimeAPIWrapper` (e.g. just above `reset_stream`):

```python
    def read_play_audio(self, nsamples: int, partial: bool = True):
        """Drain playback audio, counting what has been sent to the client.

        Wraps ``_play_stream.read`` so the amount of assistant audio handed
        off toward the client is tracked in one place. The running total
        (``_played_samples``) is what barge-in truncation uses to tell the
        server how much of the current assistant item the user heard.

        Args:
            nsamples (int): Number of samples to read from the play FIFO.
            partial (bool): Whether a partial (< nsamples) read is allowed.
        Returns:
            av.AudioFrame | None: The drained frame, or None if empty.
        """
        frame = self._play_stream.read(nsamples, partial=partial)
        if frame:
            self._played_samples += frame.samples
        return frame
```

- [ ] **Step 4: Route the drain sites through it**

In `src/realtime/realtime_client.py` `audio_frame_callback`, change line 114 from:

```python
        new_frame = self._play_stream.read(frame.samples, partial = True)
```

to:

```python
        new_frame = self.read_play_audio(frame.samples, partial = True)
```

In `backend/api/websocket.py` `_stream_audio_responses`, change:

```python
                frame = self.api_wrapper._play_stream.read(
                    AUDIO_CHUNK_SIZE, partial=True
                )
```

to:

```python
                frame = self.api_wrapper.read_play_audio(
                    AUDIO_CHUNK_SIZE, partial=True
                )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_realtime_client.py::test_read_play_audio_counts_samples -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/realtime/realtime_client.py backend/api/websocket.py backend/tests/test_realtime_client.py
git commit -m "feat: count assistant audio sent to client for truncation"
```

---

### Task 2: Track the current assistant audio item

Capture `item_id`/`content_index` from audio deltas, reset the played counter when a new item begins, and clear the item id when a response finishes.

**Files:**
- Modify: `src/realtime/realtime_client.py` (`__init__`; `response.output_audio.delta` handler ~225; `response.done` handler ~314)
- Test: `backend/tests/test_realtime_client.py`

**Interfaces:**
- Consumes: `_played_samples` from Task 1.
- Produces: `OpenAIRealtimeAPIWrapper._current_item_id: str | None` and `_current_content_index: int`, set from the first audio delta of each new item; `_current_item_id` reset to `None` on `response.done`.
- Produces: test helper `FakeWebSocket` in `backend/tests/test_realtime_client.py`, reused by Task 3.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_realtime_client.py` (put `FakeWebSocket` near the top, below the imports, and the test with the others):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_realtime_client.py::test_audio_delta_tracks_item_and_resets_counter -v`
Expected: FAIL — `assert None == "item_B"` (attribute exists but is never set) or `AttributeError` on `_current_item_id`.

- [ ] **Step 3: Add init state**

In `src/realtime/realtime_client.py` `__init__`, right after the `self._played_samples = 0` line added in Task 1:

```python
        self._current_item_id = None
        self._current_content_index = 0
```

- [ ] **Step 4: Capture the item on audio deltas**

In the `response.output_audio.delta` handler, inside the `elif (base64_audio := response_data['delta']):` branch, add the item-tracking block as the first statements (before `pcm_audio = base64.b64decode(base64_audio)`):

```python
                        elif (base64_audio := response_data['delta']):
                            item_id = response_data.get('item_id')
                            if item_id is not None and \
                                    item_id != self._current_item_id:
                                self._current_item_id = item_id
                                self._current_content_index = \
                                    response_data.get('content_index', 0)
                                self._played_samples = 0
                            pcm_audio = base64.b64decode(base64_audio)
```

- [ ] **Step 5: Clear the item id on response.done**

In the `response.done` handler, right after the existing `message = None` line:

```python
                        message = None
                        self._current_item_id = None
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_realtime_client.py::test_audio_delta_tracks_item_and_resets_counter -v`
Expected: PASS

Note: the receive loop logs one "Error in receive loop" line when the scripted `EOFError` ends it — this is expected and harmless.

- [ ] **Step 7: Commit**

```bash
git add src/realtime/realtime_client.py backend/tests/test_realtime_client.py
git commit -m "feat: track current assistant audio item id and content index"
```

---

### Task 3: Send truncate on barge-in

Emit `conversation.item.truncate` (before `response.cancel`) when the user barges in on an in-progress, already-playing response.

**Files:**
- Modify: `src/realtime/realtime_client.py` (`input_audio_buffer.speech_started` handler ~279-297)
- Test: `backend/tests/test_realtime_client.py`

**Interfaces:**
- Consumes: `_current_item_id`, `_current_content_index` (Task 2), `_played_samples` (Task 1), `CLIENT_SAMPLE_RATE` (already imported), and the `FakeWebSocket` helper (Task 2).
- Produces: a `conversation.item.truncate` WebSocket message on barge-in.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_realtime_client.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_realtime_client.py -k barge_in -v`
Expected: `test_barge_in_sends_truncate_before_cancel` FAILS (`conversation.item.truncate` not in `types`); `test_barge_in_without_playback_skips_truncate` PASSES already (no truncate is ever sent yet).

- [ ] **Step 3: Send truncate before cancel**

In the `input_audio_buffer.speech_started` handler, replace the existing `if message is not None:` block. Change from:

```python
                        if message is not None:
                            # An assistant response was still in progress: cancel it
                            # server-side, remember its response_id so any deltas for
                            # it still in flight (sent before the server honored our
                            # cancel) get dropped instead of starting a new message
                            # *after* the user's interrupting turn, and tell the
                            # WebSocket layer to flush whatever audio it already
                            # handed the client (which keeps playing out otherwise).
                            self._cancelled_response_id = self._current_response_id
                            await websocket.send(json.dumps(dict(type = 'response.cancel')))
                            message = None
                            self._barge_in_event.set()
```

to:

```python
                        if message is not None:
                            # An assistant response was still in progress. First
                            # tell the server how much of the current assistant
                            # item the user actually heard (the audio already
                            # sent to the client), so its conversation state
                            # doesn't keep audio that was generated but cut off
                            # before playback. Then cancel it server-side,
                            # remember its response_id so any deltas still in
                            # flight get dropped instead of starting a new
                            # message *after* the user's interrupting turn, and
                            # tell the WebSocket layer to flush whatever audio it
                            # already handed the client.
                            if self._current_item_id is not None and \
                                    self._played_samples > 0:
                                audio_end_ms = round(
                                    self._played_samples
                                    / CLIENT_SAMPLE_RATE * 1000
                                )
                                await websocket.send(json.dumps(dict(
                                    type = 'conversation.item.truncate',
                                    item_id = self._current_item_id,
                                    content_index = self._current_content_index,
                                    audio_end_ms = audio_end_ms,
                                )))
                                logger.debug(
                                    'Truncated item %s at %dms on barge-in',
                                    self._current_item_id,
                                    audio_end_ms,
                                )
                            self._cancelled_response_id = self._current_response_id
                            await websocket.send(json.dumps(dict(type = 'response.cancel')))
                            message = None
                            self._barge_in_event.set()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_realtime_client.py -k barge_in -v`
Expected: both PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -v`
Expected: all tests pass (existing `test_api.py`, `test_websocket.py`, and the new `test_realtime_client.py`).

- [ ] **Step 6: Lint**

Run: `uv run ruff check src/realtime/realtime_client.py backend/api/websocket.py backend/tests/test_realtime_client.py`
Expected: no errors (watch the 79-char line limit).

- [ ] **Step 7: Commit**

```bash
git add src/realtime/realtime_client.py backend/tests/test_realtime_client.py
git commit -m "feat: truncate interrupted assistant item on barge-in"
```

---

## Self-Review

**Spec coverage:**
- Track current assistant audio item (`item_id`/`content_index`) → Task 2. ✓
- Count audio sent to client (`_played_samples`, `read_play_audio`, route both drain sites) → Task 1. ✓
- Fire truncate on barge-in, before `response.cancel`, guarded by "in progress" + `_played_samples > 0` → Task 3. ✓
- Clear tracking on `response.done` → Task 2, Step 5. ✓
- `audio_end_ms = round(_played_samples / CLIENT_SAMPLE_RATE * 1000)` → Task 3. ✓
- Error handling: skip truncate when nothing played (`test_barge_in_without_playback_skips_truncate`); sends stay inside `receive()`'s existing try/except. ✓
- No client/protocol changes → only `realtime_client.py` and `websocket.py` (drain call) touched. ✓
- Testing (3 scenarios: truncate-after-playback, no-truncate-when-nothing-played, counter/item accounting) → Tasks 1-3. ✓
- Out of scope: `reset_stream(play_stream_only=True)` no-op left untouched. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `_played_samples` (int), `read_play_audio(nsamples, partial)`, `_current_item_id` (str|None), `_current_content_index` (int), `FakeWebSocket.sent` (list[dict]) used consistently across Tasks 1-3. ✓
