import json
import base64
import asyncio
import datetime

import av
import streamlit as st
import websockets

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
            except TerminateTaskGroup as eg:
                logger.info('Connection closing: %s', eg.reason)
            except BaseException as eg:
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
