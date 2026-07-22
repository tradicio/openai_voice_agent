# OpenAI Realtime Voice Chat
A browser-based, full-duplex voice chat with OpenAI's Realtime API. Speak
into your microphone and the assistant answers with streaming speech and a
live transcript, with natural barge-in (you can talk over it).

## Architecture

```
┌──────────────────────────┐        WebSocket (/ws/audio)        ┌──────────────────────────┐        WebSocket        ┌─────────────────┐
│  Frontend (Next.js)      │  ── control / config / audio ──▶    │  Backend (FastAPI)       │  ── PCM 24kHz mono ──▶  │  OpenAI         │
│  Web Audio API capture   │                                     │  audio resample + FIFOs  │                         │  Realtime API   │
│  + playback, transcript  │  ◀── status / transcript / audio ── │  session orchestration   │  ◀── audio + events ──  │  (gpt-realtime) │
└──────────────────────────┘                                     └──────────────────────────┘                         └─────────────────┘
        :3000                                                            :8000
```

- **Frontend** (`frontend/`, port 3000) — a Next.js 14 / React app. Captures
  mic audio with the Web Audio API, streams it to the backend over a
  WebSocket, plays returned audio, and renders the live transcript. No audio
  ever goes directly to OpenAI from the browser.
- **Backend** (`backend/`, port 8000) — a FastAPI server. It owns the OpenAI
  Realtime API connection, resamples audio between the client and API
  formats, and relays audio, transcript deltas, and status back to the
  frontend. The OpenAI key stays server-side.
- **Shared Python modules** (`src/`) — the Realtime API wrapper, audio
  utilities, prompts, and config. These live at the repo root and are
  imported by the backend (`backend/main.py` adds the root to `sys.path`).

### Repository layout

```
.
├── src/                       # Shared Python logic (imported by the backend)
│   ├── realtime/
│   │   ├── realtime_client.py # OpenAIRealtimeAPIWrapper: WS to OpenAI, task group
│   │   ├── config.py          # Model, audio formats, session config
│   │   └── tools.py           # Function-calling tools (e.g. end_conversation)
│   ├── audio/audio_utils.py   # PCM <-> PyAV AudioFrame conversion
│   └── prompts/               # prompts.py loader + prompts.yaml definitions
│
├── backend/                   # FastAPI service (port 8000)
│   ├── main.py                # App entry point, CORS, route wiring
│   ├── api/
│   │   ├── routes.py          # REST: /api/health, /api/prompts, /api/models, /api/voices
│   │   ├── websocket.py       # /ws/audio: AudioStreamSession orchestration
│   │   └── models.py          # Pydantic message models
│   ├── tests/                 # pytest suite
│   └── DEVELOPMENT.md         # Backend developer guide
│
├── frontend/                  # Next.js service (port 3000)
│   ├── app/                   # Next.js App Router (page.tsx, layout.tsx)
│   ├── components/            # PromptSelector, ModelSelector, VoiceSelector, ConversationButton, TranscriptDisplay
│   ├── hooks/useAudioStream.ts# WebSocket + audio lifecycle, transcript assembly
│   ├── lib/                   # api.ts, audioCapture.ts, audioPlayback.ts
│   └── DEVELOPMENT.md         # Frontend developer guide
│
├── pyproject.toml             # Python dependencies (backend + shared src)
```

## Prerequisites

- Python 3.12+
- Node.js 18+
- An OpenAI API key with Realtime API access

## Setup

The backend and frontend are installed and run independently.

### 1. Backend (FastAPI)

