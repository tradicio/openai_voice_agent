# Restructure Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `main.py` and `utils.py` into single-responsibility flat modules (`config.py`, `audio_utils.py`, `prompts.py`, `st_utils.py`, `realtime_client.py`, `ui.py`, thin `main.py`) with zero behavior change.

**Architecture:** Pure code-motion refactor. Each task extracts one cohesive piece of `main.py`/`utils.py` into its own module and updates imports. No logic changes. Final task deletes `utils.py` once empty and does a manual end-to-end smoke test in the running Streamlit app.

**Tech Stack:** Python 3, Streamlit, streamlit-webrtc, websockets, PyAV, uv.

## Global Constraints

- No behavior changes — this is a pure reorganization (per spec `docs/superpowers/specs/2026-07-16-restructure-modules-design.md`).
- Flat top-level modules only — no package directory.
- No automated test suite exists in this project; verification is `python -c "import <module>"` per task plus one final manual Streamlit run.
- Delete `utils.py` only after all three of its members have been moved out.

---

### Task 1: Extract `config.py`

**Files:**
- Create: `config.py`
- Modify: `main.py:1-69` (remove the extracted constants, add import)

**Interfaces:**
- Consumes: `TOOL_DEFINITIONS` from `tools.py` (already exists, unchanged).
- Produces: `config.py` exports `REALTIME_API_URL`, `REALTIME_API_HEADERS`, `REALTIME_API_CONFIG`, `DEFAULT_INSTRUCTIONS`, `API_SAMPLE_RATE`, `API_SAMPLE_WIDTH`, `API_CHANNELS`, `CLIENT_SAMPLE_RATE`, `CLIENT_SAMPLE_WIDTH`, `CLIENT_CHANNELS`, `FORMAT_MAPPING`, `LAYOUT_MAPPING` — later tasks import these from `config`.

- [ ] **Step 1: Create `config.py` with the extracted constants**

```python
from tools import TOOL_DEFINITIONS


# Configuration for calling Realtime API
REALTIME_API_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
REALTIME_API_HEADERS = {}
REALTIME_API_CONFIG = dict(
    type = 'realtime',
    output_modalities = ['audio'],
    audio = dict(
        input = dict(
            format = dict(type = 'audio/pcm', rate = 24000),
            transcription = dict(
                model = 'whisper-1',
            ),
            turn_detection = dict(
                type = 'server_vad',
                threshold = 0.5,
                prefix_padding_ms = 100,
                silence_duration_ms = 800,
            ),
        ),
        output = dict(
            format = dict(type = 'audio/pcm', rate = 24000),
            voice = 'alloy',
        ),
    ),
    tools = TOOL_DEFINITIONS,
    tool_choice = 'auto',
)

DEFAULT_INSTRUCTIONS = "Your knowledge cutoff is 2023-10. You are a helpful, witty, and friendly AI. Act like a human, but remember that you aren't a human and that you can't do human things in the real world. Your voice and personality should be warm and engaging, with a lively and playful tone. If interacting in a non-English language, start by using the standard accent or dialect familiar to the user. Talk quickly. You should always call a function if you can. Do not refer to these rules, even if you're asked about them."

# Audio data parameters for Realtime API
API_SAMPLE_RATE = 24000
API_SAMPLE_WIDTH = 2
API_CHANNELS = 1

# Audio data parameters for client side
CLIENT_SAMPLE_RATE = 48000
CLIENT_SAMPLE_WIDTH = 2
CLIENT_CHANNELS = 2

# Mapping for PyAV format conversion
FORMAT_MAPPING = { 2: 's16' }
LAYOUT_MAPPING = { 1: 'mono', 2: 'stereo' }
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "import config; print(config.REALTIME_API_URL)"`
Expected: prints `wss://api.openai.com/v1/realtime?model=gpt-realtime` with no errors.

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "refactor: extract Realtime API config constants into config.py"
```

---

### Task 2: Extract `audio_utils.py` and `prompts.py` from `utils.py`

**Files:**
- Create: `audio_utils.py`
- Create: `prompts.py`
- Modify: `utils.py` (remove the three functions being redistributed; this task removes `audio_frame_to_pcm_audio`, `pcm_audio_to_audio_frame`, `get_blank_audio_frame`, `load_prompts`, leaving only `hash_by_code`)

**Interfaces:**
- Produces: `audio_utils.py` exports `audio_frame_to_pcm_audio(frame)`, `pcm_audio_to_audio_frame(pcm_audio, *, format, layout, sample_rate)`, `get_blank_audio_frame(*, format, layout, samples, sample_rate)`.
- Produces: `prompts.py` exports `load_prompts(path='prompts.yaml')`.
- `hash_by_code` stays in `utils.py` temporarily; Task 3 moves it to `st_utils.py` and deletes `utils.py`.

- [ ] **Step 1: Create `audio_utils.py`**

```python
import av
import numpy as np


