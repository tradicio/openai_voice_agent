# Restructure into src/ and document the audio/text mechanism

## Goal

Only `main.py` should remain in the project root. All other application
modules move under `src/`, organized into subfolders by responsibility.
Additionally, `README.md` gains a section documenting how the audio and text
(transcript) mechanism works, so the demo's internals are clear to a reader.

This is a pure reorganization: no behavior changes, no new features.

## Target structure

```
main.py                      # entry point only

src/
  __init__.py
  ui.py                      # top-level Streamlit view (was ui.py)

  realtime/
    __init__.py
    realtime_client.py       # OpenAIRealtimeAPIWrapper (was realtime_client.py)
    config.py                # Realtime API config constants (was config.py)
    tools.py                 # tool/function-calling definitions (was tools.py)

  audio/
    __init__.py
    audio_utils.py           # PCM <-> av.AudioFrame helpers (was audio_utils.py)

  prompts/
    __init__.py
    prompts.py                # load_prompts() (was prompts.py)
    prompts.yaml               # prompt data (was prompts.yaml)

  utils/
    __init__.py
    st_utils.py               # generic Streamlit/logging/event-loop helpers (was st_utils.py)
```

`pyproject.toml` needs no changes: there is no `[build-system]`/package
config today (the app runs via `uv run streamlit run main.py`), so a plain
package directory with `__init__.py` files works without packaging changes.

## Import changes

- `main.py`: `from ui import main` -> `from src.ui import main`
- `src/ui.py`:
  - `from prompts import load_prompts` -> `from src.prompts.prompts import load_prompts`
  - `from realtime_client import OpenAIRealtimeAPIWrapper` -> `from src.realtime.realtime_client import OpenAIRealtimeAPIWrapper`
  - `from st_utils import ...` -> `from src.utils.st_utils import ...`
- `src/realtime/realtime_client.py`:
  - `from audio_utils import ...` -> `from src.audio.audio_utils import ...`
  - `from config import ...` -> `from src.realtime.config import ...`
  - `from st_utils import get_logger` -> `from src.utils.st_utils import get_logger`
  - `from tools import TOOL_HANDLERS, TOOL_INSTRUCTIONS` -> `from src.realtime.tools import TOOL_HANDLERS, TOOL_INSTRUCTIONS`
- `src/realtime/config.py`:
  - `from tools import TOOL_DEFINITIONS` -> `from src.realtime.tools import TOOL_DEFINITIONS`
- `src/prompts/prompts.py`:
  - `load_prompts`'s default `path` argument changes from the literal
    `'prompts.yaml'` to a path resolved relative to the module file
    (`os.path.join(os.path.dirname(__file__), 'prompts.yaml')`), so it loads
    correctly regardless of the process's current working directory rather
    than depending on the app being launched from the repo root.

No other module needs changes (`src/audio/audio_utils.py`,
`src/utils/st_utils.py`, `src/realtime/tools.py` have no intra-project
imports to fix).

## README documentation

Add a new "How it works" section to `README.md`, after Configuration/Run,
covering:

- **Audio pipeline**: `streamlit-webrtc` captures microphone audio
  client-side and delivers frames to `OpenAIRealtimeAPIWrapper.audio_frame_callback`,
  which writes them into a record FIFO (`av.audio.fifo.AudioFifo`). A
  background `send()` task reads from that FIFO, resamples to the API's
  format (24kHz mono PCM), base64-encodes it, and streams it to the OpenAI
  Realtime API over a WebSocket. Audio deltas coming back from the API are
  handled in `receive()`, resampled to the client's format (48kHz stereo),
  and written into a play FIFO; the same `audio_frame_callback` reads from
  that FIFO on every WebRTC frame tick to play the response back to the user.
- **Text/transcript flow**: as audio streams, the API also emits transcript
  deltas (`response.output_audio_transcript.delta` for the assistant,
  `conversation.item.input_audio_transcription.completed` for the user).
  These are accumulated into chat messages and rendered live via
  `st.chat_message` inside `st.empty()` placeholders, giving a live captioned
  transcript alongside the audio.
- **Tool calling**: `response.function_call_arguments.done` events are
  dispatched to handlers registered in `src/realtime/tools.py` (currently
  just `end_conversation`, which lets the assistant end the call after
  saying goodbye).
- **Concurrency model**: a single asyncio event loop runs `send`, `receive`,
  `timer` (session timeout), and `status_checker` (UI-driven stop) as
  concurrent tasks inside one `asyncio.TaskGroup`; any task raising
  `TerminateTaskGroup` cleanly tears down the whole group and closes the
  connection.

## Testing / verification

No automated tests exist in this repo. Verification is:
1. `uv run streamlit run main.py` starts without import errors.
2. The app loads, prompt selector populates from `src/prompts/prompts.yaml`,
   and a conversation can be started/stopped (manual smoke test).
