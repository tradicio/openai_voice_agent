# Remove Timeout · Add Model + Voice Selectors · Consolidate Dropdowns — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the session-timeout feature entirely, make the realtime model and voice user-selectable through the existing config path, and consolidate the three list-dropdowns into one reusable component.

**Architecture:** Model/voice allowlists live in `src/realtime/config.py` as the single source of truth, exposed by new `GET /api/models` and `GET /api/voices` endpoints and validated in the WebSocket config handler. The frontend fetches each list into a generic `Selector` component and sends the chosen `prompt_key`/`model`/`voice` in the WebSocket `config` message; the backend applies them to `OpenAIRealtimeAPIWrapper` via setters before the OpenAI connection opens.

**Tech Stack:** Python 3.12 · FastAPI · Pydantic v2 · pytest + `fastapi.testclient` · websockets · Next.js 16 / React 19 · TypeScript · Tailwind.

## Global Constraints

- Backend tests run with: `cd backend && pytest tests/test_api.py -v` (imports `from main import app`; `src` is importable because `main.py` inserts the repo root on `sys.path`).
- Frontend verification runs with: `cd frontend && npm run build` and `cd frontend && npm run lint`. There is **no** frontend unit-test framework — do not add one.
- Default model is `gpt-realtime-2`; default voice is `alloy`.
- Models offered: `gpt-realtime-2`, `gpt-realtime`. Voices offered: `alloy`, `ash`, `ballad`, `coral`, `echo`, `sage`, `shimmer`, `verse`, `marin`, `cedar`.
- The backend validates client-sent `model`/`voice`/`prompt_key` against allowlists; unknown values produce a status message and leave the current value unchanged (no crash).
- Follow existing code style: `dict(...)` factory style in `config.py`, NumPy-style docstrings on public backend functions, `'use client'` + Tailwind label classes on frontend components.
- End every commit message with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

**Backend**
- `src/realtime/config.py` — *Modify.* Add `MODELS`, `VOICES`, `DEFAULT_MODEL`, `DEFAULT_VOICE`, `MODEL_KEYS`, `VOICE_KEYS`; replace `REALTIME_API_URL` constant with `build_realtime_url()`; replace `REALTIME_API_CONFIG` constant with `build_api_config(voice)`; extend `build_session_update()` with a `voice` param.
- `src/realtime/client.py` — *Modify.* Remove timer/timeout; add `model`/`voice` constructor params + `set_model()`/`set_voice()`; use `build_realtime_url()` and pass voice to `build_session_update()`.
- `backend/api/models.py` — *Modify.* `ConfigMessage`: drop `timeout`, add `model`/`voice`.
- `backend/api/routes.py` — *Modify.* Delete `TimeoutRequest` + `POST /api/session/timeout`; add `GET /api/models` and `GET /api/voices`.
- `backend/api/websocket.py` — *Modify.* Drop `self.session_timeout` + timeout branch; add validated model/voice branches.
- `backend/tests/test_api.py` — *Modify.* Remove timeout tests; add model/voice endpoint tests.

**Frontend**
- `frontend/components/Selector.tsx` — *Create.* Generic fetch-list-then-`<select>` widget.
- `frontend/components/PromptSelector.tsx` — *Delete.*
- `frontend/components/TimeoutSlider.tsx` — *Delete.*
- `frontend/lib/api.ts` — *Modify.* `sendConfigMessage` config type: drop `timeout`, add `model`/`voice`.
- `frontend/hooks/useAudioStream.ts` — *Modify.* Drop `timeout` param; add `model`/`voice`.
- `frontend/app/page.tsx` — *Modify.* Drop timeout state + slider; add model/voice state + three `<Selector>`s.

**Docs**
- `backend/DEVELOPMENT.md`, `README.md` — *Modify.*

---

## Task 1: Backend config — allowlists and factories

**Files:**
- Modify: `src/realtime/config.py`
- Test: `backend/tests/test_config.py` (Create)