def audio_frame_to_pcm_audio(frame: av.AudioFrame) -> bytes:
    return frame.to_ndarray().tobytes()


def pcm_audio_to_audio_frame(
    pcm_audio: bytes,
    *,
    format: str,
    layout: str,
    sample_rate: int
) -> av.AudioFrame:
    raw_data = np.frombuffer(pcm_audio, np.int16).reshape(1, -1)
    frame = av.AudioFrame.from_ndarray(raw_data, format = format, layout = layout)
    frame.sample_rate = sample_rate
    return frame


def get_blank_audio_frame(
    *,
    format: str,
    layout: str,
    samples: int,
    sample_rate: int
) -> av.AudioFrame:
    frame = av.AudioFrame(format = format, layout = layout, samples = samples)
    for p in frame.planes:
        p.update(bytes(p.buffer_size))
    frame.sample_rate = sample_rate
    return frame
```

- [ ] **Step 2: Create `prompts.py`**

```python
import yaml


def load_prompts(path: str = 'prompts.yaml') -> dict[str, dict[str, str]]:
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

- [ ] **Step 3: Remove the moved functions from `utils.py`, leaving only `hash_by_code`**

`utils.py` should now contain only:

```python
def hash_by_code(obj) -> int:
    """Hash function to detect code changes
    """
    import inspect
    return hash(inspect.getsource(obj))
```

- [ ] **Step 4: Verify both new modules import cleanly**

Run: `python -c "import audio_utils, prompts; print(prompts.load_prompts()['default']['label'])"`
Expected: prints `Assistente predefinito` with no errors.

- [ ] **Step 5: Commit**

```bash
git add audio_utils.py prompts.py utils.py
git commit -m "refactor: split audio helpers and prompt loading out of utils.py"
```

---

### Task 3: Move `hash_by_code` into `st_utils.py` and delete `utils.py`

**Files:**
- Modify: `st_utils.py` (add `hash_by_code`)
- Delete: `utils.py`

**Interfaces:**
- Produces: `st_utils.py` now exports `get_logger`, `get_event_loop` (existing) plus `hash_by_code(obj)` — later tasks import `hash_by_code` from `st_utils`, not `utils`.

- [ ] **Step 1: Add `hash_by_code` to `st_utils.py`**

```python
import asyncio
import inspect
import logging

import streamlit as st


@st.cache_resource
def get_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger


@st.cache_resource
def get_event_loop(*, _logger = None) -> asyncio.AbstractEventLoop:
    """Get a new event loop
    """
    if _logger is not None:
        _logger.info('Creating new event loop')
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop


def hash_by_code(obj) -> int:
    """Hash function to detect code changes
    """
    return hash(inspect.getsource(obj))
```

- [ ] **Step 2: Delete `utils.py`**

```bash
git rm utils.py
```

- [ ] **Step 3: Verify `st_utils.py` imports cleanly**

