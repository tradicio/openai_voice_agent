# `src/` Restructure — Design Spec

**Date:** 2026-07-22
**Status:** Approved for planning
**Scope:** Reorganize and decompose `src/` for readability, code quality, and a
solid base for future tools/features. Consumers in `backend/` and the test
suite are updated to match.

---

## 1. Goals & non-goals

**Goals**

- Give every module one clear purpose; eliminate scattered `*_utils` files and
  misplaced constants.
- Decompose the 529-line `OpenAIRealtimeAPIWrapper` God class into cohesive,
  independently-testable units.
- Expose a clean public API per package so consumers stop reaching into private
  internals.
- Make adding a new tool or feature a localized change.

**Non-goals (explicitly out of scope)**

- No runtime behavior changes. This is a **strictly behavior-preserving**
  refactor (see §7).
- No new features, no bug fixes (any bug found is logged in §10, not fixed here).
- No change to the `src`-at-repo-root layout or the `sys.path` import mechanism
  in `backend/main.py`.
- No change to the WebSocket wire protocol or REST API.
- No frontend changes.

---

## 2. Current problems (grounded in the code)

1. **God class.** `src/realtime/realtime_client.py` (529 lines) mixes WS
   connection lifecycle, a ~200-line `receive()` event-dispatch `if/elif`
   chain, the transcript item store, audio resampling + FIFO management,
   barge-in truncation, timers, and tool dispatch.
2. **Scattered utils.** `src/utils.py` (8 lines, one `get_logger`) sits at the
   package root; `src/audio/audio_utils.py` duplicates the "utils" naming.
3. **Misplaced constants.** Audio sample-rate/width/channel constants and the
   PyAV `FORMAT_MAPPING`/`LAYOUT_MAPPING` live in `realtime/config.py`, split
   from the `audio/` package that owns audio concerns.
4. **Mixed-concern config.** `realtime/config.py` bundles API connection config,
   session/VAD config, audio constants, and `DEFAULT_INSTRUCTIONS` (really a
   prompt), and imports `tools.py` — so "config" is not pure data.
5. **Redundant naming.** `audio/audio_utils.py`, `prompts/prompts.py`.
6. **Leaky abstraction at the boundary.** `backend/api/websocket.py` reaches
   into wrapper privates: `._items`, `._record_stream`, `._play_stream`,
   `._resampler_for_api/.format`, `._resampler_for_client`.

---

## 3. Target folder layout

```
src/
├── __init__.py
├── log.py                 # get_logger                         (was src/utils.py)
│
├── audio/
│   ├── __init__.py        # re-exports codec fns, formats, AudioPipeline
│   ├── codec.py           # pcm <-> AudioFrame                 (was audio/audio_utils.py)
│   ├── formats.py         # API_*/CLIENT_* rates + FORMAT/LAYOUT maps  (from realtime/config.py)
│   └── pipeline.py        # NEW: AudioPipeline (resamplers + record/play FIFOs)
│
├── prompts/
│   ├── __init__.py        # re-exports load_prompts, DEFAULT_INSTRUCTIONS
│   ├── loader.py          # load_prompts                       (was prompts/prompts.py)
│   ├── defaults.py        # DEFAULT_INSTRUCTIONS               (from realtime/config.py)
│   └── prompts.yaml
│
└── realtime/
    ├── __init__.py        # re-exports OpenAIRealtimeAPIWrapper, TerminateTaskGroup
    ├── client.py          # thin orchestrator                  (was realtime_client.py)
    ├── events.py          # NEW: EventDispatcher + TurnState (the receive() body)
    ├── transcript.py      # NEW: TranscriptStore (the _items dict + seq logic)
    ├── config.py          # PURIFIED: API URL/headers + session-config builder
    └── tools.py           # tool registry (unchanged)
```

---

## 4. Module responsibilities & public API

### 4.1 `src/log.py`
- `get_logger(name, level=logging.DEBUG) -> logging.Logger` — moved verbatim
  from `src/utils.py`. Kept (not inlined) because it forces each logger to
  `DEBUG`; inlining would change logging behavior.

### 4.2 `src/audio/formats.py`
Pure data moved out of `realtime/config.py`:
- `API_SAMPLE_RATE`, `API_SAMPLE_WIDTH`, `API_CHANNELS`
- `CLIENT_SAMPLE_RATE`, `CLIENT_SAMPLE_WIDTH`, `CLIENT_CHANNELS`
- `FORMAT_MAPPING`, `LAYOUT_MAPPING`

