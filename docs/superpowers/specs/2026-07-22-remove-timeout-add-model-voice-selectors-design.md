# Remove timeout slider · Add model + voice selectors · Consolidate dropdowns

**Date:** 2026-07-22
**Status:** Approved (design)

## Summary

Three coordinated changes to the OpenAI voice agent:

- **A. Remove session timeout entirely** — delete the timeout slider and all
  server-side timer machinery. A conversation now ends only when the user
  stops it, when the assistant calls the `end_conversation` tool, or on a
  stream error.
- **B. Add model and voice selection** — the realtime model (currently
  hardcoded in the WebSocket URL) and the voice (currently hardcoded in the
  session config) become user-selectable, flowing through the same
  client→`config`-message→wrapper path the prompt already uses.
- **C. Consolidate dropdowns** — replace `PromptSelector` and the two new
  selectors with a single generic `Selector` component, removing duplication.

## Decisions (from brainstorming)

1. Timeout is **removed entirely** (no fixed default, no timer task).
2. Model/voice lists are **served by the backend** (endpoints like
   `/api/prompts`), giving a single source of truth.
3. The backend **validates** the client-sent model/voice against an allowlist
   (same as `prompt_key`); unknown values are rejected with a status message.
4. Models offered: `gpt-realtime-2` (default), `gpt-realtime`.
5. Voices offered (full set): `alloy` (default), `ash`, `ballad`, `coral`,
   `echo`, `sage`, `shimmer`, `verse`, `marin`, `cedar`.
6. The three dropdowns are consolidated into **one generic `Selector`**.

## Architecture context (current state)

- `frontend/app/page.tsx` holds `selectedPrompt` + `sessionTimeout` and renders
  `PromptSelector`, `TimeoutSlider`, `ConversationButton`, `TranscriptDisplay`.
- `frontend/hooks/useAudioStream.ts` opens the WebSocket and, on open, sends a
  `config` message `{prompt_key, timeout}` followed by a `start` control.
- `backend/api/websocket.py` `AudioStreamSession._handle_config` applies timeout
  and prompt to `OpenAIRealtimeAPIWrapper`.
- `src/realtime/config.py` hardcodes the model in `REALTIME_API_URL`
  (`?model=gpt-realtime-2`) and the voice in `REALTIME_API_CONFIG`
  (`audio.output.voice = 'alloy'`).
- `src/realtime/client.py` runs four tasks in a `TaskGroup`: `send`, `receive`,
  `timer`, `status_checker`.

**Timing note (why B is safe):** the model is needed *before* the WebSocket to
OpenAI is opened, and the voice is needed when `configure()` sends
`session.update`. Both happen inside `run()`, which is started only after the
`config` message is received and applied (`start` control triggers
`_start_conversation`). So setters that run before `start` are sufficient — no
mid-session model/voice change is required or supported.

## Part A — Remove timeout

| Layer | File | Change |
|---|---|---|
| Realtime client | `src/realtime/client.py` | Remove `timer()` method, `_session_timeout` attribute + constructor param, `set_session_timeout()`, the `task_group.create_task(self.timer())` line, and the now-unused `import datetime`. |
| WS message model | `backend/api/models.py` | Remove `timeout` field from `ConfigMessage` (and update its docstring). |
| WS handler | `backend/api/websocket.py` | Remove `self.session_timeout` init and the `if message.timeout is not None:` branch in `_handle_config`. |
| REST routes | `backend/api/routes.py` | Delete `TimeoutRequest` and `POST /api/session/timeout`. |
| Tests | `backend/tests/test_api.py` | Remove the 8 timeout tests (`test_set_timeout_*`, `test_timeout_*`). |
| Frontend component | `frontend/components/TimeoutSlider.tsx` | Delete file. |
| Frontend page | `frontend/app/page.tsx` | Remove `sessionTimeout` state, the `<TimeoutSlider>` render, and the import. |
| Frontend hook | `frontend/hooks/useAudioStream.ts` | Remove `timeout` param from `useAudioStream` and from the `sendConfigMessage` call. |
| Frontend api lib | `frontend/lib/api.ts` | Remove `timeout` from `sendConfigMessage`'s config type. |

After removal, `OpenAIRealtimeAPIWrapper.run()` creates three tasks: `send`,
`receive`, `status_checker`. The `TerminateTaskGroup` flow is otherwise
unchanged.

## Part B — Model + voice selection

### Single source of truth: `src/realtime/config.py`

Add allowlists and defaults, consumed by both the routes and the WS validator:

```python
MODELS = [
    {"key": "gpt-realtime-2", "label": "GPT Realtime 2"},
    {"key": "gpt-realtime",   "label": "GPT Realtime"},
]
DEFAULT_MODEL = "gpt-realtime-2"

VOICES = [
    {"key": "alloy",   "label": "Alloy"},
    {"key": "ash",     "label": "Ash"},
    {"key": "ballad",  "label": "Ballad"},
    {"key": "coral",   "label": "Coral"},
    {"key": "echo",    "label": "Echo"},
    {"key": "sage",    "label": "Sage"},
    {"key": "shimmer", "label": "Shimmer"},
    {"key": "verse",   "label": "Verse"},
    {"key": "marin",   "label": "Marin"},
    {"key": "cedar",   "label": "Cedar"},
]
DEFAULT_VOICE = "alloy"

MODEL_KEYS = {m["key"] for m in MODELS}
VOICE_KEYS = {v["key"] for v in VOICES}
```