Run: `python -c "import st_utils; print(st_utils.hash_by_code(st_utils.get_logger))"`
Expected: prints an integer hash with no errors.

- [ ] **Step 4: Commit**

```bash
git add st_utils.py
git commit -m "refactor: move hash_by_code into st_utils.py, delete utils.py"
```

---

### Task 4: Extract `realtime_client.py`

**Files:**
- Create: `realtime_client.py`
- Modify: `main.py` (remove `TerminateTaskGroup` and `OpenAIRealtimeAPIWrapper`, replace with import)

**Interfaces:**
- Consumes: `config.py` constants (`REALTIME_API_URL`, `REALTIME_API_HEADERS`, `REALTIME_API_CONFIG`, `DEFAULT_INSTRUCTIONS`, `API_SAMPLE_RATE`, `API_SAMPLE_WIDTH`, `API_CHANNELS`, `CLIENT_SAMPLE_RATE`, `CLIENT_SAMPLE_WIDTH`, `CLIENT_CHANNELS`, `FORMAT_MAPPING`, `LAYOUT_MAPPING`); `audio_utils.audio_frame_to_pcm_audio`, `audio_utils.pcm_audio_to_audio_frame`, `audio_utils.get_blank_audio_frame`; `st_utils.get_logger`; `tools.TOOL_HANDLERS`, `tools.TOOL_INSTRUCTIONS`.
- Produces: `realtime_client.py` exports `TerminateTaskGroup` and `OpenAIRealtimeAPIWrapper` (same public API as before: `__init__(api_key, session_timeout=60, send_interval=0.2, instructions=DEFAULT_INSTRUCTIONS)`, `audio_frame_callback`, `run()`, `write_messages()`, `recording` property, `valid_messages` property, `set_session_timeout()`, `set_instructions()`, `request_end_conversation()`, `start()`, `stop()`, `reset_stream()`) — `ui.py` (Task 5) imports and uses this class.

- [ ] **Step 1: Create `realtime_client.py` with `TerminateTaskGroup` and `OpenAIRealtimeAPIWrapper`**