### 4.3 `src/audio/codec.py`
Moved verbatim from `audio/audio_utils.py`:
- `audio_frame_to_pcm_audio(frame) -> bytes`
- `pcm_audio_to_audio_frame(pcm_audio, *, format, layout, sample_rate) -> AudioFrame`

### 4.4 `src/audio/pipeline.py` — `AudioPipeline` (new)
Owns both resamplers **and** both FIFOs plus the `played_samples` counter.
FIFOs are created in `__init__`, so consumers never pre-create them.

| Method | Replaces | Behavior |
|---|---|---|
| `write_client_pcm(pcm_bytes)` | backend writing `_record_stream` | decode client-format frame → write to record FIFO |
| `next_api_pcm() -> bytes \| None` | `send()` read+resample+encode | read record FIFO; `None` if empty; else resample→API format→bytes |
| `write_api_pcm(pcm_bytes)` | audio-delta handler | decode API-format frame → resample→client → write play FIFO |
| `read_client_pcm(n, partial=True) -> bytes \| None` | `read_play_audio` + backend encode | drain play FIFO, add to `played_samples`, return bytes |
| `play_buffer_seconds() -> float` | `_play_stream.samples / CLIENT_SAMPLE_RATE` | remaining buffered playback (for goodbye wait) |
| `played_samples` (property) | `_played_samples` | samples sent to client this turn |
| `reset_played()` | `self._played_samples = 0` | zero the counter |
| `reset()` | `reset_stream()` (full) | create-if-missing both FIFOs |
| `reset_play()` | `reset_stream(play_stream_only=True)` | force-recreate (empty) play FIFO |

### 4.5 `src/realtime/transcript.py` — `TranscriptStore` (new)
Owns `_items: dict[str, dict]` (insertion-ordered) and `_next_seq`.

- `get_or_create(item_id, role) -> dict` — assigns a monotonic `seq` once
  (replaces `_get_or_create_item`).
- `append_delta(item_id, role, delta)` — get-or-create then `text += delta`.
- `fill_if_empty(item_id, role, text)` — set text only if currently empty
  (the append-only rule for `input_audio_transcription.completed`).
- `mark_status(item_id, status)` — set status if the item exists.
- `snapshot() -> list[tuple[str, dict]]` — `list(items.items())` for the monitor.
- `reset()` — clear items, reset `seq`.

Item record shape is unchanged: `{"role", "text", "seq", "status"}`.

### 4.6 `src/realtime/events.py` — `TurnState` + `EventDispatcher` (new)

**`TurnState`** (dataclass) — per-turn barge-in tracking:
`current_response_id`, `cancelled_response_id`, `current_item_id`,
`current_content_index`; with `reset()`.

**`EventDispatcher`** — holds refs to the owning `client`, `TranscriptStore`,
`AudioPipeline`, `TurnState`, and the `barge_in_event`.
- `async dispatch(event: dict, websocket)` — looks up `event["type"]` in a
  handler map; falls back to the existing prefix-match debug group, then a
  final debug `else`.
- One handler method per current `elif` branch, moved **verbatim** in logic:

  | Event type | Handler | Notes |
  |---|---|---|
  | `response.output_audio.delta` | `_on_audio_delta` | drop if cancelled; else track item/response, `audio.write_api_pcm` |
  | `response.output_audio_transcript.delta` | `_on_transcript_delta` | drop if cancelled; `transcript.append_delta(..., 'assistant')` |
  | `response.output_audio_transcript.done` | `_on_transcript_done` | `mark_status('done')` |
  | `conversation.item.input_audio_transcription.delta` | `_on_input_transcription_delta` | `append_delta(..., 'user')` |
  | `conversation.item.input_audio_transcription.completed` | `_on_input_transcription_completed` | `fill_if_empty`, `mark_status('done')` |
  | `conversation.item.input_audio_transcription.failed` | `_on_input_transcription_failed` | log at error |
  | `input_audio_buffer.speech_started` | `_on_speech_started` (async) | barge-in: `audio.reset_play()`, set event, truncate+cancel on ws, mark prior row `interrupted`, reserve user row |
  | `response.function_call_arguments.done` | `_on_function_call_done` | `TOOL_HANDLERS[name](client, args)` |
  | `response.done` | `_on_response_done` (async) | reset turn; clear cancelled id; if `client` ending → wait `play_buffer_seconds()+0.5` → `client.stop()` |
  | `error` | `_on_error` | log at error |

  Debug prefix group (unchanged): `session.created`, `session.updated`,
  `conversation.item.created`, `response.output_audio.`, `rate_limits.updated`.

Tool handlers keep their `(client, arguments)` signature, so
`end_conversation` still calls `client.request_end_conversation()`. `events.py`
must not import `client.py` at module scope (the `client` ref is passed in at
construction) to avoid a circular import.

