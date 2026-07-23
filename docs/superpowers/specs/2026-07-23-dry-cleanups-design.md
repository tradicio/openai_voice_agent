# DRY cleanups: audio pipeline & WS messenger

**Date:** 2026-07-23
**Status:** Approved for implementation
**Scope:** Two behavior-preserving refactors that remove duplication. No feature
changes, no API changes, no performance claims.

## Background & honest framing

The original request was to "reduce the number of functions to make execution
faster and the code cleaner." That premise does not hold for this codebase:

- **It is I/O-bound.** Time is spent on the OpenAI Realtime WebSocket, `av`
  audio resampling (C), and network round-trips. Python function-call count is
  not a bottleneck; merging functions yields **no measurable speedup**.
- **It is already lean and just-refactored** (~1,700 LOC non-test; the
  `refactor/backend-ws-modularization` merge). Aggressively collapsing functions
  would reduce readability and testability.

Decision (agreed with the user): do only the **safe DRY cleanups** below. These
make the code cleaner to read without changing behavior, performance, or the
public surface. Function count barely moves — that is expected and correct.

## Goals

- Remove the repeated `av.audio.fifo.AudioFifo(...)` literals in
  `src/audio/pipeline.py` (currently 5 copies in 2 flavors).
- Remove the repeated `json.dumps({...}) + send_text` (and the duplicated
  best-effort `try/except`) in `backend/api/ws/messenger.py`.

## Non-goals

- No changes to `routes.py` (the two trivial GET handlers stay as-is — merging
  hurts clarity).
- No removal of the `client.py` delegator/facade methods (deliberate
  encapsulation; removing them would break it).
- No behavior, wire-protocol, or public-API changes.
- No new or modified tests are expected; the existing suite is the contract.

## Change A — `src/audio/pipeline.py`: DRY the FIFO construction

Two private builders (named per user preference — **not** `_new_*`):

```python
def _record_fifo(self):
    return av.audio.fifo.AudioFifo(
        format=FORMAT_MAPPING[API_SAMPLE_WIDTH],
        layout=LAYOUT_MAPPING[API_CHANNELS],
    )

def _play_fifo(self):
    return av.audio.fifo.AudioFifo(
        format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
        layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
    )
```

Rewrite the three existing methods to use them, preserving semantics exactly:

- `reset()` — create each FIFO **only if it is currently `None`** (unchanged:
  does not empty existing buffers).
- `reset_play()` — `self._play_stream = self._play_fifo()` (force-recreate/empty
  the play FIFO).
- `open()` — `self._record_stream = self._record_fifo()`,
  `self._play_stream = self._play_fifo()`, `self.played_samples = 0`.

Result: the 4-line `AudioFifo(...)` literal drops from 5 copies to the 2 helper
definitions. Public methods and their docstrings are unchanged.

## Change B — `backend/api/ws/messenger.py`: one private `_send`

Add one private helper that centralizes serialization and the best-effort guard:

```python
async def _send(self, payload: dict, *, best_effort: bool = False) -> None:
    if best_effort:
        try:
            await self._websocket.send_text(json.dumps(payload))
        except Exception:
            pass
    else:
        await self._websocket.send_text(json.dumps(payload))
```

Keep all five public methods (they are the interface) as thin one-liners:

- `send_status` → `_send({"type": "status", "message": message}, best_effort=True)`
- `send_conversation_ended` →
  `_send({"type": "conversation_ended"}, best_effort=True)`
- `send_transcript` →
  `_send({"type": "transcript", "role": role, "seq": seq, "delta": delta})`
- `send_audio` → `_send({"type": "audio", "data": b64_data})`
- `send_clear_audio` → `_send({"type": "clear_audio"})`

The best-effort-vs-raising distinction is preserved exactly: `send_status` and
`send_conversation_ended` swallow failures; the other three propagate. Docstrings
and the class-level comment stay.

## Verification

1. Run the existing backend suite — must pass unchanged:
   `pytest backend/tests/test_audio_pipeline.py backend/tests/test_ws_messenger.py`
   then the full `pytest backend/tests/`.
2. Run `spider-lint` (ruff/format/type checks) and fix any style/type issues.
3. Confirm no test files were modified — the tests are the behavior contract; if
   a test needs changing, the refactor is wrong.

## Expected net effect

~15–20 fewer duplicated lines; clearer, single-source-of-truth construction and
send logic; identical behavior, wire protocol, and performance.