```python
import json
import base64
import asyncio
import datetime

import av
import streamlit as st
import websockets

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


logger = get_logger(__name__)


class TerminateTaskGroup(Exception):
    """Exception raised to terminate a task group."""
    def __init__(self, reason: str):
        super().__init__()
        self.reason = reason

    def __repr__(self):
        return f"{self.__class__.__name__}(reason={repr(self.reason)})"


class OpenAIRealtimeAPIWrapper:
    _api_key: str
    _session_timeout: int | float
    _send_interval: float
    _instructions: str
    _ending: bool
    _recording: bool
    _messages: list[dict]
    _resampler_for_api: av.audio.resampler.AudioResampler
    _resampler_for_client: av.audio.resampler.AudioResampler
    _record_stream: av.audio.fifo.AudioFifo
    _play_stream: av.audio.fifo.AudioFifo

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

        self._recording = False
        self._messages = []
        self._resampler_for_api = av.audio.resampler.AudioResampler(
            format = FORMAT_MAPPING[API_SAMPLE_WIDTH],
            layout = LAYOUT_MAPPING[API_CHANNELS],
            rate = API_SAMPLE_RATE
        )
        self._resampler_for_client = av.audio.resampler.AudioResampler(
            format = FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
            layout = LAYOUT_MAPPING[CLIENT_CHANNELS],
            rate = CLIENT_SAMPLE_RATE
        )

    def audio_frame_callback(self, frame: av.AudioFrame) -> av.AudioFrame:
        """Audio data processing callback function for streamlit-webrtc

        Args:
            frame (av.AudioFrame): Audio data frame
        Returns:
            av.AudioFrame: Processed audio data frame
        """
        stream_pts = self._record_stream.samples_written * self._record_stream.pts_per_sample
        if frame.pts > stream_pts:
            logger.debug('Missing samples: %s < %s; Filling them up...', stream_pts, frame.pts)
            blank_frame = get_blank_audio_frame(
                format = frame.format.name,
                layout = frame.layout.name,
                samples = int((frame.pts - stream_pts) / self._record_stream.pts_per_sample),
                sample_rate = frame.sample_rate
            )
            self._record_stream.write(blank_frame)
        self._record_stream.write(frame)

        new_frame = self._play_stream.read(frame.samples, partial = True)
        if new_frame:
            assert new_frame.format.name == frame.format.name
            assert new_frame.layout.name == frame.layout.name
            assert new_frame.sample_rate == frame.sample_rate
        else:
            # Return silence if empty
            new_frame = get_blank_audio_frame(
                format = frame.format.name,
                layout = frame.layout.name,
                samples = frame.samples,
                sample_rate = frame.sample_rate
            )
        new_frame.pts = frame.pts
        new_frame.time_base = frame.time_base
        return new_frame

    async def run(self):
        """Start connection with OpenAI Realtime API and handle audio data transmission
        """
        if self.recording:
            logger.warning('Already recording')
            return

        self.start()

        async with websockets.connect(
            REALTIME_API_URL,
            additional_headers = {
                'Authorization': f"Bearer {self._api_key}",
                **REALTIME_API_HEADERS
            }
        ) as websocket:
            logger.info('Connected to OpenAI Realtime API')
            await self.configure(websocket)
            logger.info('Configured')

            try:
                async with asyncio.TaskGroup() as task_group:
                    task_group.create_task(self.send(websocket))
                    task_group.create_task(self.receive(websocket))
                    task_group.create_task(self.timer())
                    task_group.create_task(self.status_checker())
            except* TerminateTaskGroup as eg:
                logger.info('Connection closing: %s', eg.exceptions[0].reason)
            except* Exception as eg:
                logger.error('Error in task group', exc_info = eg)
        logger.info('Connection closed')

    async def configure(self, websocket: 'websockets.asyncio.client.ClientConnection'):
        """Send session configuration to OpenAI Realtime API

        Args:
            websocket (websockets.asyncio.client.ClientConnection): WebSocket client
        """
        instructions = '\n\n'.join([self._instructions, *TOOL_INSTRUCTIONS])
        await websocket.send(json.dumps(dict(
            type = 'session.update',
            session = dict(REALTIME_API_CONFIG, instructions = instructions),
        )))

    async def send(self, websocket: 'websockets.asyncio.client.ClientConnection'):
        """Send audio data to OpenAI Realtime API

        Args:
            websocket (websockets.asyncio.client.ClientConnection): WebSocket client
        """
        while True:
            try:
                frame = self._record_stream.read()
                if not frame:
                    await asyncio.sleep(self._send_interval)
                    continue
                frame, *_rest = self._resampler_for_api.resample(frame)
                assert not _rest

                pcm_audio = audio_frame_to_pcm_audio(frame)
                base64_audio = base64.b64encode(pcm_audio).decode('utf-8')

                await websocket.send(json.dumps(dict(
                    type = 'input_audio_buffer.append',
                    audio = base64_audio
                )))
                logger.debug('Sent audio to OpenAI (%d bytes)', len(pcm_audio))
            except Exception as e:
                logger.error('Error in send loop', exc_info = e)
                st.exception(e)
                break
        raise TerminateTaskGroup('send')

    async def receive(self, websocket: 'websockets.asyncio.client.ClientConnection'):
        """Receive responses from OpenAI Realtime API

        Args:
            websocket (websockets.asyncio.client.ClientConnection): WebSocket client
        """
        transcript_placeholder = None
        message = None
        user_transcript_placeholder = None
        user_message = None
        while True:
            try:
                response = await websocket.recv()
                if response:
                    response_data = json.loads(response)

                    if response_data['type'] == 'response.output_audio.delta':
                        # Queue audio data from server
                        base64_audio = response_data['delta']
                        if base64_audio:
                            pcm_audio = base64.b64decode(base64_audio)
                            frame = pcm_audio_to_audio_frame(
                                pcm_audio,
                                format = FORMAT_MAPPING[API_SAMPLE_WIDTH],
                                layout = LAYOUT_MAPPING[API_CHANNELS],
                                sample_rate = API_SAMPLE_RATE
                            )
                            resampled_frame, *_rest = \
                                    self._resampler_for_client.resample(frame)
                            assert not _rest
                            self._play_stream.write(resampled_frame)
                            logger.debug(
                                'Event: %s - received audio from OpenAI (%d bytes)',
                                response_data['type'],
                                len(pcm_audio)
                            )

                    elif response_data['type'] == 'response.output_audio_transcript.delta':
                        # logger.debug('Event: %s', response_data['type'])  # Skipped as it occurs too frequently
                        if not message:
                            transcript_placeholder = st.empty()
                            message = dict(role = 'assistant', content = '')
                            self._messages.append(message)
                        message['content'] += response_data['delta']
                        if not transcript_placeholder:
                            transcript_placeholder = st.empty()
                        with transcript_placeholder.container():
                            with st.chat_message('assistant'):
                                st.write(message['content'])

                    elif response_data['type'] == 'response.output_audio_transcript.done':
                        logger.info(
                            'Event: %s - %s',
                            response_data['type'],
                            response_data['transcript']
                        )
                        message = None
                        transcript_placeholder = None

                    elif response_data['type'] == 'conversation.item.input_audio_transcription.completed':
                        logger.debug(
                            'Event: %s - %s',
                            response_data['type'],
                            response_data['transcript']
                        )
                        if not user_message:
                            user_message = dict(role = 'user', content = '')
                            self._messages.append(user_message)
                        if user_message['content'] is None:
                            user_message['content'] = response_data['transcript']
                        else:
                            user_message['content'] += response_data['transcript']
                        if not user_transcript_placeholder:
                            user_transcript_placeholder = st.empty()
                        with user_transcript_placeholder.container():
                            with st.chat_message('user'):
                                st.write(user_message['content'])

                    elif response_data['type'] == 'input_audio_buffer.speech_started':
                        # Reset existing AI voice audio when user speech is detected
                        self.reset_stream(play_stream_only = True)
                        logger.debug(
                            'Event: %s - cleared the play stream',
                            response_data['type']
                        )
                        # Prepare container when user starts speaking to avoid overlap with AI transcript
                        user_transcript_placeholder = st.empty()
                        user_message = dict(role = 'user', content = None)
                        self._messages.append(user_message)

                    elif response_data['type'] == 'response.function_call_arguments.done':
                        logger.info('Event: %s - %s', response_data['type'], response_data)
                        tool_handler = TOOL_HANDLERS.get(response_data.get('name'))
                        if tool_handler:
                            arguments = json.loads(response_data.get('arguments') or '{}')
                            tool_handler(self, arguments)

                    elif response_data['type'] == 'response.done':
                        logger.debug('%s: %s', response_data['type'], response_data)
                        if self._ending:
                            remaining_seconds = self._play_stream.samples / CLIENT_SAMPLE_RATE
                            logger.info(
                                'Waiting %.2fs for the goodbye message to finish playing',
                                remaining_seconds
                            )
                            await asyncio.sleep(remaining_seconds + 0.5)
                            logger.info('Ending conversation as requested by the assistant')
                            self.stop()

                    elif response_data['type'] == 'error':
                        logger.error('Event: %s - %s', response_data['type'], response_data)
                        st.error(response_data['error']['message'])

                    elif any(
                        response_data['type'].startswith(pattern)
                         for pattern in (
                            'session.created',
                            'session.updated',
                            'conversation.item.created',
                            'response.output_audio.',
                            'rate_limits.updated',
                        )
                    ):
                        # Log content
                        logger.debug('%s: %s', response_data['type'], response_data)
                    else:
                        # Only log event name
                        logger.debug('Event: %s', response_data['type'])
                else:
                    logger.debug('No response')
            except Exception as e:
                logger.error('Error in receive loop', exc_info = e)
                st.exception(e)
                break
        raise TerminateTaskGroup('receive')

    async def timer(self):
        """Monitor session timeout
        """
        await asyncio.sleep(
            datetime.timedelta(seconds = self._session_timeout).total_seconds()
        )
        raise TerminateTaskGroup('timer')

    async def status_checker(self):
        """Monitor recording status and terminate task group when recording ends
        """
        while self.recording:
            await asyncio.sleep(1)
        logger.info('Recording stopped')
        raise TerminateTaskGroup('status_checker')

    def write_messages(self):
        """Display chat messages
        """
        for message in self.valid_messages:
            with st.chat_message(message['role']):
                st.write(message['content'])

    @property
    def recording(self) -> bool:
        """Get recording status of audio data
        """
        return self._recording

    @property
    def valid_messages(self) -> list[dict]:
        """Get valid chat messages
        """
        return [m for m in self._messages if m['content'] is not None]

    def set_session_timeout(self, timeout: int | float):
        """Set session timeout duration
        """
        self._session_timeout = timeout

    def set_instructions(self, instructions: str):
        """Set assistant system instructions (prompt)
        """
        self._instructions = instructions

    def request_end_conversation(self):
        """Mark the conversation to stop once the current response finishes playing

        Called by the 'end_conversation' tool handler (see tools.py).
        """
        logger.info(
            'Assistant requested to end the conversation; '
            'will stop once the current response finishes playing'
        )
        self._ending = True

    def start(self):
        """Start operation

        (Automatically called by run method)
        """
        if self.recording:
            raise RuntimeError('Already recording')
        self._recording = True
        self._ending = False
        self._messages = []
        self.reset_stream()

    def stop(self):
        """Stop operation
        """
        self._recording = False

    def reset_stream(self, play_stream_only: bool = False):
        """Reset audio data stream
        """
        if not play_stream_only:
            self._record_stream = av.audio.fifo.AudioFifo()
        self._play_stream = av.audio.fifo.AudioFifo()
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `python -c "from realtime_client import OpenAIRealtimeAPIWrapper, TerminateTaskGroup; print('ok')"`
Expected: prints `ok` with no errors.

- [ ] **Step 3: Commit**

```bash
git add realtime_client.py
git commit -m "refactor: extract OpenAIRealtimeAPIWrapper into realtime_client.py"
```

---

### Task 5: Extract `ui.py` and trim `main.py`

**Files:**
- Create: `ui.py`
- Modify: `main.py` (replace entire contents with a thin entry point)

**Interfaces:**
- Consumes: `realtime_client.OpenAIRealtimeAPIWrapper`; `prompts.load_prompts`; `st_utils.get_logger`, `st_utils.get_event_loop`, `st_utils.hash_by_code`.
- Produces: `ui.py` exports `main()` — the Streamlit page renderer. `main.py`'s `if __name__ == '__main__':` block calls `ui.main()`.

- [ ] **Step 1: Create `ui.py`**

```python
import streamlit as st
from streamlit_webrtc import WebRtcMode, webrtc_streamer