**Interfaces:**
- Consumes: `src.audio.formats.API_SAMPLE_RATE`, `src.realtime.tools.TOOL_DEFINITIONS` (existing).
- Produces:
  - `MODELS: list[dict[str, str]]`, `VOICES: list[dict[str, str]]` — each item `{"key", "label"}`.
  - `DEFAULT_MODEL = "gpt-realtime-2"`, `DEFAULT_VOICE = "alloy"`.
  - `MODEL_KEYS: set[str]`, `VOICE_KEYS: set[str]`.
  - `build_realtime_url(model: str = DEFAULT_MODEL) -> str`.
  - `build_api_config(voice: str = DEFAULT_VOICE) -> dict`.
  - `build_session_update(instructions: str, voice: str = DEFAULT_VOICE) -> dict`.
  - `REALTIME_API_HEADERS: dict` (unchanged, still exported).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config.py`:

```python
from src.realtime.config import (
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    MODEL_KEYS,
    MODELS,
    VOICE_KEYS,
    VOICES,
    build_api_config,
    build_realtime_url,
    build_session_update,
)


def test_defaults_are_in_allowlists():
    assert DEFAULT_MODEL in MODEL_KEYS
    assert DEFAULT_VOICE in VOICE_KEYS


def test_models_and_voices_shape():
    assert {"gpt-realtime-2", "gpt-realtime"} == MODEL_KEYS
    assert len(VOICES) == 10
    assert "cedar" in VOICE_KEYS
    for item in [*MODELS, *VOICES]:
        assert set(item) == {"key", "label"}


def test_build_realtime_url_uses_model():
    assert build_realtime_url("gpt-realtime") == (
        "wss://api.openai.com/v1/realtime?model=gpt-realtime"
    )
    assert build_realtime_url() == (
        "wss://api.openai.com/v1/realtime?model=gpt-realtime-2"
    )


def test_build_api_config_injects_voice_without_shared_mutation():
    a = build_api_config("verse")
    b = build_api_config("coral")
    assert a["audio"]["output"]["voice"] == "verse"
    assert b["audio"]["output"]["voice"] == "coral"
    # Distinct nested dicts, not a shared/mutated module-level object.
    assert a["audio"]["output"] is not b["audio"]["output"]


def test_build_session_update_carries_voice_and_instructions():
    payload = build_session_update("be nice", voice="sage")
    assert payload["type"] == "session.update"
    assert payload["session"]["instructions"] == "be nice"
    assert payload["session"]["audio"]["output"]["voice"] == "sage"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_config.py -v`
Expected: FAIL — `ImportError` for `MODELS` / `build_realtime_url` / `build_api_config`.

- [ ] **Step 3: Rewrite `src/realtime/config.py`**

Replace the entire file contents with:

```python
from src.audio.formats import API_SAMPLE_RATE
from src.realtime.tools import TOOL_DEFINITIONS

# Selectable realtime models (single source of truth; served by the API and
# used to validate client-requested values).
MODELS = [
    {"key": "gpt-realtime-2", "label": "GPT Realtime 2"},
    {"key": "gpt-realtime", "label": "GPT Realtime"},
]
DEFAULT_MODEL = "gpt-realtime-2"

# Selectable assistant voices.
VOICES = [
    {"key": "alloy", "label": "Alloy"},
    {"key": "ash", "label": "Ash"},
    {"key": "ballad", "label": "Ballad"},
    {"key": "coral", "label": "Coral"},
    {"key": "echo", "label": "Echo"},
    {"key": "sage", "label": "Sage"},
    {"key": "shimmer", "label": "Shimmer"},
    {"key": "verse", "label": "Verse"},
    {"key": "marin", "label": "Marin"},
    {"key": "cedar", "label": "Cedar"},
]
DEFAULT_VOICE = "alloy"

MODEL_KEYS = {m["key"] for m in MODELS}
VOICE_KEYS = {v["key"] for v in VOICES}

# Extra headers for the Realtime API handshake (none required today).
REALTIME_API_HEADERS = {}