Install the Python dependencies from the repo root. With
[uv](https://docs.astral.sh/uv/):

```sh
uv sync
```

Or with a plain `venv` + `pip`:

```sh
python -m venv .venv
source .venv/bin/activate        # on Windows: .venv\Scripts\activate
pip install -e .
```

Create a `.env` file at the repo root (see [`.env.example`](./.env.example)):

```env
OPENAI_API_KEY=sk-...
FRONTEND_URL=http://localhost:3000   # exact frontend origin (used for CORS + WS origin check)
LOG_LEVEL=INFO
```

Run the backend from the `backend/` directory:

```sh
cd backend
uv run python main.py        # or: python main.py  (with the venv active)
```

It listens on `http://localhost:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

### 2. Frontend (Next.js)

```sh
cd frontend
npm install
npm run dev
```

The app is served at `http://localhost:3000`. To point it at a non-default
backend, set `NEXT_PUBLIC_API_URL` in `frontend/.env.local` (see
[`frontend/.env.local.example`](./frontend/.env.local.example)):

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Then open `http://localhost:3000`, pick a prompt, select the model and voice, click
**Start Conversation**, and grant microphone access.

## How it works

### Session lifecycle

Each browser tab opens one WebSocket to `/ws/audio`. The backend validates
the `Origin` header against `FRONTEND_URL` and creates an
`AudioStreamSession` (`backend/api/websocket.py`) that owns everything for
that connection. The frontend then sends a `config` message (chosen prompt +
model + voice) and a `control: start` message; the backend opens the OpenAI
Realtime connection and spins up three background tasks:

- an **API task** running `OpenAIRealtimeAPIWrapper.run()` (the send/receive
  loop against OpenAI),
- a **monitor task** that forwards transcript growth to the client, and
- a **stream task** that forwards assistant audio to the client.

### Audio pipeline

**Uplink (mic → OpenAI).** The browser captures mono audio via the Web Audio
API, converts it to interleaved 48 kHz stereo 16-bit PCM, base64-encodes it,
and sends it as `audio` messages. The backend decodes each frame into a PyAV
`AudioFrame` and writes it to a record FIFO. The Realtime wrapper resamples
that to the API format (**24 kHz mono PCM**) and streams it to OpenAI as
`input_audio_buffer.append` events.

**Downlink (OpenAI → speaker).** Audio deltas from the API are resampled to
the client format (**48 kHz stereo**) and written to a play FIFO. The stream
task reads chunks off that FIFO, base64-encodes them, and sends `audio`
messages to the frontend, which schedules them for playback.

### Transcript flow

The API emits transcript deltas — `response.output_audio_transcript.delta`
for the assistant and `conversation.item.input_audio_transcription.completed`
(Whisper) for the user. The wrapper accumulates these into per-item records,
each tagged with a stable `item_id` and a monotonic `seq`. The monitor task
tracks how many characters of each item it has already forwarded and sends
only the new suffix as a `transcript` message (`role`, `seq`, `delta`).

The frontend keys transcript state by `seq`, so it renders **one row per
turn** in creation order and never merges turns — important because the
user's Whisper transcript often arrives *after* the assistant has already
started replying.

### Barge-in

Server-side VAD has `interrupt_response` enabled, so speaking over the
assistant interrupts it. When the wrapper detects an interruption, the
backend sends a `clear_audio` message and the frontend flushes any assistant
audio it had already buffered — so playback stops promptly instead of
draining the queue.

### Tool calling

`response.function_call_arguments.done` events are dispatched to handlers
registered in `src/realtime/tools.py`. The one built-in tool,
`end_conversation`, lets the assistant hang up right after saying goodbye.
Adding a tool is a matter of writing a handler and registering its schema —
see the module docstring for the steps.

### Concurrency & teardown

Inside the API task, `OpenAIRealtimeAPIWrapper.run()` runs its send/receive/
timer/status coroutines together in a single `asyncio.TaskGroup`; any of them
raising a terminate signal tears down the whole group and closes the OpenAI
socket. On `control: stop` (or WebSocket disconnect) the session stops the
wrapper and awaits the monitor/API/stream tasks with timeouts before falling
back to cancellation. The backend also guards itself with a per-message size
cap and an audio-frame rate limit so a single client can't exhaust resources.

## WebSocket protocol (`/ws/audio`)

Client → Server:

```json
{"type": "control", "action": "start"}          // or "stop"
{"type": "config",  "prompt_key": "default", "model": "gpt-realtime-2", "voice": "alloy"}
{"type": "audio",   "data": "<base64 PCM>"}
```

Server → Client:

```json
{"type": "status",      "message": "Connected"}
{"type": "transcript",  "role": "user", "seq": 3, "delta": "..."}
{"type": "audio",       "data": "<base64 PCM>"}
{"type": "clear_audio"}                          // barge-in: flush buffered audio
```

## REST API

| Method | Path                     | Purpose                                   |
| ------ | ------------------------ | ----------------------------------------- |
| GET    | `/api/health`            | Liveness check → `{"status": "ok"}`       |
| GET    | `/api/prompts`           | List selectable prompts (key + label)     |
| GET    | `/api/models`            | List selectable models (key + label)      |
| GET    | `/api/voices`            | List selectable voices (key + label)      |

## Configuration

- **Prompts** are defined in `src/prompts/prompts.yaml` (key → `label` +
  `instructions`) and surfaced to the UI via `GET /api/prompts`.
- **Model and audio parameters** (model name, sample rates, VAD thresholds,
  default instructions) live in `src/realtime/config.py`.

## Testing

Run the backend test suite from the repo root:

```sh
uv run pytest        # configured via pyproject.toml (testpaths = backend/tests)
```

## Further reading

- [`backend/DEVELOPMENT.md`](./backend/DEVELOPMENT.md) — backend components,
  endpoints, and message formats.
- [`frontend/DEVELOPMENT.md`](./frontend/DEVELOPMENT.md) — component and hook
  reference.
