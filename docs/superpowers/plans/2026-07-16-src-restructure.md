# src/ Restructuring + Architecture Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every application module except `main.py` into a `src/` package organized into `realtime/`, `audio/`, `prompts/`, and `utils/` subfolders, and document the audio/text mechanism in `README.md`.

**Architecture:** Pure reorganization — no behavior changes. Files move via `git mv` (preserves history), each subfolder gets an `__init__.py`, and every intra-project import is rewritten to the new `src.<subfolder>.<module>` path. `prompts.py`'s YAML path becomes file-relative instead of cwd-relative. No `pyproject.toml` changes are needed since there is no `[build-system]`/package config today.

**Tech Stack:** Python 3.12, Streamlit, streamlit-webrtc, no test framework in this repo.

## Global Constraints

- No behavior changes — this is a file-move + import-path + docs-only change.
- No `pyproject.toml` changes (no existing `[build-system]` section to update).
- Every subfolder under `src/` needs an `__init__.py` (empty) to be importable as `src.<subfolder>.<module>`.
- Use `git mv` for every file move so git history is preserved.
- There is no test suite in this repo. Verification per task is a `python -c "import ..."` sanity check (catches import errors immediately); the final task is a manual smoke test of the running app.

---

### Task 1: Package scaffold + move `audio_utils.py`

**Files:**
- Create: `src/__init__.py` (empty)
- Create: `src/audio/__init__.py` (empty)
- Move: `audio_utils.py` -> `src/audio/audio_utils.py` (no internal edits needed — it has no intra-project imports)

**Interfaces:**
- Produces: `src.audio.audio_utils.audio_frame_to_pcm_audio(frame)`, `src.audio.audio_utils.pcm_audio_to_audio_frame(pcm_audio, *, format, layout, sample_rate)`, `src.audio.audio_utils.get_blank_audio_frame(*, format, layout, samples, sample_rate)` — used by Task 4.

- [ ] **Step 1: Create the package directories and empty `__init__.py` files**

```bash
mkdir -p src/audio
touch src/__init__.py src/audio/__init__.py
```

- [ ] **Step 2: Move `audio_utils.py` into `src/audio/`**

```bash
git mv audio_utils.py src/audio/audio_utils.py
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `python -c "from src.audio.audio_utils import audio_frame_to_pcm_audio, pcm_audio_to_audio_frame, get_blank_audio_frame; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: move audio_utils.py into src/audio/"
```

---

### Task 2: Move `st_utils.py` into `src/utils/`

**Files:**
- Create: `src/utils/__init__.py` (empty)
- Move: `st_utils.py` -> `src/utils/st_utils.py` (no internal edits needed — it has no intra-project imports)

**Interfaces:**
- Produces: `src.utils.st_utils.get_logger(name, level=logging.DEBUG)`, `src.utils.st_utils.get_event_loop(*, _logger=None)`, `src.utils.st_utils.hash_by_code(obj)` — used by Tasks 4 and 5.

- [ ] **Step 1: Create the package directory and empty `__init__.py`**

```bash
mkdir -p src/utils
touch src/utils/__init__.py
```

- [ ] **Step 2: Move `st_utils.py` into `src/utils/`**

```bash
git mv st_utils.py src/utils/st_utils.py
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `python -c "from src.utils.st_utils import get_logger, get_event_loop, hash_by_code; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: move st_utils.py into src/utils/"
```

---

### Task 3: Move `prompts.py` + `prompts.yaml` into `src/prompts/`, fix the YAML path

**Files:**
- Create: `src/prompts/__init__.py` (empty)
- Move: `prompts.py` -> `src/prompts/prompts.py`
- Move: `prompts.yaml` -> `src/prompts/prompts.yaml`
- Modify: `src/prompts/prompts.py` — make the default YAML path file-relative

**Interfaces:**
- Produces: `src.prompts.prompts.load_prompts(path=None)` returning `dict[str, dict[str, str]]` — used by Task 5.

- [ ] **Step 1: Create the package directory and empty `__init__.py`**

```bash
mkdir -p src/prompts
touch src/prompts/__init__.py
```

- [ ] **Step 2: Move `prompts.py` and `prompts.yaml`**

```bash
git mv prompts.py src/prompts/prompts.py
git mv prompts.yaml src/prompts/prompts.yaml
```

- [ ] **Step 3: Make the default YAML path file-relative**

Edit `src/prompts/prompts.py` to resolve the default path next to the module
file, so it no longer depends on the process's current working directory:

```python
import os

import yaml


_DEFAULT_PROMPTS_PATH = os.path.join(os.path.dirname(__file__), 'prompts.yaml')


def load_prompts(path: str = _DEFAULT_PROMPTS_PATH) -> dict[str, dict[str, str]]:
    """Load named assistant prompts from a YAML file

    Args:
        path (str): Path to the YAML file containing prompts
    Returns:
        dict[str, dict[str, str]]: Mapping of prompt key to
            a dict with 'label' and 'instructions'
    """
    with open(path, encoding = 'utf-8') as f:
        return yaml.safe_load(f)
```