def build_realtime_url(model: str = DEFAULT_MODEL) -> str:
    """Build the Realtime API WebSocket URL for the given model.

    Parameters
    ----------
    model : str
        The realtime model key (e.g. ``"gpt-realtime-2"``).

    Returns
    -------
    str
        The full ``wss://`` URL including the ``model`` query parameter.
    """
    return f"wss://api.openai.com/v1/realtime?model={model}"


def build_api_config(voice: str = DEFAULT_VOICE) -> dict:
    """Build a fresh Realtime session config with the given output voice.

    A new dict (including nested dicts) is returned on every call so callers
    can safely inject per-session values without mutating shared state.

    Parameters
    ----------
    voice : str
        The output voice key (e.g. ``"alloy"``).

    Returns
    -------
    dict
        The ``session`` config payload minus ``instructions``.
    """
    return dict(
        type='realtime',
        output_modalities=['audio'],
        audio=dict(
            input=dict(
                format=dict(type='audio/pcm', rate=API_SAMPLE_RATE),
                transcription=dict(
                    model='gpt-4o-transcribe',
                ),
                turn_detection=dict(
                    type='server_vad',
                    interrupt_response=True,
                    threshold=0.5,
                    prefix_padding_ms=100,
                    silence_duration_ms=800,
                ),
            ),
            output=dict(
                format=dict(type='audio/pcm', rate=API_SAMPLE_RATE),
                voice=voice,
            ),
        ),
        tools=TOOL_DEFINITIONS,
        tool_choice='auto',
    )


