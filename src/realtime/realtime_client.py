import json
import base64
import asyncio
import datetime

import av
import websockets

from src.audio.audio_utils import (
    audio_frame_to_pcm_audio,
    pcm_audio_to_audio_frame,
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
from src.log import get_logger
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
    _items: dict[str, dict]
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
        # item_id -> {"role", "text", "seq", "status"}, insertion-ordered.
        # Source of truth for the transcript rows shown to the client.
        self._items: dict[str, dict] = {}
        self._next_seq = 0
        self._current_response_id = None
        self._cancelled_response_id = None
        self._barge_in_event = asyncio.Event()
        self._played_samples = 0
        self._current_item_id = None
        self._current_content_index = 0
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
                break
        raise TerminateTaskGroup('send')

    async def receive(self, websocket: 'websockets.asyncio.client.ClientConnection'):
        """Receive responses from OpenAI Realtime API

        Args:
            websocket (websockets.asyncio.client.ClientConnection): WebSocket client
        """
        while True:
            try:
                response = await websocket.recv()
                if response:
                    response_data = json.loads(response)

                    if response_data['type'] == 'response.output_audio.delta':
                        # Drop leftover audio still in flight for an
                        # already-cancelled response.
                        if self._cancelled_response_id is not None and \
                                response_data.get('response_id') == self._cancelled_response_id:
                            pass
                        elif (base64_audio := response_data['delta']):
                            item_id = response_data.get('item_id')
                            if item_id is not None and \
                                    item_id != self._current_item_id:
                                self._current_item_id = item_id
                                self._current_content_index = \
                                    response_data.get('content_index', 0)
                                self._played_samples = 0
                            # Mark the response active so a barge-in can cancel
                            # it before any transcript delta arrives (audio
                            # leads the transcript).
                            self._current_response_id = \
                                response_data.get('response_id')
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
                        # Drop leftover transcript for an already-cancelled
                        # response; it would otherwise appear after the user's
                        # interrupting turn, reversing the visible order.
                        if self._cancelled_response_id is None or \
                                response_data.get('response_id') != self._cancelled_response_id:
                            self._current_response_id = response_data.get('response_id')
                            item_id = response_data.get('item_id')
                            if item_id is not None:
                                item = self._get_or_create_item(item_id, 'assistant')
                                item['text'] += response_data['delta']

                    elif response_data['type'] == 'response.output_audio_transcript.done':
                        logger.info(
                            'Event: %s - %s',
                            response_data['type'],
                            response_data['transcript']
                        )
                        item_id = response_data.get('item_id')
                        if item_id is not None and item_id in self._items:
                            self._items[item_id]['status'] = 'done'

                    elif response_data['type'] == 'conversation.item.input_audio_transcription.delta':
                        logger.debug(
                            'Event: %s - item=%s delta=%r',
                            response_data['type'],
                            response_data.get('item_id'),
                            response_data.get('delta'),
                        )
                        item_id = response_data.get('item_id')
                        if item_id is not None:
                            item = self._get_or_create_item(item_id, 'user')
                            item['text'] += response_data.get('delta', '')

                    elif response_data['type'] == 'conversation.item.input_audio_transcription.completed':
                        logger.debug(
                            'Event: %s - item=%s transcript=%r',
                            response_data['type'],
                            response_data.get('item_id'),
                            response_data.get('transcript'),
                        )
                        item_id = response_data.get('item_id')
                        if item_id is not None:
                            item = self._get_or_create_item(item_id, 'user')
                            transcript = response_data.get('transcript')
                            # Append-only: only fill from 'completed' if no
                            # deltas arrived (whisper-1 sends only 'completed';
                            # other models stream deltas first).
                            if transcript and not item['text']:
                                item['text'] = transcript
                            item['status'] = 'done'

                    elif response_data['type'] == 'conversation.item.input_audio_transcription.failed':
                        # Sent instead of '.completed' when a turn can't be
                        # transcribed; logged at error level so the missing
                        # user row is visible.
                        logger.error(
                            'Event: %s - item=%s error=%s',
                            response_data['type'],
                            response_data.get('item_id'),
                            response_data.get('error'),
                        )

                    elif response_data['type'] == 'input_audio_buffer.speech_started':
                        # User barged in: stop playback unconditionally. Audio
                        # plays from the backlog for seconds after the
                        # transcript ends, so this must not depend on
                        # transcript state — the tail must still be stopped.
                        self.reset_stream(play_stream_only = True)
                        self._barge_in_event.set()
                        logger.debug(
                            'Event: %s - barge-in, stopping playback item=%s',
                            response_data['type'],
                            response_data.get('item_id'),
                        )
                        if self._current_response_id is not None:
                            # A response is still active server-side. Tell the
                            # server how much the user actually heard (so its
                            # state matches), then cancel it and remember the
                            # id so in-flight deltas get dropped, not replayed.
                            if self._current_item_id is not None and \
                                    self._played_samples > 0:
                                audio_end_ms = round(
                                    self._played_samples
                                    / CLIENT_SAMPLE_RATE * 1000
                                )
                                await websocket.send(json.dumps(dict(
                                    type = 'conversation.item.truncate',
                                    item_id = self._current_item_id,
                                    content_index = (
                                        self._current_content_index
                                    ),
                                    audio_end_ms = audio_end_ms,
                                )))
                                logger.debug(
                                    'Truncated item %s at %dms on barge-in',
                                    self._current_item_id,
                                    audio_end_ms,
                                )
                            self._cancelled_response_id = \
                                self._current_response_id
                            # Mark the interrupted row so the next response
                            # starts fresh instead of appending.
                            if self._current_item_id is not None and \
                                    self._current_item_id in self._items:
                                self._items[self._current_item_id]['status'] = \
                                    'interrupted'
                            await websocket.send(json.dumps(dict(
                                type = 'response.cancel'
                            )))
                        # Reset per-turn state for the next response.
                        self._current_item_id = None
                        self._played_samples = 0
                        # Reserve the user's row now so its seq sorts ahead of
                        # the reply (speech_started carries the user item_id).
                        item_id = response_data.get('item_id')
                        if item_id is not None:
                            self._get_or_create_item(item_id, 'user')

                    elif response_data['type'] == 'response.function_call_arguments.done':
                        logger.info('Event: %s - %s', response_data['type'], response_data)
                        tool_handler = TOOL_HANDLERS.get(response_data.get('name'))
                        if tool_handler:
                            arguments = json.loads(response_data.get('arguments') or '{}')
                            tool_handler(self, arguments)

                    elif response_data['type'] == 'response.done':
                        logger.debug('%s: %s', response_data['type'], response_data)
                        # No more deltas for this response; the next transcript
                        # delta must start a fresh item, not append to a stale
                        # one.
                        self._current_item_id = None
                        self._current_response_id = None
                        done_response_id = response_data.get('response', {}).get('id')
                        if done_response_id and done_response_id == self._cancelled_response_id:
                            self._cancelled_response_id = None
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
                        logger.debug('%s: %s', response_data['type'], response_data)
                    else:
                        logger.debug('Event: %s', response_data['type'])
                else:
                    logger.debug('No response')
            except Exception as e:
                logger.error('Error in receive loop', exc_info = e)
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
        self._items = {}
        self._next_seq = 0
        # Clear per-turn tracking so a restart can't truncate against a
        # previous session's item/playback position.
        self._current_item_id = None
        self._current_content_index = 0
        self._played_samples = 0
        self._cancelled_response_id = None
        self._current_response_id = None
        self.reset_stream()

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

    def _get_or_create_item(self, item_id: str, role: str) -> dict:
        """Return the transcript item for ``item_id``, creating it if new.

        A stable, monotonically increasing ``seq`` is assigned once, when the
        item is first seen, and defines the row order shown to the client.

        Args:
            item_id (str): The Realtime API conversation item id.
            role (str): ``'user'`` or ``'assistant'``.
        Returns:
            dict: The item record ``{"role", "text", "seq", "status"}``.
        """
        item = self._items.get(item_id)
        if item is None:
            item = dict(
                role = role, text = '', seq = self._next_seq,
                status = 'in_progress',
            )
            self._items[item_id] = item
            self._next_seq += 1
        return item

    def read_play_audio(self, nsamples: int, partial: bool = True):
        """Drain playback audio, counting what has been sent to the client.

        The running total (``_played_samples``) is what barge-in truncation
        uses to tell the server how much of the current item the user heard.

        Args:
            nsamples (int): Number of samples to read from the play FIFO.
            partial (bool): Whether a partial (< nsamples) read is
                allowed.
        Returns:
            av.AudioFrame | None: The drained frame, or None if empty.
        """
        frame = self._play_stream.read(nsamples, partial=partial)
        if frame:
            self._played_samples += frame.samples
        return frame

    def reset_stream(self, play_stream_only: bool = False):
        """Reset audio data stream

        With ``play_stream_only`` the play FIFO is force-recreated (emptied)
        rather than created-if-missing, so a barge-in actually drops the
        buffered assistant audio instead of letting it keep streaming out.
        """
        if play_stream_only:
            self._play_stream = av.audio.fifo.AudioFifo(
                format = FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
                layout = LAYOUT_MAPPING[CLIENT_CHANNELS],
            )
            return
        if not hasattr(self, '_record_stream') or self._record_stream is None:
            self._record_stream = av.audio.fifo.AudioFifo(
                format = FORMAT_MAPPING[API_SAMPLE_WIDTH],
                layout = LAYOUT_MAPPING[API_CHANNELS],
            )
        if not hasattr(self, '_play_stream') or self._play_stream is None:
            self._play_stream = av.audio.fifo.AudioFifo(
                format = FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
                layout = LAYOUT_MAPPING[CLIENT_CHANNELS],
            )
