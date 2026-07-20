# Backend Development Guide

## Project Structure

- `main.py` — FastAPI application and server
- `api/routes.py` — REST API endpoints
- `api/websocket.py` — WebSocket handler with session management
- `api/models.py` — Pydantic message models
- `src/realtime/realtime_client.py` — OpenAI Realtime API wrapper (unchanged from original)
- `src/audio/audio_utils.py` — Audio processing utilities
- `src/prompts/prompts.py` and `prompts.yaml` — Prompt definitions
- `src/utils.py` — Non-Streamlit utilities (logging, event loop, hashing)
- `tests/test_api.py` — REST endpoint tests

## Key Components

### OpenAIRealtimeAPIWrapper
Core class managing OpenAI Realtime API connection. Unchanged from original project.

Methods:
- `audio_frame_callback()` — Processes incoming audio frames
- `run()` — Async event loop managing send/receive/timer/status tasks
- `stop()` — Stops the session
- `set_session_timeout()` — Updates timeout
- `set_instructions()` — Changes system prompt

### AudioStreamSession
Manages a WebSocket connection's lifecycle.

Methods:
- `handle()` — Main message loop
- `_start_conversation()` — Initiates API connection with FIFO buffers
- `_stop_conversation()` — Closes API connection
- `_handle_config()` — Applies configuration changes (timeout, prompt)
- `_handle_audio_frame()` — Decodes and writes audio to FIFO

## API Endpoints

### REST Endpoints

**GET /api/prompts**
```json
{
  "prompts": [
    {"key": "default", "label": "General Assistant"},
    {"key": "italian_tutor", "label": "Italian Tutor"},
    {"key": "customer_support", "label": "Customer Support"}
  ]
}
```

**POST /api/session/timeout**
Request: `{"timeout": 120}`
Response: `{"status": "ok", "timeout": 120}`

**GET /api/health**
Response: `{"status": "ok"}`

### WebSocket Endpoint

**WS /ws/audio**

Client → Server:
```json
{"type": "control", "action": "start"}
{"type": "config", "timeout": 120, "prompt_key": "default"}
{"type": "audio", "data": "<base64 pcm>"}
{"type": "control", "action": "stop"}
```

Server → Client:
```json
{"type": "status", "message": "..."}
{"type": "transcript", "role": "user|assistant", "delta": "..."}
```

## Environment Variables

- `OPENAI_API_KEY` (required) — OpenAI API key
- `FRONTEND_URL` (optional, default: http://localhost:3000) — Frontend origin for CORS
- `LOG_LEVEL` (optional, default: INFO) — Logging level

## Running Locally

```bash
export OPENAI_API_KEY=sk-...
python main.py
```

## Testing

```bash
pytest tests/test_api.py -v
```

All 8 tests should pass (health, prompts, timeout validation).

## Debugging

Enable debug logging:
```bash
export LOG_LEVEL=DEBUG
python main.py
```

View Swagger docs: `http://localhost:8000/docs`
