# Per-Turn Transcript Rows (item_id-keyed) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the transcript panel show one row per speaker turn — user and assistant each on their own row, with a new row after every turn finish or interruption.

**Architecture:** Rekey the transcript model on the Realtime API's stable `item_id` instead of list position. The backend keeps an insertion-ordered `_items` dict and assigns a monotonic `seq` at item creation; the monitor forwards `{role, seq, delta}`; the frontend renders one row per `seq` with no merging.

**Tech Stack:** Python 3.11+ (async, `websockets`), FastAPI WebSocket, PyAV; Next.js/React/TypeScript frontend; pytest + pytest-asyncio (`asyncio_mode = auto`).

## Reconciliation note (2026-07-21, executed inline in worktree)

The parallel barge-in-truncation work advanced further (branch tip `2a04b5c`) and
**restructured `speech_started`**. Executed against that state with these deviations from
the task text below:

- **Task 1 is already done** — its logging (`.delta` branch, item-id in the `completed` and
  `speech_started` logs) is present in the rebased base. No action.
- **Task 3 drops the `_active_assistant_item_id` flag.** `speech_started` now fires barge-in
  unconditionally and guards cancel/truncate with `if self._current_response_id is not None:`;
  `_current_response_id` is set on transcript/audio deltas and reset on `response.done`. That
  existing signal replaces the planned flag. On barge-in, mark `self._items[self._current_item_id]`
  interrupted (the audio item id equals the assistant transcript item id).
- **The two truncation tests need no changes** — they set `_current_response_id` via their
  scripted transcript delta, so the guard still fires. (Supersedes the Task 3 Step 1
  instruction to add `item_id` to them.)
- Execution is **inline** (Agent subagents run in the main checkout, not this worktree), and
  commits land on branch `feat/transcript-per-turn-rows`. Test command:
  `.venv/bin/python -m pytest`.

## Global Constraints

