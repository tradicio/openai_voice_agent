# DRY Cleanups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicated FIFO construction in the audio pipeline and duplicated send logic in the WS messenger, with zero behavior change.

**Architecture:** Two independent, behavior-preserving refactors. Each extracts a private helper that becomes the single source of truth for repeated code, then rewrites the existing methods to call it. The existing test suite is the behavior contract and must pass unchanged — no test edits.

**Tech Stack:** Python 3, FastAPI, `av` (PyAV) FIFOs, pytest / pytest-asyncio.

## Global Constraints

- Do NOT modify any file under `backend/tests/` — the tests are the behavior contract; if a test needs changing, the refactor is wrong.
- Preserve every public method signature and docstring in the touched classes.
- Preserve the wire protocol exactly (identical JSON envelopes).
- Preserve the best-effort-vs-raising distinction in the messenger.
- Tests run from repo root with `pytest` (`testpaths = ["backend/tests"]` in `pyproject.toml`).
- Helper naming (user preference): `_record_fifo` / `_play_fifo` — NOT `_new_*`.
- After each task, run `spider-lint` and fix any style/type issues.

---

### Task 1: DRY the FIFO construction in `AudioPipeline`

**Files:**
- Modify: `src/audio/pipeline.py` (methods `reset`, `reset_play`, `open`; add `_record_fifo`, `_play_fifo`)
- Test (existing, do not edit): `backend/tests/test_audio_pipeline.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: two new private methods on `AudioPipeline`:
  - `_record_fifo(self) -> av.audio.fifo.AudioFifo` — a fresh record (API-format) FIFO.
  - `_play_fifo(self) -> av.audio.fifo.AudioFifo` — a fresh play (client-format) FIFO.
  - Public methods `reset()`, `reset_play()`, `open()`, and `played_samples` semantics are unchanged.

- [ ] **Step 1: Run the existing tests to establish the green baseline**

Run: `pytest backend/tests/test_audio_pipeline.py -v`
Expected: PASS (4 tests: `test_read_client_pcm_counts_samples`, `test_reset_play_drops_buffered_audio`, `test_reset_played_zeros_counter`, `test_open_drops_buffered_audio_and_resets_counter`).

- [ ] **Step 2: Add the two private FIFO builders**

Add these two methods to the `AudioPipeline` class (place them just after `__init__`, before `write_client_pcm`):

```python
def _record_fifo(self) -> av.audio.fifo.AudioFifo:
    """A fresh record (API-format) FIFO."""
    return av.audio.fifo.AudioFifo(
        format=FORMAT_MAPPING[API_SAMPLE_WIDTH],
        layout=LAYOUT_MAPPING[API_CHANNELS],
    )

def _play_fifo(self) -> av.audio.fifo.AudioFifo:
    """A fresh play (client-format) FIFO."""
    return av.audio.fifo.AudioFifo(
        format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
        layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
    )
```

- [ ] **Step 3: Rewrite `reset`, `reset_play`, and `open` to use the builders**

Replace the existing `reset`, `reset_play`, and `open` method bodies with:

```python
def reset(self) -> None:
    """Create the FIFOs if missing (does not empty existing buffers)."""
    if self._record_stream is None:
        self._record_stream = self._record_fifo()
    if self._play_stream is None:
        self._play_stream = self._play_fifo()

def reset_play(self) -> None:
    """Force-recreate (empty) the play FIFO — drops buffered assistant audio."""
    self._play_stream = self._play_fifo()

def open(self) -> None:
    """Force-create fresh (empty) record and play FIFOs and reset the counter.

    Called at the start of each conversation so a stop/start on the same
    session discards any audio left buffered from the previous one.
    """
    self._record_stream = self._record_fifo()
    self._play_stream = self._play_fifo()
    self.played_samples = 0
