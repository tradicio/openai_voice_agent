# OpenAI Realtime Voice Chat on Streamlit

![UI Image](./resources/ui.png)

## Installation

```sh
uv sync
```

## Configuration

Create `.streamlit/secrets.toml` with:

```toml
OPENAI_API_KEY = "sk-..."
```

## Run

```sh
uv run streamlit run main.py
```

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
the call). Any of these raising `TerminateTaskGroup` cleanlyS tears down the
whole group and closes the WebSocket connection.
