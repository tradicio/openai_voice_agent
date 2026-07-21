# Transcript: one row per speaker turn (item_id-keyed)

Date: 2026-07-21
Status: Approved (design)

## Problem

In the running app, the transcript panel shows **only assistant text, all collapsed into
a single row**. User ("You:") rows never appear, and successive assistant turns pile into
one bubble instead of getting their own row.

Two independent defects combine to produce this:

1. **Backend — user transcript never surfaces.** On `input_audio_buffer.speech_started`
   the backend appends a user container with `content=None`. The monitor loop
   (`websocket.py:_monitor_messages`) skips any message with falsy content
   (`if not content: continue`), so the slot is never forwarded until it gains text. If the
   Whisper transcript never fills it, the user row never appears. The GA `gpt-realtime` API
   also emits `conversation.item.input_audio_transcription.delta`, which the current code
   does not handle at all — only `.completed`.

2. **Frontend — turns merge into one row.** `useAudioStream.ts:rebuildMerged()` fuses
   consecutive same-role messages into a single bubble. With user rows missing (defect 1),
   every assistant turn becomes adjacent and fuses into one row.

The desired behavior: **a dedicated row per speaker, and a new row after each turn finishes
or is interrupted.**

## Chosen approach

**Approach B — `item_id`-keyed rows.** Rekey the transcript model on the API's stable
`item_id` instead of list position, and assign a monotonic `seq` at item-creation time to
carry row order to the client. This matches how the openai-agents SDK models transcripts
(separate typed items per speaker) and removes both the reserved-empty-slot hack and the
frontend merge.

Rejected: Approach A (minimal positional patch — keeps the fragile reserved-slot ordering
and stale-local-variable delta attachment) and Approach C (hybrid). B was chosen because the
observed bugs are symptoms of using list position as identity when the API already provides
stable item IDs.

## Phase 0 — Confirm the cause (diagnosis first)

Before any behavioral change, add **temporary** debug logging in
`realtime_client.receive()` for:

- `input_audio_buffer.speech_started` — log `item_id`
- `conversation.item.input_audio_transcription.delta` — log `item_id` + delta
- `conversation.item.input_audio_transcription.completed` — log `item_id` + transcript

Run one short conversation and inspect logs:

- **Events arrive** → confirmed forwarding/merge bug; proceed with the fix below.
- **Events do not arrive** → the input-transcription config for `gpt-realtime` is the
  problem; revisit `REALTIME_API_CONFIG.audio.input.transcription` before proceeding.

This logging is removed (or dropped to a quieter level) once the cause is confirmed.

## Backend design

### Data model (`src/realtime/realtime_client.py`)

Replace `self._messages: list[dict]` and the `message` / `user_message` local variables with:

- `self._items: dict[str, dict]` — `item_id -> {"role", "text", "seq", "status"}`,
  insertion-ordered.
- `self._next_seq: int` — monotonic counter. `seq` is assigned once, when an item is first
  created, and defines row order on the client.
- `status ∈ {"in_progress", "done", "interrupted"}`.

A small helper creates-or-returns an item by `item_id`, assigning `seq` on first creation.

### Event handling (`receive()`)

- `input_audio_buffer.speech_started`
  - Create the **user** item keyed by its `item_id` (arrives before the assistant reply, so
    its `seq` sorts first).
  - Existing barge-in behavior is preserved: clear the play stream; if an assistant item is
    still streaming, mark it `status="interrupted"`, send `response.cancel`, record the
    cancelled `response_id`, and set the barge-in event. The next assistant response carries a
    fresh `item_id`, so it becomes a new row automatically.
- `conversation.item.input_audio_transcription.delta` *(newly handled)* and `.completed`
  - Append text to the user item identified by `item_id`. `.completed` sets
    `status="done"`.
- `response.output_audio_transcript.delta`
  - Create/append the **assistant** item keyed by `item_id`. Preserve the existing
    cancelled-response drop guard so leftover deltas for a cancelled response are ignored.
- `response.output_audio_transcript.done`
  - Mark the assistant item `status="done"`.
- `response.done`
  - Unchanged control flow (cancelled-id cleanup, end-of-conversation handling).

`valid_messages` (used elsewhere) is redefined to return items with non-empty text in `seq`
order, preserving its existing contract for any consumer.

### Monitor (`backend/api/websocket.py:_monitor_messages`)

- Poll `self.api_wrapper._items` instead of `_messages`.
- Track `last_transcript_lengths: dict[str, int]` keyed by `item_id`.
- Forward `{"type": "transcript", "role": <role>, "seq": <seq>, "delta": <new text>}`.
- The `seq` field replaces the old list-position `index`. Empty items simply have no text yet
  and are naturally not forwarded until they do — no special skip logic needed.

## Frontend design

### `frontend/hooks/useAudioStream.ts`

- Rekey `rawMessagesRef` from `index` to `seq`.
- **Remove `rebuildMerged()`, `mergedRef`, and `indexToBubblePos`** — all merge machinery.
- `Message` / `RawMessage`: `index` field becomes `seq`.
- `applyTranscriptDelta(seq, role, delta)`: upsert the `seq`'s text in the map; if `seq` is
  new, `insertSorted` it into the ordered list. Rows are derived by mapping the sorted `seq`
  list to `{role, text, seq}` — one row per `seq`, never merged.
- A finished or interrupted turn yields a new `seq` on the next turn, so "new row after each
  finish/interruption" needs no special-casing.

### `frontend/components/TranscriptDisplay.tsx`

- Key rows by `seq`.
- No streaming/finalization indicator (kept minimal per decision). One `<div class="message
  {role}">` per turn as today.

## Testing

### Backend (extend existing pytest suites)

`backend/tests/test_realtime_client.py`:
- `speech_started` creates a user item; its `seq` is lower than a following assistant item's.
- input transcription `.delta` and `.completed` both populate the correct user item by
  `item_id`.
- assistant deltas build a separate assistant item; `.done` sets `status="done"`.
- an interruption (`speech_started` mid-assistant-stream) marks the prior assistant item
  `interrupted` and the next assistant response yields a **distinct** item (no merge).

`backend/tests/test_websocket.py` (using the existing `FakeAPIWrapper`):
- the monitor forwards one delta stream per `item_id`, each carrying the correct `role` and
  `seq`, and never re-sends already-forwarded text.

### Frontend

No JS test runner is currently configured in `frontend/`. Verify by reasoning plus a manual
run against the Phase 0 diagnostic build. No Vitest/tooling added (per decision).

## Out of scope (YAGNI)

- Transcript persistence/history across sessions.
- Editing transcripts.
- Styling redesign beyond per-row rendering.
- Live streaming indicator (deferred).
```