def build_session_update(
    instructions: str, voice: str = DEFAULT_VOICE
) -> dict:
    """Build the ``session.update`` payload with instructions and voice.

    Parameters
    ----------
    instructions : str
        The assistant system prompt.
    voice : str
        The output voice key.

    Returns
    -------
    dict
        A ready-to-send ``session.update`` message.
    """
    return dict(
        type='session.update',
        session=dict(build_api_config(voice), instructions=instructions),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_config.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/realtime/config.py backend/tests/test_config.py
git commit -m "feat: add model/voice allowlists and config factories

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Realtime client — remove timer, add model/voice

**Files:**
- Modify: `src/realtime/client.py`
- Test: `backend/tests/test_client.py` (Create)

**Interfaces:**
- Consumes: `build_realtime_url`, `build_session_update`, `DEFAULT_MODEL`, `DEFAULT_VOICE`, `REALTIME_API_HEADERS` from Task 1.
- Produces (on `OpenAIRealtimeAPIWrapper`):
  - `__init__(self, api_key, send_interval=0.2, instructions=DEFAULT_INSTRUCTIONS, model=DEFAULT_MODEL, voice=DEFAULT_VOICE)` — note: **no** `session_timeout` param.
  - `set_model(self, model: str) -> None`, `set_voice(self, voice: str) -> None`, existing `set_instructions`.
  - Attributes `self._model`, `self._voice`.
  - **No** `timer` method and **no** `set_session_timeout` method.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_client.py`:

```python
from src.realtime import OpenAIRealtimeAPIWrapper
from src.realtime.config import DEFAULT_MODEL, DEFAULT_VOICE


def _make():
    return OpenAIRealtimeAPIWrapper(api_key="test-key")


def test_defaults_for_model_and_voice():
    w = _make()
    assert w._model == DEFAULT_MODEL
    assert w._voice == DEFAULT_VOICE


def test_set_model_and_voice():
    w = _make()
    w.set_model("gpt-realtime")
    w.set_voice("verse")
    assert w._model == "gpt-realtime"
    assert w._voice == "verse"


def test_constructor_overrides():
    w = OpenAIRealtimeAPIWrapper(
        api_key="k", model="gpt-realtime", voice="coral"
    )
    assert w._model == "gpt-realtime"
    assert w._voice == "coral"


def test_timeout_api_removed():
    w = _make()
    assert not hasattr(w, "timer")
    assert not hasattr(w, "set_session_timeout")
    assert not hasattr(w, "_session_timeout")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_client.py -v`
Expected: FAIL — `test_defaults_for_model_and_voice` errors on `w._model` (AttributeError) and `test_timeout_api_removed` fails (`timer` still present).

- [ ] **Step 3: Edit the class attribute block and `__init__`**

In `src/realtime/client.py`, replace the class-attribute block (currently lines ~34-39):

```python
class OpenAIRealtimeAPIWrapper:
    _api_key: str
    _session_timeout: int | float
    _send_interval: float
    _instructions: str
    _ending: bool
    _recording: bool
```

with:

```python
class OpenAIRealtimeAPIWrapper:
    _api_key: str
    _send_interval: float
    _instructions: str
    _model: str
    _voice: str
    _ending: bool
    _recording: bool
```

Replace the `__init__` signature and body head (currently lines ~41-59):

```python
    def __init__(
        self,
        api_key: str,
        session_timeout: int | float = 60,
        send_interval: float = 0.2,
        instructions: str = DEFAULT_INSTRUCTIONS
    ):
        """
        Args:
            api_key (str): OpenAI API key
            session_timeout (int | float): Voice chat session timeout duration (seconds)
            send_interval (float): Interval for sending voice data (seconds)
            instructions (str): System instructions (prompt) for the assistant
        """
        self._api_key = api_key
        self._session_timeout = session_timeout
        self._send_interval = send_interval
        self._instructions = instructions
        self._ending = False
```

with:

```python
    def __init__(
        self,
        api_key: str,
        send_interval: float = 0.2,
        instructions: str = DEFAULT_INSTRUCTIONS,
        model: str = DEFAULT_MODEL,
        voice: str = DEFAULT_VOICE,
    ):
        """
        Args:
            api_key (str): OpenAI API key
            send_interval (float): Interval for sending voice data (seconds)
            instructions (str): System instructions (prompt) for the assistant
            model (str): Realtime model key used for the connection
            voice (str): Output voice key for the assistant
        """
        self._api_key = api_key
        self._send_interval = send_interval
        self._instructions = instructions
        self._model = model
        self._voice = voice
        self._ending = False
```

- [ ] **Step 4: Update imports**

Replace the config import block (currently lines ~11-15):

```python
from src.realtime.config import (
    REALTIME_API_HEADERS,
    REALTIME_API_URL,
    build_session_update,
)
```

with:

```python
from src.realtime.config import (
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    REALTIME_API_HEADERS,
    build_realtime_url,
    build_session_update,
)
```

Remove the now-unused `import datetime` line (near the top of the file).

- [ ] **Step 5: Use the dynamic URL in `run()`**

In `run()`, replace:

```python
        async with websockets.connect(
            REALTIME_API_URL,
            additional_headers = {
```

with:

```python
        async with websockets.connect(
            build_realtime_url(self._model),
            additional_headers = {
```

Remove the timer task line inside the `TaskGroup` block:

```python
                    task_group.create_task(self.timer())
```

(Delete that single line; keep `send`, `receive`, and `status_checker`.)

- [ ] **Step 6: Pass voice into `configure()`**

In `configure()`, replace:

```python
        instructions = '\n\n'.join([self._instructions, *TOOL_INSTRUCTIONS])
        await websocket.send(json.dumps(build_session_update(instructions)))
```

with:

```python
        instructions = '\n\n'.join([self._instructions, *TOOL_INSTRUCTIONS])
        await websocket.send(
            json.dumps(build_session_update(instructions, self._voice))
        )
```

- [ ] **Step 7: Delete the `timer` method**

Remove the entire method (currently lines ~151-157):

```python
    async def timer(self):
        """Monitor session timeout
        """
        await asyncio.sleep(
            datetime.timedelta(seconds = self._session_timeout).total_seconds()
        )
        raise TerminateTaskGroup('timer')
```

- [ ] **Step 8: Replace `set_session_timeout` with `set_model`/`set_voice`**

Remove:

```python
    def set_session_timeout(self, timeout: int | float):
        """Set session timeout duration
        """
        self._session_timeout = timeout
```

Add (place them next to `set_instructions`):

```python
    def set_model(self, model: str):
        """Set the realtime model used for the next connection."""
        self._model = model

    def set_voice(self, voice: str):
        """Set the assistant output voice used for the next connection."""
        self._voice = voice
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_client.py tests/test_config.py -v`
Expected: PASS (all).

- [ ] **Step 10: Commit**

```bash
git add src/realtime/client.py backend/tests/test_client.py
git commit -m "refactor: drop session timeout, add model/voice to realtime client

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Backend API — messages, routes, WS handler

**Files:**
- Modify: `backend/api/models.py`
- Modify: `backend/api/routes.py`
- Modify: `backend/api/websocket.py`
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `MODELS`, `VOICES`, `MODEL_KEYS`, `VOICE_KEYS`, `DEFAULT_MODEL`, `DEFAULT_VOICE` from Task 1; `set_model`/`set_voice`/`set_instructions` from Task 2.
- Produces:
  - `ConfigMessage` fields: `type`, `prompt_key: str | None`, `model: str | None`, `voice: str | None` (no `timeout`).
  - `GET /api/models` → `{"models": [{"key", "label"}, ...]}`.
  - `GET /api/voices` → `{"voices": [{"key", "label"}, ...]}`.

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `backend/tests/test_api.py` with:

```python
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check():
    """Test GET /api/health endpoint"""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_prompts():
    """Test GET /api/prompts endpoint"""
    response = client.get("/api/prompts")
    assert response.status_code == 200
    data = response.json()
    assert "prompts" in data
    assert len(data["prompts"]) > 0
    assert "key" in data["prompts"][0]
    assert "label" in data["prompts"][0]


def test_get_models():
    """Test GET /api/models endpoint"""
    response = client.get("/api/models")
    assert response.status_code == 200
    data = response.json()
    assert "models" in data
    assert len(data["models"]) > 0
    keys = {m["key"] for m in data["models"]}
    assert "gpt-realtime-2" in keys
    for m in data["models"]:
        assert "key" in m and "label" in m


def test_get_voices():
    """Test GET /api/voices endpoint"""
    response = client.get("/api/voices")
    assert response.status_code == 200
    data = response.json()
    assert "voices" in data
    assert len(data["voices"]) == 10
    keys = {v["key"] for v in data["voices"]}
    assert "alloy" in keys
    for v in data["voices"]:
        assert "key" in v and "label" in v


def test_timeout_endpoint_removed():
    """The old timeout endpoint no longer exists."""
    response = client.post("/api/session/timeout", json={"timeout": 120})
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_api.py -v`
Expected: FAIL — `test_get_models`/`test_get_voices` return 404; `test_timeout_endpoint_removed` fails because the endpoint still returns 200.

- [ ] **Step 3: Update `ConfigMessage` in `backend/api/models.py`**

Replace the `ConfigMessage` class:

```python
class ConfigMessage(BaseModel):
    """Client -> Server: update the session timeout and/or active prompt."""

    type: Literal["config"]
    timeout: int | None = None
    prompt_key: str | None = None
```

with:

```python
class ConfigMessage(BaseModel):
    """Client -> Server: update the active prompt, model, and/or voice."""

    type: Literal["config"]
    prompt_key: str | None = None
    model: str | None = None
    voice: str | None = None
```

- [ ] **Step 4: Update `backend/api/routes.py`**

Remove the `TimeoutRequest` class (lines ~12-15) and the entire `update_session_timeout` endpoint (lines ~94-121).

Add this import near the top (after the existing imports):

```python
from src.realtime.config import MODELS, VOICES
```

Add these two endpoints after `get_prompts`:

```python
@router.get("/api/models")
async def get_models() -> dict:
    """List the realtime models available for selection.

    Returns
    -------
    dict
        ``{"models": [{"key": ..., "label": ...}, ...]}``.
    """
    return {"models": MODELS}


@router.get("/api/voices")
async def get_voices() -> dict:
    """List the assistant voices available for selection.

    Returns
    -------
    dict
        ``{"voices": [{"key": ..., "label": ...}, ...]}``.
    """
    return {"voices": VOICES}
```

- [ ] **Step 5: Update `backend/api/websocket.py` imports and init**

Add to the existing `from src.realtime...` imports at the top of the file:

```python
from src.realtime.config import (
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    MODEL_KEYS,
    VOICE_KEYS,
)
```

In `AudioStreamSession.__init__`, replace:

```python
        self.session_timeout = 120
        prompts = load_prompts()
        self.prompt_key = next(iter(prompts), "default")
```

with:

```python
        prompts = load_prompts()
        self.prompt_key = next(iter(prompts), "default")
        self.model = DEFAULT_MODEL
        self.voice = DEFAULT_VOICE
```

- [ ] **Step 6: Update `_handle_config`**

Replace the whole body of `_handle_config` (the `try` block contents) with:

```python
        try:
            if message.prompt_key is not None:
                prompts = load_prompts()
                if message.prompt_key in prompts:
                    self.prompt_key = message.prompt_key
                    self.api_wrapper.set_instructions(
                        prompts[self.prompt_key]["instructions"]
                    )
                    await self._send_status("Prompt updated")
                else:
                    await self._send_status(
                        f"Prompt '{message.prompt_key}' not found"
                    )

            if message.model is not None:
                if message.model in MODEL_KEYS:
                    self.model = message.model
                    self.api_wrapper.set_model(self.model)
                    await self._send_status("Model updated")
                else:
                    await self._send_status(
                        f"Model '{message.model}' not found"
                    )

            if message.voice is not None:
                if message.voice in VOICE_KEYS:
                    self.voice = message.voice
                    self.api_wrapper.set_voice(self.voice)
                    await self._send_status("Voice updated")
                else:
                    await self._send_status(
                        f"Voice '{message.voice}' not found"
                    )
        except Exception as e:
            logger.error(f"Error handling config: {e}")
            await self._send_status("Failed to apply configuration")
```

Also update the `_handle_config` docstring first line to:

```python
        """Apply a client-requested prompt, model, and/or voice change.
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/ -v`
Expected: PASS — health, prompts, models, voices, timeout-removed, plus Task 1/2 tests.

- [ ] **Step 8: Commit**

```bash
git add backend/api/models.py backend/api/routes.py backend/api/websocket.py backend/tests/test_api.py
git commit -m "feat: serve model/voice lists, validate config, drop timeout endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Frontend — generic Selector, wiring, and removals

**Files:**
- Create: `frontend/components/Selector.tsx`
- Delete: `frontend/components/PromptSelector.tsx`, `frontend/components/TimeoutSlider.tsx`
- Modify: `frontend/lib/api.ts`, `frontend/hooks/useAudioStream.ts`, `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `GET /api/prompts`, `/api/models`, `/api/voices` from Task 3.
- Produces:
  - `Selector` default export with props `{ endpoint: string; responseKey: string; label: string; onSelect: (key: string) => void; disabled: boolean }`.
  - `sendConfigMessage(ws, config: { prompt_key?: string; model?: string; voice?: string })`.
  - `useAudioStream(isActive, promptKey, model, voice, onConversationEnded?)`.

There is no frontend test framework; this task is verified with `npm run build` and `npm run lint`.

- [ ] **Step 1: Create `frontend/components/Selector.tsx`**

```tsx
'use client';

import { useEffect, useState } from 'react';

interface Option {
  key: string;
  label: string;
}

interface SelectorProps {
  endpoint: string;
  responseKey: string;
  label: string;
  onSelect: (key: string) => void;
  disabled: boolean;
}

export default function Selector({
  endpoint,
  responseKey,
  label,
  onSelect,
  disabled,
}: SelectorProps) {
  const [options, setOptions] = useState<Option[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    fetch(`${apiUrl}${endpoint}`)
      .then((res) => {
        if (!res.ok) throw new Error(`Request failed: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        const items: Option[] = data[responseKey] ?? [];
        setOptions(items);
        if (items.length > 0) {
          setSelected(items[0].key);
          onSelect(items[0].key);
        }
      })
      .catch((err) => {
        console.error(`Failed to fetch ${endpoint}:`, err);
        setError(`Could not load ${label}. Please try refreshing the page.`);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [endpoint, responseKey]);

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const key = e.target.value;
    setSelected(key);
    onSelect(key);
  };

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        {label}
      </label>
      {error ? (
        <p className="text-sm text-red-600">{error}</p>
      ) : (
        <select
          value={selected}
          onChange={handleChange}
          disabled={disabled}
          className="disabled:opacity-50"
        >
          {options.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
```

Note: `onSelect` is intentionally omitted from the effect deps (parent passes a
new function each render); the `eslint-disable` line keeps `next lint` clean.

- [ ] **Step 2: Delete the old components**

```bash
git rm frontend/components/PromptSelector.tsx frontend/components/TimeoutSlider.tsx
```

- [ ] **Step 3: Update `frontend/lib/api.ts`**

Replace the `sendConfigMessage` function:

```typescript
export function sendConfigMessage(
  ws: WebSocket,
  config: { timeout?: number; prompt_key?: string },
) {
  ws.send(
    JSON.stringify({
      type: 'config',
      ...config,
    }),
  );
}
```

with:

```typescript
export function sendConfigMessage(
  ws: WebSocket,
  config: { prompt_key?: string; model?: string; voice?: string },
) {
  ws.send(
    JSON.stringify({
      type: 'config',
      ...config,
    }),
  );
}
```

- [ ] **Step 4: Update `frontend/hooks/useAudioStream.ts` signature**

Replace:

```typescript
export function useAudioStream(
  isActive: boolean,
  promptKey: string,
  timeout: number,
  onConversationEnded?: () => void,
) {
```

with:

```typescript
export function useAudioStream(
  isActive: boolean,
  promptKey: string,
  model: string,
  voice: string,
  onConversationEnded?: () => void,
) {
```

- [ ] **Step 5: Update the config send inside the hook**

Replace:

```typescript
      sendConfigMessage(newWs, {
        prompt_key: promptKey,
        timeout,
      });
```

with:

```typescript
      sendConfigMessage(newWs, {
        prompt_key: promptKey,
        model,
        voice,
      });
```

- [ ] **Step 6: Update the effect dependency array in the hook**

Replace the closing deps array of the main effect:

```typescript
  }, [isActive, promptKey, timeout]);
```

with:

```typescript
  }, [isActive, promptKey, model, voice]);
```

- [ ] **Step 7: Update `frontend/app/page.tsx`**

Replace the entire file with:

```tsx
'use client';

import { useState } from 'react';
import Selector from '@/components/Selector';
import ConversationButton from '@/components/ConversationButton';
import TranscriptDisplay from '@/components/TranscriptDisplay';
import { useAudioStream } from '@/hooks/useAudioStream';

export default function Home() {
  const [isRecording, setIsRecording] = useState(false);
  const [selectedPrompt, setSelectedPrompt] = useState('');
  const [selectedModel, setSelectedModel] = useState('');
  const [selectedVoice, setSelectedVoice] = useState('');

  const handleStartConversation = () => {
    setIsRecording(true);
  };

  const handleStopConversation = () => {
    setIsRecording(false);
  };

  const { messages, status } = useAudioStream(
    isRecording,
    selectedPrompt,
    selectedModel,
    selectedVoice,
    handleStopConversation,
  );

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900 text-center">
        Voice Chat
      </h1>

      {status && (
        <div className="p-3 bg-blue-100 text-blue-800 rounded text-sm">
          {status}
        </div>
      )}

      <Selector
        endpoint="/api/prompts"
        responseKey="prompts"
        label="Assistant Prompt"
        onSelect={setSelectedPrompt}
        disabled={isRecording}
      />

      <Selector
        endpoint="/api/models"
        responseKey="models"
        label="Model"
        onSelect={setSelectedModel}
        disabled={isRecording}
      />

      <Selector
        endpoint="/api/voices"
        responseKey="voices"
        label="Voice"
        onSelect={setSelectedVoice}
        disabled={isRecording}
      />

      <ConversationButton
        isRecording={isRecording}
        onStart={handleStartConversation}
        onStop={handleStopConversation}
      />

      <TranscriptDisplay messages={messages} />
    </div>
  );
}
```

- [ ] **Step 8: Verify the build and lint pass**

Run: `cd frontend && npm run lint && npm run build`
Expected: lint passes with no errors; build completes successfully. If lint complains about an unused import or variable, it points to a missed reference to the deleted `timeout`/`TimeoutSlider`/`PromptSelector` — fix it.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/Selector.tsx frontend/lib/api.ts frontend/hooks/useAudioStream.ts frontend/app/page.tsx
git add -A frontend/components
git commit -m "feat: generic Selector with model/voice pickers, drop timeout slider

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Documentation

**Files:**
- Modify: `backend/DEVELOPMENT.md`
- Modify: `README.md`

No automated test; verify by reading. Fold into one commit.

- [ ] **Step 1: Update `backend/DEVELOPMENT.md`**

Make these edits:

- Under **OpenAIRealtimeAPIWrapper → Methods**, replace:
  - `- `run()` — Async event loop managing send/receive/timer/status tasks` → `- `run()` — Async event loop managing send/receive/status tasks`
  - `- `set_session_timeout()` — Updates timeout` → `- `set_model()` — Sets the realtime model for the next connection`
  - Add a line: `- `set_voice()` — Sets the assistant output voice`
- Under **AudioStreamSession → Methods**, replace:
  - `- `_handle_config()` — Applies configuration changes (timeout, prompt)` → `- `_handle_config()` — Applies configuration changes (prompt, model, voice)`
- Under **REST Endpoints**:
  - Remove the entire **POST /api/session/timeout** block (request + response lines).
  - After the **GET /api/prompts** block, add:

    ````markdown
    **GET /api/models**
    ```json
    {
      "models": [
        {"key": "gpt-realtime-2", "label": "GPT Realtime 2"},
        {"key": "gpt-realtime", "label": "GPT Realtime"}
      ]
    }
    ```

    **GET /api/voices**
    ```json
    {
      "voices": [
        {"key": "alloy", "label": "Alloy"},
        {"key": "ash", "label": "Ash"}
      ]
    }
    ```
    ````
- Under **WebSocket Endpoint → Client → Server**, replace:
  - `{"type": "config", "timeout": 120, "prompt_key": "default"}` → `{"type": "config", "prompt_key": "default", "model": "gpt-realtime-2", "voice": "alloy"}`
- Under **Testing**, replace `All 8 tests should pass (health, prompts, timeout validation).` with `All tests should pass (health, prompts, models, voices, config factories, client).`

- [ ] **Step 2: Update `README.md`**

Search `README.md` for any mention of the timeout slider / maximum conversation time and remove it; where the UI controls or features are described, note that the user can select the assistant prompt, the realtime model, and the voice. (Keep edits minimal and consistent with the surrounding prose.)

Run: `grep -ni "timeout\|slider\|voice\|model" README.md` to locate the spots to touch.

- [ ] **Step 3: Commit**

```bash
git add backend/DEVELOPMENT.md README.md
git commit -m "docs: document model/voice selection, remove timeout references

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the full backend suite: `cd backend && pytest tests/ -v` — all pass.
- [ ] Run frontend checks: `cd frontend && npm run lint && npm run build` — both pass.
- [ ] Manual smoke (optional, needs `OPENAI_API_KEY`): start backend + frontend, pick a non-default model and voice, start a conversation, confirm the reply uses the chosen voice and the connection uses the chosen model (backend logs the URL only implicitly — verify via audio timbre change and no connection error).
- [ ] Confirm no stray references remain: `grep -rniE "timeout|TimeoutSlider|PromptSelector|session_timeout|REALTIME_API_URL|REALTIME_API_CONFIG" backend/ src/ frontend/app frontend/components frontend/hooks frontend/lib` returns only the retained task-timeout constants in `websocket.py` (`MONITOR_TASK_TIMEOUT_S`, `API_TASK_TIMEOUT_S`, `STREAM_TASK_TIMEOUT_S`, and the `TimeoutError` handlers around `asyncio.wait_for`).