- Run backend tests from the **repo root** (pyproject: `testpaths = ["backend/tests"]`, `pythonpath = ["backend"]`) with the project's Python **3.11+** interpreter (the code uses `except*`, invalid on 3.10). Command: `python -m pytest -q`.
- **Coordination:** this branch (`feat/barge-in-truncation`) has **committed** barge-in-truncation work (`3e06d8b`, `a66572d`) in `src/realtime/realtime_client.py`: `__init__` fields `_current_item_id`/`_current_content_index`/`_played_samples`, the audio-item tracking in the `response.output_audio.delta` branch, and a **`conversation.item.truncate` block inside the `input_audio_buffer.speech_started` branch** (currently lines 309-327). **Do not remove or repurpose any of it** — Task 3 rewrites `speech_started` but MUST keep the truncate block intact. This plan adds a *separate* `_active_assistant_item_id` flag and a separate `_items` dict so the two features do not collide. Two existing truncation tests (`test_barge_in_sends_truncate_before_cancel`, `test_barge_in_without_playback_skips_truncate` in `backend/tests/test_realtime_client.py`) script a transcript delta **without** an `item_id`; because the new barge-in guard keys on `_active_assistant_item_id` (set only when a transcript delta carries an `item_id`), Task 3 updates those two tests to add `"item_id": "item_A"` to their delta so they keep passing. All line numbers below refer to the current committed state (`a66572d`).
- Transcript text stored per item MUST stay append-only (monotonically growing). The monitor forwards deltas by character-length diff (`text[prev_len:]`); replacing or shrinking a stored string would corrupt forwarding.
- Keep NumPy/Sphinx-style docstrings and the existing code style (spaces around `=` in call kwargs is the house style in `realtime_client.py`; `websocket.py` uses standard PEP8 — match each file's local style).

---

### Task 1: Phase 0 — confirm the cause with debug logging

Add handling + debug logs for the input-transcription events so we can confirm whether Whisper events actually arrive before changing behavior. The `.delta` event is currently unhandled entirely; adding its (debug-level, permanent) log is also the first half of Task 3.

**Files:**
- Modify: `src/realtime/realtime_client.py` (the `conversation.item.input_audio_transcription.completed` branch, ~lines 275-287)

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing new (diagnostic only).

- [ ] **Step 1: Add a debug log to the existing `completed` branch and a new `delta` branch**

In `receive()`, immediately **before** the existing
`elif response_data['type'] == 'conversation.item.input_audio_transcription.completed':`
branch (~line 275), add a new branch, and leave the completed branch's log in place:

```python
                    elif response_data['type'] == 'conversation.item.input_audio_transcription.delta':
                        logger.debug(
                            'Event: %s - item=%s delta=%r',
                            response_data['type'],
                            response_data.get('item_id'),
                            response_data.get('delta'),
                        )

                    elif response_data['type'] == 'conversation.item.input_audio_transcription.completed':
                        logger.debug(
                            'Event: %s - item=%s transcript=%r',
                            response_data['type'],
                            response_data.get('item_id'),
                            response_data.get('transcript'),
                        )
                        if not user_message:
                            user_message = dict(role = 'user', content = '')
                            self._messages.append(user_message)
                        if user_message['content'] is None:
                            user_message['content'] = response_data['transcript']
                        else:
                            user_message['content'] += response_data['transcript']
```

Also update the `input_audio_buffer.speech_started` debug log (~line 292) to include the item id:

```python
                        logger.debug(
                            'Event: %s - item=%s cleared the play stream',
                            response_data['type'],
                            response_data.get('item_id'),
                        )
```

- [ ] **Step 2: Run one conversation and read the logs**

Start the backend and frontend (`backend/DEVELOPMENT.md` / `frontend/DEVELOPMENT.md`), speak one sentence, let the assistant reply, then stop. Grep the backend log:

```bash
grep -E "input_audio_transcription|speech_started" <backend-log>
```

Expected (cause = forwarding/merge bug): you see `speech_started` with an `item=...`, and at least one `...transcription.completed` (and possibly `.delta`) line carrying a non-empty transcript and the **same** `item=...`.

If you see **no** `...transcription.completed`/`.delta` lines at all, STOP: the input-transcription config for `gpt-realtime` is the real problem — revisit `REALTIME_API_CONFIG.audio.input.transcription` in `src/realtime/config.py` before continuing this plan.

- [ ] **Step 3: Commit**

```bash
git add src/realtime/realtime_client.py
git commit -m "chore: log input transcription events to confirm they arrive

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Backend item store + helper (additive)

Introduce the `_items` model and `seq` counter alongside the existing `_messages` list (no behavior change yet), so `receive()` can be migrated in Task 3 with the model already in place.

**Files:**
- Modify: `src/realtime/realtime_client.py` (`__init__` ~lines 78-93; class body for the new method)
- Test: `backend/tests/test_realtime_client.py`

**Interfaces:**
- Produces:
  - `self._items: dict[str, dict]` — `item_id -> {"role": str, "text": str, "seq": int, "status": str}`, insertion-ordered.
  - `self._next_seq: int`.
  - `self._active_assistant_item_id: str | None`.
  - `self._get_or_create_item(item_id: str, role: str) -> dict` — returns the item record, assigning `seq` once on first creation; `status` starts as `"in_progress"`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_realtime_client.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_realtime_client.py::test_get_or_create_item_assigns_incrementing_seq_once -v`
Expected: FAIL with `AttributeError: 'OpenAIRealtimeAPIWrapper' object has no attribute '_get_or_create_item'`.

- [ ] **Step 3: Add the fields and helper**

In `__init__`, immediately after `self._messages = []` (~line 79) add:

```python
        # item_id -> {"role", "text", "seq", "status"}. Insertion-ordered so
        # iteration yields creation order. This is the source of truth for the
        # transcript rows shown to the client, replacing positional _messages.
        self._items: dict[str, dict] = {}
        self._next_seq = 0
        # item_id of the assistant response currently streaming transcript, or
        # None. Used to detect barge-in without reusing the truncation feature's
        # _current_item_id (which tracks the currently *playing audio* item).
        self._active_assistant_item_id: str | None = None
```

Add this method to the class (e.g. just above `read_play_audio`):

```python
    def _get_or_create_item(self, item_id: str, role: str) -> dict:
        """Return the transcript item for ``item_id``, creating it if new.

        A stable, monotonically increasing ``seq`` is assigned once, when the
        item is first seen, and defines the row order shown to the client. The
        ``item_id`` comes from the Realtime API and correlates every delta /
        completed event to the right row regardless of arrival order.

        Args:
            item_id (str): The Realtime API conversation item id.
            role (str): ``'user'`` or ``'assistant'``.
        Returns:
            dict: The item record ``{"role", "text", "seq", "status"}``.
        """
        item = self._items.get(item_id)
        if item is None:
            item = dict(role = role, text = '', seq = self._next_seq, status = 'in_progress')
            self._items[item_id] = item
            self._next_seq += 1
        return item
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_realtime_client.py::test_get_or_create_item_assigns_incrementing_seq_once -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/realtime/realtime_client.py backend/tests/test_realtime_client.py
git commit -m "feat: add item_id-keyed transcript store and seq helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Migrate `receive()` transcript handling to `_items`

Rewrite the transcript-related branches of `receive()` to populate `_items` by `item_id`, remove the `message` / `user_message` locals and all `_messages` usage, and mark rows `done`/`interrupted`. This is the core behavioral change.

**Files:**
- Modify: `src/realtime/realtime_client.py` (`receive()` ~lines 212-330; `start()` ~line 422; `valid_messages` ~lines 387-390; class annotation ~line 52)
- Test: `backend/tests/test_realtime_client.py`

**Interfaces:**
- Consumes: `self._get_or_create_item`, `self._items`, `self._active_assistant_item_id` (Task 2).
- Produces: `_items` populated during `receive()`; `valid_messages` derived from `_items`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_realtime_client.py` (the module already imports `json`, `pytest`, `OpenAIRealtimeAPIWrapper`, `TerminateTaskGroup`, and defines `FakeWebSocket`):

```python
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


async def test_barge_in_marks_prior_assistant_row_interrupted_and_starts_new_row():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
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
```

Also update the **two existing truncation tests** so their transcript delta carries an `item_id` (the new barge-in guard keys on `_active_assistant_item_id`, which is set only when a transcript delta has an `item_id`). In both `test_barge_in_sends_truncate_before_cancel` (~line 101) and `test_barge_in_without_playback_skips_truncate` (~line 134), change the scripted delta from:

```python
        {
            "type": "response.output_audio_transcript.delta",
            "delta": "Hi",
            "response_id": "resp_1",
        },
```

to (add the `item_id`, matching the `_current_item_id = "item_A"` these tests set):

```python
        {
            "type": "response.output_audio_transcript.delta",
            "delta": "Hi",
            "response_id": "resp_1",
            "item_id": "item_A",
        },
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_realtime_client.py -k "user_row or input_transcription_delta or barge_in_marks or valid_messages_orders" -v`
Expected: FAIL (e.g. `KeyError: 'user_1'` / assertion errors — `_items` is not populated by `receive()` yet).

- [ ] **Step 3: Rewrite the transcript branches in `receive()`**

Remove the two local initializers at the top of `receive()` (currently ~lines 212-213):

```python
        message = None
        user_message = None
```

Replace the `response.output_audio_transcript.delta` branch (~lines 253-265) with:

```python
                    elif response_data['type'] == 'response.output_audio_transcript.delta':
                        # Drop leftover transcript for a response we already
                        # cancelled (see input_audio_buffer.speech_started): it
                        # would otherwise create a row *after* the user's
                        # interrupting turn, reversing the visible order.
                        if self._cancelled_response_id is None or \
                                response_data.get('response_id') != self._cancelled_response_id:
                            self._current_response_id = response_data.get('response_id')
                            item_id = response_data.get('item_id')
                            if item_id is not None:
                                item = self._get_or_create_item(item_id, 'assistant')
                                item['text'] += response_data['delta']
                                self._active_assistant_item_id = item_id
```

Replace the `response.output_audio_transcript.done` branch (~lines 267-273) with:

```python
                    elif response_data['type'] == 'response.output_audio_transcript.done':
                        logger.info(
                            'Event: %s - %s',
                            response_data['type'],
                            response_data.get('transcript')
                        )
                        item_id = response_data.get('item_id')
                        if item_id is not None and item_id in self._items:
                            self._items[item_id]['status'] = 'done'
```

Replace the input-transcription `delta` (added in Task 1) and `completed` branches (~lines 275-287) with:

```python
                    elif response_data['type'] == 'conversation.item.input_audio_transcription.delta':
                        item_id = response_data.get('item_id')
                        if item_id is not None:
                            item = self._get_or_create_item(item_id, 'user')
                            item['text'] += response_data.get('delta', '')

                    elif response_data['type'] == 'conversation.item.input_audio_transcription.completed':
                        logger.debug(
                            'Event: %s - item=%s transcript=%r',
                            response_data['type'],
                            response_data.get('item_id'),
                            response_data.get('transcript'),
                        )
                        item_id = response_data.get('item_id')
                        if item_id is not None:
                            item = self._get_or_create_item(item_id, 'user')
                            transcript = response_data.get('transcript')
                            # Keep text append-only: only set from 'completed'
                            # when no streaming deltas already populated it
                            # (whisper-1 sends only 'completed'; other models
                            # stream '.delta' then send the full 'completed').
                            if transcript and not item['text']:
                                item['text'] = transcript
                            item['status'] = 'done'
```

Replace the `input_audio_buffer.speech_started` branch (currently lines 289-334) with the following. **This preserves the committed truncate block verbatim** — only the guard (`message is not None` → `self._active_assistant_item_id is not None`), the `message = None` line (→ mark-interrupted + clear the flag), and the user-row reservation change:

```python
                    elif response_data['type'] == 'input_audio_buffer.speech_started':
                        # Reset existing AI voice audio when user speech is detected
                        self.reset_stream(play_stream_only = True)
                        logger.debug(
                            'Event: %s - item=%s cleared the play stream',
                            response_data['type'],
                            response_data.get('item_id'),
                        )
                        if self._active_assistant_item_id is not None:
                            # An assistant response was still in progress.
                            # First tell the server how much of the current
                            # assistant item the user actually heard (the
                            # audio already sent to the client), so its
                            # conversation state doesn't keep audio that was
                            # generated but cut off before playback. Then
                            # cancel it server-side, remember its response_id
                            # so any deltas still in flight get dropped
                            # instead of starting a new message *after* the
                            # user's interrupting turn, mark its row
                            # interrupted, and tell the WebSocket layer to
                            # flush whatever audio it already handed the client.
                            if self._current_item_id is not None and \
                                    self._played_samples > 0:
                                audio_end_ms = round(
                                    self._played_samples
                                    / CLIENT_SAMPLE_RATE * 1000
                                )
                                await websocket.send(json.dumps(dict(
                                    type = 'conversation.item.truncate',
                                    item_id = self._current_item_id,
                                    content_index = (
                                        self._current_content_index
                                    ),
                                    audio_end_ms = audio_end_ms,
                                )))
                                logger.debug(
                                    'Truncated item %s at %dms on barge-in',
                                    self._current_item_id,
                                    audio_end_ms,
                                )
                            self._cancelled_response_id = self._current_response_id
                            if self._active_assistant_item_id in self._items:
                                self._items[self._active_assistant_item_id]['status'] = 'interrupted'
                            await websocket.send(json.dumps(dict(type = 'response.cancel')))
                            self._active_assistant_item_id = None
                            self._barge_in_event.set()
                        # Reserve the user's row now (before the assistant replies)
                        # so its seq sorts ahead of the reply. speech_started
                        # carries the user message's item_id.
                        item_id = response_data.get('item_id')
                        if item_id is not None:
                            self._get_or_create_item(item_id, 'user')
```

In the `response.done` branch, immediately after the existing `self._current_item_id = None` line (currently line 349) add:

```python
                        self._active_assistant_item_id = None
```

- [ ] **Step 4: Update `valid_messages`, `start()`, and the class annotation**

Replace `valid_messages` (currently lines 411-414) with:

```python
    @property
    def valid_messages(self) -> list[dict]:
        """Get valid chat messages in creation (seq) order.
        """
        return [
            dict(role = item['role'], content = item['text'])
            for item in sorted(self._items.values(), key = lambda i: i['seq'])
            if item['text']
        ]
```

In `start()` replace `self._messages = []` (currently line 446) with:

```python
        self._items = {}
        self._next_seq = 0
        self._active_assistant_item_id = None
```

Remove the now-unused class annotation `_messages: list[dict]` (~line 52) and the `self._messages = []` line in `__init__` (~line 79). Verify no other `_messages` references remain in this file:

Run: `grep -n "_messages" src/realtime/realtime_client.py`
Expected: no output.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_realtime_client.py -v`
Expected: PASS (all, including the pre-existing `test_read_play_audio_counts_samples`, `test_audio_delta_tracks_item_and_resets_counter`, and the two truncation tests `test_barge_in_sends_truncate_before_cancel` / `test_barge_in_without_playback_skips_truncate` — the truncate block and its ordering before `response.cancel` must still hold).

- [ ] **Step 6: Commit**

```bash
git add src/realtime/realtime_client.py backend/tests/test_realtime_client.py
git commit -m "feat: build per-turn transcript rows keyed by item_id

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Monitor forwards seq-keyed transcript deltas

Update the WebSocket monitor to read `_items` and forward `{role, seq, delta}`, and update the test `FakeAPIWrapper` to expose `_items`.

**Files:**
- Modify: `backend/api/websocket.py` (`__init__` ~line 66; `_monitor_messages` ~lines 162-200; reset ~line 317)
- Test: `backend/tests/test_websocket.py` (`FakeAPIWrapper` ~lines 26-73; new test)

**Interfaces:**
- Consumes: `self.api_wrapper._items` (`item_id -> {"role","text","seq","status"}`).
- Produces: client messages `{"type": "transcript", "role": str, "seq": int, "delta": str}`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_websocket.py`. First extend `FakeAPIWrapper.__init__` (after `self._messages: list[dict] = []`, ~line 37) with:

```python
        self._items: dict[str, dict] = {}
```

Then add a wrapper subclass and a test at the end of the file:

```python
class FakeAPIWrapperWithItems(FakeAPIWrapper):
    """Exposes a preset transcript item so the monitor forwards it once."""

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_websocket.py::test_monitor_forwards_seq_keyed_transcripts -v`
Expected: FAIL (the monitor still reads `_messages`, so no `transcript` messages with `seq` are sent and the loop blocks/times out or receives none).

- [ ] **Step 3: Update the monitor**

In `AudioStreamSession.__init__`, change the type hint (~line 66) from:

```python
        # message index -> chars already forwarded
        self.last_transcript_lengths: dict[int, int] = {}
```

to:

```python
        # item_id -> chars already forwarded
        self.last_transcript_lengths: dict[str, int] = {}
```

Replace the body of `_monitor_messages` (the `while self.recording:` loop, ~lines 173-195) with:

```python
            while self.recording:
                # Snapshot: receive() may insert a new item mid-iteration, and
                # iterating a dict while it grows raises RuntimeError. New items
                # are simply picked up on the next poll.
                items = list(self.api_wrapper._items.items())
                for item_id, item in items:
                    text = item.get("text")
                    if not text:
                        continue
                    prev_len = self.last_transcript_lengths.get(item_id, 0)
                    if len(text) > prev_len:
                        delta = text[prev_len:]
                        await self.websocket.send_text(
                            json.dumps({
                                "type": "transcript",
                                "role": item.get("role"),
                                "seq": item.get("seq"),
                                "delta": delta,
                            })
                        )
                        self.last_transcript_lengths[item_id] = len(text)
                        logger.debug(
                            f"Forwarded {item.get('role')} transcript "
                            "delta to client"
                        )
                await asyncio.sleep(MONITOR_POLL_INTERVAL_S)
```

Also update the docstring of `_monitor_messages` (~lines 163-171) to describe item_id keying (replace the "by index" wording):

```python
        """Monitor and forward transcript growth from API to client.

        Items are mutated in place as transcript deltas stream in (text
        starts as '' and grows), so we track how many characters of each
        item we've already forwarded, keyed by the API's stable ``item_id``,
        and send only the newly-added substring. The forwarded ``seq`` gives
        the client a stable creation order for the rows.
        """
```

(The `last_transcript_lengths = {}` reset in `_start_conversation` at ~line 317 needs no change — an empty dict works for either key type.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_websocket.py -v`
Expected: PASS (all, including the pre-existing start/stop and barge-in tests).

- [ ] **Step 5: Commit**

```bash
git add backend/api/websocket.py backend/tests/test_websocket.py
git commit -m "feat: forward seq-keyed transcript deltas from item store

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Frontend — one row per seq, remove merging

Rekey the transcript hook on `seq`, delete the consecutive-same-role merge, and render one row per turn.

**Files:**
- Modify: `frontend/hooks/useAudioStream.ts`
- Modify: `frontend/components/TranscriptDisplay.tsx`

**Interfaces:**
- Consumes: WebSocket `transcript` messages `{type, role, seq, delta}` from Task 4.
- Produces: `messages: {role, text, seq}[]` sorted by `seq`, one entry per turn.

No automated frontend tests (decision: no JS test runner is configured; verify manually). Verification is Step 4.

- [ ] **Step 1: Rewrite the transcript state in `useAudioStream.ts`**

Replace the interfaces (lines 8-17) with:

```ts
interface Message {
  role: 'user' | 'assistant';
  text: string;
  seq: number;
}

interface RawMessage {
  role: 'user' | 'assistant';
  text: string;
}
```

Replace the refs block and `rebuildMerged`/`applyTranscriptDelta`/`resetTranscript` (lines 59-130) with:

```ts
  // Raw transcript content keyed by the backend-assigned `seq` — a stable,
  // monotonically increasing id assigned when the underlying conversation
  // item was first created. `seq` is BOTH the row identity and the sort
  // order: the user's Whisper transcript often arrives after the assistant
  // has already started replying, so messages do NOT arrive in seq order.
  const rawMessagesRef = useRef<Map<number, RawMessage>>(new Map());
  // Seqs seen so far, kept sorted incrementally (see insertSorted) so
  // re-deriving the row list never needs a fresh O(n log n) sort.
  const orderedSeqsRef = useRef<number[]>([]);

  const applyTranscriptDelta = (
    seq: number,
    role: 'user' | 'assistant',
    delta: string,
  ): Message[] => {
    const existing = rawMessagesRef.current.get(seq);
    rawMessagesRef.current.set(seq, {
      role,
      text: (existing?.text ?? '') + delta,
    });
    if (!existing) {
      insertSorted(orderedSeqsRef.current, seq);
    }
    // One row per seq, in seq order. No merging of consecutive same-role
    // turns: a finished or interrupted turn always yields a new seq next.
    return orderedSeqsRef.current.map((s) => {
      const msg = rawMessagesRef.current.get(s)!;
      return { role: msg.role, text: msg.text, seq: s };
    });
  };

  const resetTranscript = () => {
    rawMessagesRef.current = new Map();
    orderedSeqsRef.current = [];
  };
```

Update the `transcript` branch in `handleSocketMessage` (lines 178-181) to:

```ts
        } else if (message.type === 'transcript') {
          setMessages(
            applyTranscriptDelta(message.seq, message.role, message.delta),
          );
```

(`insertSorted` at lines 22-31 is unchanged and reused.)

- [ ] **Step 2: Update `TranscriptDisplay.tsx`**

Replace the `Message` interface (lines 3-7) and the `.map` key (line 19) so rows key on `seq`:

```tsx
interface Message {
  role: 'user' | 'assistant';
  text: string;
  seq: number;
}
```

```tsx
        messages.map((msg) => (
          <div key={msg.seq} className={`message ${msg.role}`}>
```

- [ ] **Step 3: Type-check / build the frontend**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors (no remaining references to the removed `index` field, `mergedRef`, or `indexToBubblePos`).

- [ ] **Step 4: Manual verification**

Start backend + frontend, have a two-turn conversation, and interrupt the assistant mid-reply once. Expected in the transcript panel:
- A `You:` row appears with your speech, on its **own** row.
- Each assistant reply is on its **own** row (turns are not fused).
- After an interruption, the assistant's next reply starts a **new** row rather than appending to the interrupted one.

- [ ] **Step 5: Commit**

```bash
git add frontend/hooks/useAudioStream.ts frontend/components/TranscriptDisplay.tsx
git commit -m "feat: render one transcript row per turn (seq-keyed, no merge)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full backend suite**

Run: `python -m pytest -q`
Expected: all tests pass (Tasks 2-4 additions plus pre-existing `test_api.py`, `test_realtime_client.py`, `test_websocket.py`).

- [ ] **Step 2: Lint / type-check backend if configured**

Run: `ruff check . && mypy src backend` (if these pass cleanly in the current repo baseline).
Expected: no new errors introduced by this change.

---

## Self-Review Notes

- **Spec coverage:** Phase-0 diagnosis → Task 1. Backend data model (`_items`/`_next_seq`/`status`, item helper) → Task 2. Event handling (speech_started user row, input `.delta`+`.completed`, assistant delta/done, interruption) → Task 3. `valid_messages` redefinition → Task 3 Step 4. Monitor `seq` forwarding + `item_id` key → Task 4. Frontend seq-keyed no-merge rows + `TranscriptDisplay` key → Task 5. Minimal UI (no streaming indicator) and no frontend test tooling → honored (Task 5 uses manual verification). Out-of-scope items excluded.
- **Append-only invariant:** enforced in Task 3 (`completed` sets text only when empty) so the monitor's length-diff forwarding (Task 4) stays correct.
- **Parallel-work isolation (truncation, committed `a66572d`):** uses a new `_active_assistant_item_id` flag rather than the truncation feature's `_current_item_id`; the `response.output_audio.delta` audio-tracking branch is left untouched; the `conversation.item.truncate` block inside `speech_started` is preserved verbatim (only its guard/cleanup lines change); the two existing truncation tests are updated to add an `item_id` to their transcript delta so the new guard fires. Truncation still sends `conversation.item.truncate` before `response.cancel` on barge-in.
- **Type consistency:** `_get_or_create_item(item_id, role) -> dict` with keys `role/text/seq/status` used identically in Tasks 3-4; `last_transcript_lengths` retyped to `dict[str, int]`; frontend `Message` gains `seq` and drops `index` in both files; client message shape `{type, role, seq, delta}` produced in Task 4 and consumed in Task 5.
```