- [ ] **Step 4: Verify the module imports and loads the YAML correctly**

Run: `python -c "from src.prompts.prompts import load_prompts; p = load_prompts(); assert p; print(list(p.keys()))"`
Expected: prints a non-empty list of prompt keys (no traceback).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: move prompts.py and prompts.yaml into src/prompts/, use file-relative path"
```

---

### Task 4: Move `tools.py`, `config.py`, `realtime_client.py` into `src/realtime/`

**Files:**
- Create: `src/realtime/__init__.py` (empty)
- Move: `tools.py` -> `src/realtime/tools.py` (no internal edits needed — it has no intra-project imports)
- Move: `config.py` -> `src/realtime/config.py`
- Move: `realtime_client.py` -> `src/realtime/realtime_client.py`
- Modify: `src/realtime/config.py` and `src/realtime/realtime_client.py` — update intra-project imports

**Interfaces:**
- Consumes: `src.audio.audio_utils.{audio_frame_to_pcm_audio, pcm_audio_to_audio_frame, get_blank_audio_frame}` (Task 1), `src.utils.st_utils.get_logger` (Task 2).
- Produces: `src.realtime.tools.{TOOL_DEFINITIONS, TOOL_HANDLERS, TOOL_INSTRUCTIONS}`, `src.realtime.config.{REALTIME_API_URL, REALTIME_API_HEADERS, REALTIME_API_CONFIG, DEFAULT_INSTRUCTIONS, API_SAMPLE_RATE, API_SAMPLE_WIDTH, API_CHANNELS, CLIENT_SAMPLE_RATE, CLIENT_SAMPLE_WIDTH, CLIENT_CHANNELS, FORMAT_MAPPING, LAYOUT_MAPPING}`, `src.realtime.realtime_client.OpenAIRealtimeAPIWrapper` — used by Task 5.

- [ ] **Step 1: Create the package directory and empty `__init__.py`**

```bash
mkdir -p src/realtime
touch src/realtime/__init__.py
```

- [ ] **Step 2: Move the three files**

```bash
git mv tools.py src/realtime/tools.py
git mv config.py src/realtime/config.py
git mv realtime_client.py src/realtime/realtime_client.py
```

- [ ] **Step 3: Fix the import in `src/realtime/config.py`**

Change:
```python
from tools import TOOL_DEFINITIONS
```
to:
```python
from src.realtime.tools import TOOL_DEFINITIONS
```

- [ ] **Step 4: Fix the imports in `src/realtime/realtime_client.py`**

Change:
```python
from audio_utils import (
    audio_frame_to_pcm_audio,
    pcm_audio_to_audio_frame,
    get_blank_audio_frame,
)
from config import (
    REALTIME_API_URL,
    REALTIME_API_HEADERS,
    REALTIME_API_CONFIG,
    DEFAULT_INSTRUCTIONS,
    API_SAMPLE_RATE,
    API_SAMPLE_WIDTH,
    API_CHANNELS,
    CLIENT_SAMPLE_RATE,
    CLIENT_SAMPLE_WIDTH,
    CLIENT_CHANNELS,
    FORMAT_MAPPING,
    LAYOUT_MAPPING,
)
from st_utils import get_logger
from tools import TOOL_HANDLERS, TOOL_INSTRUCTIONS
```
to:
```python
from src.audio.audio_utils import (
    audio_frame_to_pcm_audio,
    pcm_audio_to_audio_frame,
    get_blank_audio_frame,
)
from src.realtime.config import (
    REALTIME_API_URL,
    REALTIME_API_HEADERS,
    REALTIME_API_CONFIG,
    DEFAULT_INSTRUCTIONS,
    API_SAMPLE_RATE,
    API_SAMPLE_WIDTH,
    API_CHANNELS,
    CLIENT_SAMPLE_RATE,
    CLIENT_SAMPLE_WIDTH,
    CLIENT_CHANNELS,
    FORMAT_MAPPING,
    LAYOUT_MAPPING,
)
from src.utils.st_utils import get_logger
from src.realtime.tools import TOOL_HANDLERS, TOOL_INSTRUCTIONS
```

- [ ] **Step 5: Verify the modules import cleanly**

Run: `python -c "from src.realtime.realtime_client import OpenAIRealtimeAPIWrapper; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: move tools.py, config.py, realtime_client.py into src/realtime/"
```

---

### Task 5: Move `ui.py` into `src/`, update `main.py`

**Files:**
- Move: `ui.py` -> `src/ui.py`
- Modify: `src/ui.py` — update intra-project imports
- Modify: `main.py` — update the entry-point import

**Interfaces:**
- Consumes: `src.prompts.prompts.load_prompts` (Task 3), `src.realtime.realtime_client.OpenAIRealtimeAPIWrapper` (Task 4), `src.utils.st_utils.{get_logger, get_event_loop, hash_by_code}` (Task 2).
- Produces: `src.ui.main()` — used by `main.py`.

- [ ] **Step 1: Move `ui.py`**

```bash
git mv ui.py src/ui.py
```

- [ ] **Step 2: Fix the imports in `src/ui.py`**

Change:
```python
from prompts import load_prompts
from realtime_client import OpenAIRealtimeAPIWrapper
from st_utils import get_logger, get_event_loop, hash_by_code
```
to:
```python
from src.prompts.prompts import load_prompts
from src.realtime.realtime_client import OpenAIRealtimeAPIWrapper
from src.utils.st_utils import get_logger, get_event_loop, hash_by_code
```

- [ ] **Step 3: Fix the import in `main.py`**

Change:
```python
from ui import main
```
to:
```python
from src.ui import main
```

- [ ] **Step 4: Verify the full entry point imports cleanly**

Run: `python -c "import main; print('ok')"`
Expected: `ok` (this transitively imports every moved module, so it exercises the whole chain).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: move ui.py into src/, update main.py entry point import"
```