Replace the `REALTIME_API_URL` constant and the module-level
`REALTIME_API_CONFIG` dict with factories, so nothing shared is mutated:

```python
def build_realtime_url(model: str = DEFAULT_MODEL) -> str:
    return f"wss://api.openai.com/v1/realtime?model={model}"

def build_api_config(voice: str = DEFAULT_VOICE) -> dict:
    # returns the former REALTIME_API_CONFIG dict with audio.output.voice = voice
    ...

def build_session_update(instructions: str, voice: str = DEFAULT_VOICE) -> dict:
    return dict(
        type="session.update",
        session=dict(build_api_config(voice), instructions=instructions),
    )
```

### `src/realtime/client.py`

- `__init__` gains `model: str = DEFAULT_MODEL` and `voice: str = DEFAULT_VOICE`
  params, stored as `self._model` / `self._voice`.
- Add `set_model(model)` and `set_voice(voice)` setters (mirroring the removed
  `set_session_timeout` / existing `set_instructions`).
- `run()` connects to `build_realtime_url(self._model)` instead of the constant.
- `configure()` calls `build_session_update(instructions, self._voice)`.

### `backend/api/models.py`

`ConfigMessage` gains `model: str | None = None` and `voice: str | None = None`
(keeping `prompt_key`; `timeout` removed per Part A).

### `backend/api/websocket.py`

- `AudioStreamSession.__init__` sets `self.model = DEFAULT_MODEL` and
  `self.voice = DEFAULT_VOICE`.
- `_handle_config` adds two branches mirroring `prompt_key`:
  - if `message.model is not None`: if in `MODEL_KEYS`, store + `set_model`,
    else `_send_status("Model '<x>' not found")`.
  - if `message.voice is not None`: if in `VOICE_KEYS`, store + `set_voice`,
    else `_send_status("Voice '<x>' not found")`.

### `backend/api/routes.py`

Add two endpoints sourced from the config allowlists (imported from
`src.realtime.config`), matching the `/api/prompts` response shape:

- `GET /api/models` → `{"models": [{"key", "label"}, ...]}`
- `GET /api/voices` → `{"voices": [{"key", "label"}, ...]}`

(These lists are static, so no 404-on-empty guard is needed the way prompts
has one; they always return the configured set.)

## Part C — Generic `Selector` component

Create `frontend/components/Selector.tsx`, a reusable fetch-list-then-`<select>`
widget generalizing the current `PromptSelector`:

Props:
- `endpoint: string` — e.g. `/api/prompts`, `/api/models`, `/api/voices`
- `responseKey: string` — the array key in the response (`prompts` / `models` /
  `voices`)
- `label: string` — the field label
- `onSelect: (key: string) => void`
- `disabled: boolean`

Behavior (ported from `PromptSelector`): fetch on mount from
`NEXT_PUBLIC_API_URL` + endpoint, populate options, auto-select the first item
(calling `onSelect` so the parent state initializes), render an error message on
fetch failure.

- Delete `frontend/components/PromptSelector.tsx`.
- `frontend/app/page.tsx` renders three `<Selector>`s (prompt, model, voice),
  each wired to its own state (`selectedPrompt`, `selectedModel`,
  `selectedVoice`).
- `frontend/hooks/useAudioStream.ts` takes `promptKey`, `model`, `voice` and
  sends them in the `config` message.
- `frontend/lib/api.ts`: `sendConfigMessage` config type becomes
  `{ prompt_key?: string; model?: string; voice?: string }`.

## Data flow (after changes)

```
Selector (prompt) ─┐
Selector (model)  ─┤→ page.tsx state ─→ useAudioStream ─→ WS "config"
Selector (voice)  ─┘                                   {prompt_key, model, voice}
                                                              │
                          backend _handle_config (validate) ──┤
                                                              ├─ set_instructions
                                                              ├─ set_model  → build_realtime_url
                                                              └─ set_voice  → build_session_update
                                                                     │
                                                       OpenAIRealtimeAPIWrapper.run()
```

## Error handling

- Unknown model/voice/prompt from the client → `_send_status` error message; the
  session keeps its current (default or previously-set) value. No crash.
- `Selector` fetch failure → inline error text, same as today's `PromptSelector`.
- Backend `/api/models` and `/api/voices` are static and always succeed.

## Testing

`backend/tests/test_api.py`:
- Remove all timeout tests.
- Add `test_get_models` and `test_get_voices` mirroring `test_get_prompts`
  (200, expected key present, non-empty list, each item has `key` + `label`).

Manual/e2e check: select a non-default model + voice, start a conversation,
confirm the OpenAI connection uses the chosen model (URL) and the reply audio
uses the chosen voice.

## Documentation

- `backend/DEVELOPMENT.md`: remove the `set_session_timeout()` line,
  the `POST /api/session/timeout` section, and the `timeout` field in the
  `config` message example; add `/api/models`, `/api/voices`, and the
  `model`/`voice` config fields; update the test count.
- `README.md`: update any timeout mention; note model/voice selection.

## Out of scope (YAGNI)

- Mid-session model/voice switching.
- Persisting selections across page reloads.
- Per-model voice compatibility filtering (all voices offered for all models).
