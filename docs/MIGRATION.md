# Streamlit to Next.js Migration Guide

## Overview

This project has been migrated from a monolithic Streamlit application to a two-service architecture:
- **Backend**: Python FastAPI server managing OpenAI Realtime API connection
- **Frontend**: Next.js React app with minimal UI for control and transcript display

## Architecture

### Before (Streamlit)
- Single `main.py` entry point
- Streamlit session state for UI interactivity
- Direct WebRTC capture via `streamlit-webrtc`
- All logic in Python

### After (Next.js + FastAPI)
- **Backend** (`backend/`): FastAPI server with WebSocket endpoint for audio streaming
- **Frontend** (`frontend/`): Next.js app with Web Audio API for capture
- **Communication**: REST for control, WebSocket for audio I/O

## Directory Structure

```
.
├── backend/                    # Python FastAPI backend
│   ├── main.py                # App entry point
│   ├── api/
│   │   ├── routes.py          # REST endpoints
│   │   ├── websocket.py       # WebSocket handler
│   │   └── models.py          # Pydantic models
│   ├── src/
│   │   ├── realtime/          # OpenAI Realtime API wrapper
│   │   ├── audio/             # Audio utilities
│   │   ├── prompts/           # Prompt loading and YAML
│   │   └── utils.py           # Non-Streamlit utilities
│   ├── tests/                 # API tests
│   ├── pyproject.toml         # Dependencies
│   └── .env.example           # Config template
│
└── frontend/                   # Next.js React frontend
    ├── app/
    │   ├── page.tsx           # Main page
    │   ├── layout.tsx         # Root layout
    │   └── globals.css        # Global styles
    ├── components/            # React components
    │   ├── PromptSelector.tsx
    │   ├── TimeoutSlider.tsx
    │   ├── ConversationButton.tsx
    │   └── TranscriptDisplay.tsx
    ├── lib/                   # Utilities
    │   ├── api.ts             # API client
    │   └── audioCapture.ts    # Web Audio API wrapper
    ├── hooks/                 # React hooks
    │   └── useAudioStream.ts  # Main integration hook
    ├── package.json
    └── .env.local.example     # Config template
```

## Local Development

### Prerequisites
- Python 3.12+
- Node.js 18+
- OpenAI API key

### Backend Setup

```bash
cd backend
export OPENAI_API_KEY=sk-...
pip install -e .
python main.py
```

Server runs on `http://localhost:8000`
Swagger API docs: `http://localhost:8000/docs`

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

App runs on `http://localhost:3000`

## Removed Files

These Streamlit-specific files are no longer used:
- `main.py` (old entry point - replaced by `backend/main.py`)
- `src/ui.py` (Streamlit UI layer)
- `src/utils/st_utils.py` (Streamlit utilities)
- `.streamlit/` directory
- `streamlit-webrtc` dependency

## Key Logic Changes

### Audio Pipeline

**Before (Streamlit):**
```
Browser Mic → streamlit-webrtc → audio_frame_callback → OpenAI API
OpenAI API → audio_frame_callback → WebRTC → Browser Speaker
```

**After (Next.js):**
```
Browser Mic → Web Audio API → WebSocket → Backend FIFO → OpenAI API
OpenAI API → Backend FIFO → WebSocket → Web Audio API → Browser Speaker
```

### State Management

**Before (Streamlit):**
- `st.session_state` for recording flag, prompts, etc.
- Streamlit re-runs entire script on state changes

**After (Next.js):**
- React `useState` for UI state
- `useAudioStream` hook manages WebSocket and audio lifecycle
- No full-page re-renders

### Prompts & Config

- Loading logic unchanged (`src/prompts/prompts.py`)
- Prompts now fetched via REST API (`GET /api/prompts`)
- Prompt changes sent via WebSocket config message

## Testing

### Backend Tests
```bash
cd backend
pytest tests/test_api.py -v
```

### Frontend Testing
1. Start backend: `cd backend && python main.py`
2. Start frontend: `cd frontend && npm run dev`
3. Navigate to `http://localhost:3000`
4. Test conversation flow: prompt selection → timeout adjustment → start/stop

See `TESTING.md` for detailed frontend testing instructions.

## Deployment

### Backend
Deploy to any Python-hosting platform (Heroku, AWS Lambda, GCP Cloud Run):
```bash
cd backend
pip install -e .
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
```

### Frontend
Deploy to any Node.js hosting (Vercel, Netlify):
```bash
cd frontend
npm install
npm run build
npm start
```

Set environment variables:
- Backend: `OPENAI_API_KEY`, `FRONTEND_URL` (for CORS)
- Frontend: `NEXT_PUBLIC_API_URL` (backend URL)

## Migration Checklist

- [x] FastAPI backend scaffold created
- [x] Core Python logic migrated to backend
- [x] WebSocket handler integrated with OpenAI API
- [x] Audio I/O pipeline implemented
- [x] Next.js frontend scaffolded
- [x] React components created
- [x] WebSocket client and audio capture integrated
- [x] API tests written
- [x] Documentation complete