from prompts import load_prompts
from realtime_client import OpenAIRealtimeAPIWrapper
from st_utils import get_logger, get_event_loop, hash_by_code


logger = get_logger(__name__)


def main():
    loop = get_event_loop(_logger = logger)

    # Regenerate when code changes to utilize Streamlit's hot reload
    api_wrapper_key = f"api_wrapper-{hash_by_code(OpenAIRealtimeAPIWrapper)}"

    if api_wrapper_key not in st.session_state:
        openai_api_key = st.secrets['OPENAI_API_KEY']
        st.session_state[api_wrapper_key] = \
                OpenAIRealtimeAPIWrapper(api_key = openai_api_key)
    api_wrapper = st.session_state[api_wrapper_key]

    session_timeout = st.slider(
        'Maximum conversation time (seconds)',
        min_value = 60,
        max_value = 300,
        value = 120
    )
    api_wrapper.set_session_timeout(session_timeout)

    prompts = load_prompts()
    prompt_key = st.selectbox(
        'Assistant prompt',
        options = list(prompts.keys()),
        format_func = lambda key: prompts[key]['label'],
        disabled = st.session_state.get('recording', False),
    )
    api_wrapper.set_instructions(prompts[prompt_key]['instructions'])

    # webrtc_streamer has its own start button,
    # but we control it externally because we don't know how to notify api_wrapper
    if 'recording' not in st.session_state:
        st.session_state.recording = False
    if st.session_state.recording:
        if st.button('End conversation', type = 'primary'):
            st.session_state.recording = False
    else:
        if st.button('Start conversation'):
            st.session_state.recording = True

    webrtc_ctx = webrtc_streamer(
        key = f"recoder",
        mode = WebRtcMode.SENDRECV,
        rtc_configuration = dict(
            iceServers = [
                dict(urls = ['stun:stun.l.google.com:19302'])
            ]
        ),
        audio_frame_callback = api_wrapper.audio_frame_callback,
        media_stream_constraints = dict(video = False, audio = True),
        desired_playing_state = st.session_state.recording,
    )

    if webrtc_ctx.state.playing:
        if not api_wrapper.recording:
            st.write('Connecting to OpenAI.')
            logger.info('Starting running')
            loop.run_until_complete(api_wrapper.run())
            logger.info('Finished running')
            st.write('Disconnected from OpenAI.')
            st.session_state.recording = False
            st.rerun()
    else:
        if api_wrapper.recording:
            logger.info('Stopping running')
            api_wrapper.stop()
            st.session_state.recording = False
            st.rerun()
        api_wrapper.write_messages()