### 4.7 `src/realtime/config.py` (purified)
- `REALTIME_API_URL`, `REALTIME_API_HEADERS`
- `REALTIME_API_CONFIG` — session/VAD/audio config. Audio rates reference
  `audio.formats.API_SAMPLE_RATE` for a single source of truth (value unchanged:
  24000). Still composes `TOOL_DEFINITIONS` from `tools.py`.
- `build_session_update(instructions) -> dict` — returns
  `{"type": "session.update", "session": {**REALTIME_API_CONFIG, "instructions": instructions}}`,
  moving payload assembly out of `client.configure()`.

### 4.8 `src/realtime/client.py` — `OpenAIRealtimeAPIWrapper` (renamed file, **same class name**)
Thin orchestrator. Owns `TranscriptStore`, `AudioPipeline`, `TurnState`,
`barge_in_event`, `EventDispatcher`, and session flags/params.

- `run()` — connect WS, `configure()`, `TaskGroup(send, receive, timer, status_checker)`. Unchanged structure.
- `configure(ws)` — `instructions = "\n\n".join([self._instructions, *TOOL_INSTRUCTIONS])`; send `config.build_session_update(instructions)`.
- `send(ws)` — loop: `pcm = audio.next_api_pcm()`; if `None` sleep `send_interval`; else b64 + `input_audio_buffer.append`.
- `receive(ws)` — loop: `recv` → `json.loads` → `await dispatcher.dispatch(data, ws)`.
- `timer()`, `status_checker()` — unchanged.
- `TerminateTaskGroup` moves here (re-exported from `__init__`).

**Public API** (the boundary consumed by `backend/`):

| Method | Notes |
|---|---|
| `OpenAIRealtimeAPIWrapper(api_key, session_timeout=60, send_interval=0.2, instructions=DEFAULT_INSTRUCTIONS)` | ctor |
| `recording` (property) | unchanged |
| `run()` / `start()` / `stop()` | lifecycle |
| `set_session_timeout(t)` / `set_instructions(s)` | setters |
| `request_end_conversation()` | tool hook |
| `consume_barge_in() -> bool` | unchanged |
| `write_client_pcm(pcm_bytes)` | **new** → `audio.write_client_pcm` |
| `read_client_pcm(n, partial=True) -> bytes \| None` | **new** → `audio.read_client_pcm` |
| `transcript_snapshot() -> list[tuple[str, dict]]` | **new** → `transcript.snapshot` |

`start()` resets transcript, turn, audio FIFOs, and the played counter (same
fields the current `start()` clears).

### 4.9 Package `__init__.py` exports
- `src/audio/__init__.py`: `audio_frame_to_pcm_audio`, `pcm_audio_to_audio_frame`, the format constants, `AudioPipeline`.
- `src/prompts/__init__.py`: `load_prompts`, `DEFAULT_INSTRUCTIONS`.
- `src/realtime/__init__.py`: `OpenAIRealtimeAPIWrapper`, `TerminateTaskGroup`.

---

## 5. Consumer updates — `backend/api/websocket.py`

- Imports:
  - remove `from src.audio.audio_utils import ...`
  - remove the `src.realtime.config` format-constant import
  - remove `import av` (only used for manual FIFO creation)
  - `from src.prompts import load_prompts`
  - `from src.realtime import OpenAIRealtimeAPIWrapper`
- `_handle_audio_frame`: `audio_bytes = b64decode(...)`; if empty return; `self.api_wrapper.write_client_pcm(audio_bytes)`.
- `_stream_audio_responses`: `pcm = self.api_wrapper.read_client_pcm(AUDIO_CHUNK_SIZE, partial=True)`; if `pcm`: b64 + send; else keep the existing "api_task done → conversation_ended" branch.
- `_monitor_messages`: iterate `self.api_wrapper.transcript_snapshot()` instead of `self.api_wrapper._items.items()`.
- `_start_conversation`: delete the manual `_record_stream`/`_play_stream`
  creation block (the pipeline self-initializes); keep task creation.

No other `backend/` file imports changed surface. `backend/api/routes.py`,
`models.py`, `main.py` are unaffected except any deep `src` imports, which
become package imports where applicable.

---

## 6. Test strategy — retarget white-box tests

The suite must still pass with the **same behaviors verified**. Tests are
retargeted to the extracted units (not weakened):

**`backend/tests/test_realtime_client.py`** splits by unit:
- `_get_or_create_item` / seq / insertion-order → **`TranscriptStore`** tests.
- `reset_stream`, `read_play_audio` sample counting, `reset_play` dropping
  buffered audio → **`AudioPipeline`** tests.