---

### Task 6: Manual smoke test of the running app

**Files:** none (verification only)

- [ ] **Step 1: Confirm only `main.py` remains in the root**

Run: `ls *.py`
Expected: only `main.py` is listed.

- [ ] **Step 2: Start the app**

Run: `uv run streamlit run main.py`
Expected: Streamlit starts without any import/traceback errors printed to the terminal.

- [ ] **Step 3: Exercise the golden path in the browser**

Open the local Streamlit URL printed in the terminal, then:
1. Confirm the "Assistant prompt" selectbox is populated (proves `src/prompts/prompts.yaml` loaded).
2. Click "Start conversation", allow microphone access, speak briefly, confirm you both hear the AI voice response and see the live transcript appear via `st.chat_message`.
3. Click "End conversation" and confirm the connection stops cleanly with no traceback in the terminal.

- [ ] **Step 4: Stop the app**

Press `Ctrl+C` in the terminal running Streamlit.

(No commit — this task only verifies prior commits; nothing changes.)

---

### Task 7: Document the audio/text mechanism in `README.md`

**Files:**
- Modify: `README.md` — add a new "How it works" section after the "Run" section and before "Article on Qiita (Japanese)"

**Interfaces:** none (documentation only).

- [ ] **Step 1: Insert the new section into `README.md`**

Insert the following between the `## Run` section's code block and the
`## Article on Qiita (Japanese)` heading:

```markdown
## How it works

### Audio pipeline

`streamlit-webrtc` captures microphone audio in the browser and delivers
frames to `OpenAIRealtimeAPIWrapper.audio_frame_callback`
(`src/realtime/realtime_client.py`), which writes them into a record FIFO
(`av.audio.fifo.AudioFifo`). A background `send()` task reads from that
FIFO, resamples the audio to the format the OpenAI Realtime API expects
(24kHz mono PCM), base64-encodes it, and streams it over a WebSocket as
`input_audio_buffer.append` events.

Audio deltas coming back from the API (`response.output_audio.delta`) are
handled in `receive()`, resampled to the client's format (48kHz stereo), and
written into a play FIFO. The same `audio_frame_callback` reads from that
FIFO on every WebRTC frame tick, so the response plays back to the user in
near real time.

### Text/transcript flow

Alongside the audio, the API emits transcript deltas:
`response.output_audio_transcript.delta` for the assistant's speech and
`conversation.item.input_audio_transcription.completed` for the user's
speech. These are accumulated into chat messages and rendered live via
`st.chat_message` inside `st.empty()` placeholders, giving a live captioned
transcript alongside the audio.

### Tool calling

`response.function_call_arguments.done` events are dispatched to handlers
registered in `src/realtime/tools.py`. Today there is a single tool,
`end_conversation`, which lets the assistant end the call right after
saying goodbye.

### Concurrency model

A single asyncio event loop runs four tasks concurrently inside one
`asyncio.TaskGroup`: `send` (mic -> API), `receive` (API -> speaker/UI),
`timer` (enforces the session timeout), and `status_checker` (watches the
Streamlit "recording" flag so the UI's "End conversation" button can stop
the call). Any of these raising `TerminateTaskGroup` cleanly tears down the
whole group and closes the WebSocket connection.
```

- [ ] **Step 2: Verify the README renders sensibly**

Run: `cat README.md`
Expected: the new "How it works" section appears once, in the right place, with no broken markdown headings.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the audio/text mechanism in README"
```