```

- [ ] **Step 2: Replace `main.py` with a thin entry point**

```python
import logging

from ui import main


if __name__ == '__main__':
    logging.basicConfig(
        format = "%(levelname)s %(name)s@%(filename)s:%(lineno)d: %(message)s",
    )

    st_webrtc_logger = logging.getLogger('streamlit_webrtc')
    st_webrtc_logger.setLevel(logging.DEBUG)

    aioice_logger = logging.getLogger('aioice')
    aioice_logger.setLevel(logging.WARNING)

    fsevents_logger = logging.getLogger('fsevents')
    fsevents_logger.setLevel(logging.WARNING)

    main()
```

- [ ] **Step 3: Verify both modules import cleanly**

Run: `python -c "import ui, main; print('ok')"`
Expected: prints `ok` with no errors.

- [ ] **Step 4: Commit**

```bash
git add main.py ui.py
git commit -m "refactor: extract Streamlit UI into ui.py, trim main.py to entry point"
```

---

### Task 6: Full-app manual smoke test

**Files:** none (verification only)

**Interfaces:** none

- [ ] **Step 1: Run the app**

Run: `uv run streamlit run main.py`
Expected: app starts with no import/tracebacks in the terminal.

- [ ] **Step 2: Manually verify in the browser**

- Load the page: slider and prompt selectbox render.
- Click "Start conversation": webrtc connects, "Connecting to OpenAI." appears.
- Speak into the mic: user transcript appears as a chat bubble; assistant responds with audio and a transcript bubble.
- Say goodbye / ask to end the conversation: assistant says goodbye, then the call ends automatically (tool-calling via `tools.py` still works).
- Click "End conversation" manually on a separate run: conversation stops and prior messages remain visible.
- Switch the "Assistant prompt" dropdown to `italian_tutor` or `customer_support` before starting: confirm the assistant follows that persona's instructions.

- [ ] **Step 3: Confirm no regressions, stop the app**

If any step fails, use `superpowers:systematic-debugging` to investigate before proceeding further — do not patch symptoms.

(No commit — this task is verification only.)