```

- [ ] **Step 4: Run the tests to verify they still pass**

Run: `pytest backend/tests/test_audio_pipeline.py -v`
Expected: PASS (same 4 tests, unchanged).

- [ ] **Step 5: Lint**

Run: `spider-lint` (or the project's ruff/format/mypy commands). Fix any issues in `src/audio/pipeline.py`.
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/audio/pipeline.py
git commit -m "refactor(audio): DRY FIFO construction via _record_fifo/_play_fifo

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: DRY the send logic in `ClientMessenger`

**Files:**
- Modify: `backend/api/ws/messenger.py` (all 5 public send methods; add `_send`)
- Test (existing, do not edit): `backend/tests/test_ws_messenger.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: one new private method on `ClientMessenger`:
  - `_send(self, payload: dict, *, best_effort: bool = False) -> None` — serializes `payload` to JSON and sends it; when `best_effort` is True, swallows send exceptions, otherwise propagates them.
  - Public methods `send_status`, `send_conversation_ended`, `send_transcript`, `send_audio`, `send_clear_audio` keep their signatures and docstrings.

- [ ] **Step 1: Run the existing tests to establish the green baseline**

Run: `pytest backend/tests/test_ws_messenger.py -v`
Expected: PASS (7 tests, including `test_best_effort_send_swallows_failures` and `test_raising_send_propagates_failures`).

- [ ] **Step 2: Add the private `_send` helper**

Add this method to the `ClientMessenger` class immediately after `__init__` (before the `# --- best-effort ---` comment block):

```python
async def _send(self, payload: dict, *, best_effort: bool = False) -> None:
    """Serialize and send one envelope.

    With ``best_effort=True`` send failures are swallowed (status the
    client can live without); otherwise they propagate so a dead socket
    trips the caller's halt path.
    """
    if best_effort:
        try:
            await self._websocket.send_text(json.dumps(payload))
        except Exception:
            pass
    else:
        await self._websocket.send_text(json.dumps(payload))
```

- [ ] **Step 3: Rewrite the five public methods to delegate to `_send`**

Replace the five method bodies (keep their signatures, docstrings, and the two `# ---` section comments) so they read:

```python
# --- best-effort: swallow send failures ---

async def send_status(self, message: str) -> None:
    """Send a status message, ignoring send failures."""
    await self._send(
        {"type": "status", "message": message}, best_effort=True
    )

async def send_conversation_ended(self) -> None:
    """Tell the client the call ended server-side, ignoring send failures.

    Emitted when the assistant's ``end_conversation`` tool (or the
    session timeout) stops the conversation on the server, so the
    client can reset its UI back to the idle "Start Conversation"
    state without the user having pressed stop.
    """
    await self._send({"type": "conversation_ended"}, best_effort=True)

# --- raising: let failures propagate ---

async def send_transcript(
    self, role: str | None, seq: int | None, delta: str
) -> None:
    """Forward a transcript delta to the client."""
    await self._send({
        "type": "transcript",
        "role": role,
        "seq": seq,
        "delta": delta,
    })

async def send_audio(self, b64_data: str) -> None:
    """Send a base64-encoded PCM audio chunk to the client."""
    await self._send({"type": "audio", "data": b64_data})

async def send_clear_audio(self) -> None:
    """Tell the client to drop audio it has already scheduled."""
    await self._send({"type": "clear_audio"})
```

- [ ] **Step 4: Run the tests to verify they still pass**

Run: `pytest backend/tests/test_ws_messenger.py -v`
Expected: PASS (same 7 tests, unchanged).

- [ ] **Step 5: Run the full backend suite**

Run: `pytest`
Expected: PASS (entire suite green — confirms no cross-module regression).

- [ ] **Step 6: Lint**

Run: `spider-lint` (or the project's ruff/format/mypy commands). Fix any issues in `backend/api/ws/messenger.py`.
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add backend/api/ws/messenger.py
git commit -m "refactor(ws): DRY messenger sends via private _send helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**
- Change A (pipeline FIFO DRY) → Task 1. ✓
- Change B (messenger `_send` DRY) → Task 2. ✓
- Change C (routes) → explicitly a non-goal; no task, correct. ✓
- Verification (existing suite + lint, no test edits) → Task 1 steps 1/4/5, Task 2 steps 1/4/5/6, plus full `pytest` in Task 2 step 5. ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N" — every code step shows full code. ✓

**3. Type consistency:** Helper names `_record_fifo`/`_play_fifo` and `_send(payload, *, best_effort=False)` are used identically in the Interfaces blocks and the code steps. Constant names (`FORMAT_MAPPING`, `LAYOUT_MAPPING`, `API_SAMPLE_WIDTH`, `API_CHANNELS`, `CLIENT_SAMPLE_WIDTH`, `CLIENT_CHANNELS`) match the existing imports in `pipeline.py`. ✓
