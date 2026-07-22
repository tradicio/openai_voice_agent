import json
import base64
import asyncio
import datetime

import websockets

from src.audio.pipeline import AudioPipeline
from src.prompts import DEFAULT_INSTRUCTIONS
from src.realtime.config import (
    REALTIME_API_URL,
    REALTIME_API_HEADERS,
    REALTIME_API_CONFIG,
)
from src.log import get_logger
from src.realtime.events import EventDispatcher, TurnState
from src.realtime.tools import TOOL_INSTRUCTIONS
from src.realtime.transcript import TranscriptStore


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
        # Source of truth for the transcript rows shown to the client.
        self._transcript = TranscriptStore()
        self._barge_in_event = asyncio.Event()
        self._audio = AudioPipeline()
        self._turn = TurnState()
        self._dispatcher = EventDispatcher(
            self, self._transcript, self._audio, self._turn,
            self._barge_in_event,
        )

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
                pcm_audio = self._audio.next_api_pcm()
                if pcm_audio is None:
                    await asyncio.sleep(self._send_interval)
                    continue
                base64_audio = base64.b64encode(pcm_audio).decode('utf-8')

                await websocket.send(json.dumps(dict(
                    type = 'input_audio_buffer.append',
                    audio = base64_audio
                )))
                logger.debug('Sent audio to OpenAI (%d bytes)', len(pcm_audio))
            except Exception as e:
                logger.error('Error in send loop', exc_info = e)
                break
        raise TerminateTaskGroup('send')

    async def receive(self, websocket: 'websockets.asyncio.client.ClientConnection'):
        """Receive responses from OpenAI Realtime API and dispatch them."""
        while True:
            try:
                response = await websocket.recv()
                if response:
                    await self._dispatcher.dispatch(json.loads(response), websocket)
                else:
                    logger.debug('No response')
            except Exception as e:
                logger.error('Error in receive loop', exc_info=e)
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

    @property
    def recording(self) -> bool:
        """Get recording status of audio data
        """
        return self._recording

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
        self._transcript.reset()
        # Clear per-turn tracking so a restart can't truncate against a
        # previous session's item/playback position.
        self._turn.reset()
        self._audio.reset()
        self._audio.reset_played()

    def stop(self):
        """Stop operation
        """
        self._recording = False

    def consume_barge_in(self) -> bool:
        """Check whether the user just interrupted the assistant, clearing the flag

        Used by the WebSocket layer to know when to tell the client to stop
        audio it already has scheduled, which otherwise keeps playing out.
        """
        if self._barge_in_event.is_set():
            self._barge_in_event.clear()
            return True
        return False

    def transcript_snapshot(self) -> list[tuple[str, dict]]:
        """Return (item_id, row) pairs in creation order for the client."""
        return self._transcript.snapshot()

    def write_client_pcm(self, pcm_bytes: bytes) -> None:
        """Enqueue client audio (base64-decoded PCM) for uplink to the API."""
        self._audio.write_client_pcm(pcm_bytes)

    def read_client_pcm(self, nsamples: int, partial: bool = True) -> bytes | None:
        """Drain playback audio as PCM bytes for the client; None if empty."""
        return self._audio.read_client_pcm(nsamples, partial=partial)
