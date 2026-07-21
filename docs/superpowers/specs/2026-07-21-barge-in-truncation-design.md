# Barge-in truncation design

**Date:** 2026-07-21
**Status:** Approved (design)
**Area:** `src/realtime/realtime_client.py` (server-facing only)

## Problem

When the user barges in on the assistant, the current code sends
`response.cancel` and tells the browser to drop already-queued audio
(`clear_audio`), but it never sends `conversation.item.truncate`.

With a WebSocket connection to the OpenAI Realtime API, `interrupt_response`
only stops *generation*. The client is responsible for telling the server how
much of the assistant's audio the user actually heard, via
`conversation.item.truncate` with an `audio_end_ms` value. Without it, the
server keeps the **entire** generated assistant response in its conversation
state, even though the user only heard the first fraction before interrupting.
Over a multi-turn chat this makes the model reference things the user never
heard.

The OpenAI Agents SDK (`RealtimeSession`) solves this with a
`RealtimePlaybackTracker` that records playback position and sends
`conversation.item.truncate` on interruption. This spec brings the same
correctness fix to this codebase, using a simpler server-side estimate of how
much audio was sent to the client.

References:
- https://developers.openai.com/api/docs/guides/realtime-conversations
- https://community.openai.com/t/realtime-api-interruptions-dont-properly-trim-the-transcript/1000703

## Goal

On barge-in, send `conversation.item.truncate` for the in-progress assistant
audio item with an `audio_end_ms` equal to the amount of that item's audio
already sent to the client, so the model's server-side history matches what
the user experienced.

Non-goals:
- No client/browser protocol changes (`clear_audio` and the frontend stay as-is).
- No precise client-reported playback position (the accepted approximation is
  the server-side "sent" estimate).
- Not fixing the separate `reset_stream(play_stream_only=True)` observation
  (see Out of Scope).

## The truncate call

```json
{
  "type": "conversation.item.truncate",
  "item_id": "<current assistant audio item>",
  "content_index": 0,
  "audio_end_ms": <ms of that item sent to the client>
}
```

## Components

All changes are in `src/realtime/realtime_client.py`
(`OpenAIRealtimeAPIWrapper`), plus routing updates in the audio-drain callers.

### 1. Track the current assistant audio item

New instance state:
- `self._current_item_id: str | None`
- `self._current_content_index: int`
- `self._played_samples: int` (client-domain sample count, i.e. 48 kHz)

In the `response.output_audio.delta` handler, read `item_id` and
`content_index` from the event. When `item_id` differs from
`self._current_item_id`, a new item has started:
- set `self._current_item_id = item_id`
- set `self._current_content_index = content_index` (default `0`)
- reset `self._played_samples = 0`

(Today the code tracks only `response_id` from the *transcript* delta;
`conversation.item.truncate` requires the `item_id` from the *audio* delta.)

### 2. Count audio sent to the client

Add a method on the wrapper:

```python
def read_play_audio(self, nsamples, partial=True):
    frame = self._play_stream.read(nsamples, partial=partial)
    if frame:
        self._played_samples += frame.samples
    return frame
```

Route every drain of `_play_stream` through it:
- `backend/api/websocket.py` `_stream_audio_responses` (the live FastAPI path)
  calls `self.api_wrapper.read_play_audio(AUDIO_CHUNK_SIZE, partial=True)`
  instead of `self.api_wrapper._play_stream.read(...)`.
- The legacy `audio_frame_callback` in the wrapper drains via the same method
  for consistency.

The counter is client-domain samples. Convert to ms:

```python
audio_end_ms = round(self._played_samples / CLIENT_SAMPLE_RATE * 1000)
```

Resampling preserves duration, so this ms value is valid in the API's 24 kHz
timeline. Because "sent" is always ≤ "generated so far", `audio_end_ms` can
never exceed the real item length, so the API will not reject it.

### 3. Fire truncate on barge-in

Inside the existing `input_audio_buffer.speech_started` handler, within the
current `if message is not None:` block (which already means "a response was in
progress"), and **before** the existing `response.cancel` send:

```python
if self._current_item_id is not None and self._played_samples > 0:
    audio_end_ms = round(self._played_samples / CLIENT_SAMPLE_RATE * 1000)
    await websocket.send(json.dumps(dict(
        type='conversation.item.truncate',
        item_id=self._current_item_id,
        content_index=self._current_content_index,
        audio_end_ms=audio_end_ms,
    )))
```

If nothing was played yet (`_played_samples == 0`), skip truncate (matches the
SDK's "if audio is playing" guard) and just cancel as today.

### 4. Clear tracking on response end

On `response.done`, set `self._current_item_id = None` so a later
`speech_started` cannot truncate an already-finished item. (`_played_samples`
resets naturally when the next item's first delta arrives.)

## Data flow

```
audio delta       -> capture item_id/content_index; reset counter on new item
                     -> write resampled frame to _play_stream
WS drain          -> read_play_audio() -> _played_samples += frame.samples
                     -> base64 -> send to client
speech_started    -> if item in progress and _played_samples > 0:
                        send conversation.item.truncate(item_id,
                                                         content_index,
                                                         audio_end_ms)
                     -> response.cancel (existing)
                     -> clear local + client buffers (existing)
response.done     -> _current_item_id = None
```

## Error handling

- `_played_samples == 0` -> no truncate (avoids a zero-length truncate).
- All sends remain inside the existing `try/except` in `receive()`; a failed
  truncate is logged and does not crash the receive loop.
- No client/protocol changes, so the browser playback path and `clear_audio`
  handling are unaffected.

## Testing (TDD)

Drive `receive()` with a fake websocket that yields a scripted sequence of
events and then breaks the loop, and assert on what the wrapper sent:

1. **Truncate on barge-in after playback.** Sequence: audio delta(s) for
   item `A` -> some `read_play_audio` calls to advance `_played_samples` ->
   `input_audio_buffer.speech_started`. Assert a `conversation.item.truncate`
   is sent with `item_id == "A"`, correct `content_index`, and the expected
   `audio_end_ms`, and that it is sent **before** `response.cancel`.
2. **No truncate when nothing played.** `speech_started` with
   `_played_samples == 0` -> no `conversation.item.truncate` is sent, but
   `response.cancel` still is.
3. **Counter accounting.** `read_play_audio` increments `_played_samples` by
   the returned frame's sample count; a delta with a new `item_id` resets the
   counter and updates `_current_item_id`/`_current_content_index`.

Follow the existing test structure in `backend/tests/test_websocket.py` /
`backend/tests/test_api.py` (plain `assert`, fixtures, `pytest`).

## Out of scope

`reset_stream(play_stream_only=True)` only constructs a new `_play_stream`
FIFO when one does not already exist, so on an in-progress conversation it
appears to be a no-op rather than actually clearing buffered audio. This is a
separate potential bug from barge-in truncation and is intentionally not
addressed here.