- `receive()`-driven behaviors (audio-delta item tracking, barge-in
  truncate-before-cancel, truncate-skip-without-playback, user-row-before-reply,
  input-delta accumulation, interrupted-row-then-new-row) → **`EventDispatcher`**
  tests: feed the same scripted events through `dispatcher.dispatch(...)` with
  the `FakeWebSocket`, assert on `TranscriptStore` / `TurnState` / `AudioPipeline`
  / sent messages. `FakeWebSocket` is reused as-is.
- Imports: `pcm_audio_to_audio_frame` from `src.audio` (or `src.audio.codec`);
  constants from `src.audio.formats`; `OpenAIRealtimeAPIWrapper`/
  `TerminateTaskGroup` from `src.realtime`.

**`backend/tests/test_websocket.py`**:
- `FakeAPIWrapper` is simplified to mirror the **new public surface**:
  `write_client_pcm`, `read_client_pcm`, `transcript_snapshot`,
  `consume_barge_in`, `run`, `stop`, `set_session_timeout`, `set_instructions`,
  `recording`. It no longer needs resamplers or raw FIFOs.
- `monkeypatch.setattr(ws_module, "OpenAIRealtimeAPIWrapper", Fake...)` is
  unchanged. Item-forwarding fakes expose items via `transcript_snapshot()`.
- Format-constant imports drop if unused after simplification.

---

## 7. Behavior-preservation constraints

- **No functional change.** Every handler branch moves verbatim in logic; only
  its location and the objects it mutates (store/pipeline/turn) change.
- The barge-in ordering guarantees are preserved exactly: `reset_play()` before
  setting the event; `conversation.item.truncate` sent **before**
  `response.cancel`; truncate skipped when `played_samples == 0`; prior
  assistant row marked `interrupted`; user row reserved on `speech_started`.
- The append-only transcript rule is preserved: `completed` fills text only when
  no deltas arrived.
- FIFO semantics preserved: full `reset()` is create-if-missing; `reset_play()`
  force-recreates. Early frames written before `run()` executes are retained.
- Numeric config values unchanged (24 kHz API, 48 kHz stereo client, VAD
  thresholds, timeouts).

---

## 8. Old → new mapping (quick reference)

| Old location | New location |
|---|---|
| `src/utils.py: get_logger` | `src/log.py` |
| `src/audio/audio_utils.py` | `src/audio/codec.py` |
| `realtime/config.py` audio constants + maps | `src/audio/formats.py` |
| `realtime/config.py: DEFAULT_INSTRUCTIONS` | `src/prompts/defaults.py` |
| `realtime/config.py` API/session config | `src/realtime/config.py` (purified) + `build_session_update` |
| `prompts/prompts.py` | `src/prompts/loader.py` |
| `realtime_client.py` `_items`/`_get_or_create_item`/`_next_seq` | `src/realtime/transcript.py` |
| `realtime_client.py` resamplers/FIFOs/`_played_samples`/`reset_stream`/`read_play_audio` | `src/audio/pipeline.py` |
| `realtime_client.py` `receive()` dispatch + turn fields | `src/realtime/events.py` |
| `realtime_client.py` orchestration + public API | `src/realtime/client.py` |

---

## 9. Verification plan

- `uv run pytest` passes (all existing + retargeted tests).
- `uv run ruff` / configured linters clean on changed files.
- Grep confirms no remaining private-attribute access from `backend/`
  (`\._items`, `\._record_stream`, `\._play_stream`, `\._resampler`).
- Manual smoke: start a conversation, speak, confirm streaming reply, live
  transcript, barge-in, and assistant-initiated `end_conversation` all work.

---

## 10. Expected LOC & honesty note

The primary win is **structure and readability**, not a dramatic line cut.
`realtime_client.py` (529 lines) redistributes into `client.py` (~170),
`events.py` (~230), `transcript.py` (~45), and `audio/pipeline.py` (~90). The
`if/elif` → dict-dispatch and small transcript helpers remove modest
duplication (~20–40 lines). Total `src/` LOC stays in the same ballpark but is
distributed into focused, testable files.

---

## 11. Out of scope / follow-ups

- Renaming the public class `OpenAIRealtimeAPIWrapper` to something shorter
  (e.g. `RealtimeClient`) — deferred to avoid churn; the name is preserved.
- Any bug discovered during the move is recorded here as a follow-up, not fixed:
  - _(none recorded yet)_
- Removing the `src`-at-root `sys.path` mechanism / packaging `src` as an
  installable package.
