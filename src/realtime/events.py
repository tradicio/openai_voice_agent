import asyncio
import base64
import json
from dataclasses import dataclass

from src.audio.formats import CLIENT_SAMPLE_RATE
from src.log import get_logger
from src.realtime.tools import TOOL_HANDLERS

logger = get_logger(__name__)


@dataclass
class TurnState:
    """Per-turn tracking used for barge-in truncation and row ordering."""
    current_response_id: str | None = None
    cancelled_response_id: str | None = None
    current_item_id: str | None = None
    current_content_index: int = 0

    def reset(self) -> None:
        self.current_response_id = None
        self.cancelled_response_id = None
        self.current_item_id = None
        self.current_content_index = 0


class EventDispatcher:
    """Routes a parsed Realtime API event to its handler.

    Handlers mutate the transcript store, audio pipeline, and turn state,
    and may send control events (truncate / cancel) back to the API socket.
    """

    _DEBUG_PREFIXES = (
        'session.created',
        'session.updated',
        'conversation.item.created',
        'response.output_audio.',
        'rate_limits.updated',
    )

    def __init__(self, client, transcript, audio, turn, barge_in_event):
        self._client = client
        self._transcript = transcript
        self._audio = audio
        self._turn = turn
        self._barge_in_event = barge_in_event
        self._handlers = {
            'response.output_audio.delta': self._on_audio_delta,
            'response.output_audio_transcript.delta': self._on_transcript_delta,
            'response.output_audio_transcript.done': self._on_transcript_done,
            'conversation.item.input_audio_transcription.delta':
                self._on_input_transcription_delta,
            'conversation.item.input_audio_transcription.completed':
                self._on_input_transcription_completed,
            'conversation.item.input_audio_transcription.failed':
                self._on_input_transcription_failed,
            'input_audio_buffer.speech_started': self._on_speech_started,
            'response.function_call_arguments.done':
                self._on_function_call_done,
            'response.done': self._on_response_done,
            'error': self._on_error,
        }

    async def dispatch(self, event: dict, websocket) -> None:
        handler = self._handlers.get(event['type'])
        if handler is not None:
            await handler(event, websocket)
        elif any(event['type'].startswith(p) for p in self._DEBUG_PREFIXES):
            logger.debug('%s: %s', event['type'], event)
        else:
            logger.debug('Event: %s', event['type'])

    async def _on_audio_delta(self, event, websocket):
        # Drop leftover audio still in flight for an already-cancelled response.
        if self._turn.cancelled_response_id is not None and \
                event.get('response_id') == self._turn.cancelled_response_id:
            return
        base64_audio = event['delta']
        if not base64_audio:
            return
        item_id = event.get('item_id')
        if item_id is not None and item_id != self._turn.current_item_id:
            self._turn.current_item_id = item_id
            self._turn.current_content_index = event.get('content_index', 0)
            self._audio.reset_played()
        # Mark the response active so a barge-in can cancel it before any
        # transcript delta arrives (audio leads the transcript).
        self._turn.current_response_id = event.get('response_id')
        pcm_audio = base64.b64decode(base64_audio)
        self._audio.write_api_pcm(pcm_audio)
        logger.debug(
            'Event: %s - received audio from OpenAI (%d bytes)',
            event['type'], len(pcm_audio),
        )

    async def _on_transcript_delta(self, event, websocket):
        # Drop leftover transcript for an already-cancelled response.
        if self._turn.cancelled_response_id is None or \
                event.get('response_id') != self._turn.cancelled_response_id:
            self._turn.current_response_id = event.get('response_id')
            item_id = event.get('item_id')
            if item_id is not None:
                self._transcript.append_delta(item_id, 'assistant', event['delta'])

    async def _on_transcript_done(self, event, websocket):
        logger.info('Event: %s - %s', event['type'], event['transcript'])
        item_id = event.get('item_id')
        if item_id is not None:
            self._transcript.mark_status(item_id, 'done')

    async def _on_input_transcription_delta(self, event, websocket):
        logger.debug(
            'Event: %s - item=%s delta=%r',
            event['type'], event.get('item_id'), event.get('delta'),
        )
        item_id = event.get('item_id')
        if item_id is not None:
            self._transcript.append_delta(item_id, 'user', event.get('delta', ''))

    async def _on_input_transcription_completed(self, event, websocket):
        logger.debug(
            'Event: %s - item=%s transcript=%r',
            event['type'], event.get('item_id'), event.get('transcript'),
        )
        item_id = event.get('item_id')
        if item_id is not None:
            self._transcript.fill_if_empty(item_id, 'user', event.get('transcript'))
            self._transcript.mark_status(item_id, 'done')

    async def _on_input_transcription_failed(self, event, websocket):
        logger.error(
            'Event: %s - item=%s error=%s',
            event['type'], event.get('item_id'), event.get('error'),
        )

    async def _on_speech_started(self, event, websocket):
        # User barged in: stop playback unconditionally.
        self._audio.reset_play()
        self._barge_in_event.set()
        logger.debug(
            'Event: %s - barge-in, stopping playback item=%s',
            event['type'], event.get('item_id'),
        )
        if self._turn.current_response_id is not None:
            if self._turn.current_item_id is not None and \
                    self._audio.played_samples > 0:
                audio_end_ms = round(
                    self._audio.played_samples / CLIENT_SAMPLE_RATE * 1000
                )
                await websocket.send(json.dumps(dict(
                    type='conversation.item.truncate',
                    item_id=self._turn.current_item_id,
                    content_index=self._turn.current_content_index,
                    audio_end_ms=audio_end_ms,
                )))
                logger.debug(
                    'Truncated item %s at %dms on barge-in',
                    self._turn.current_item_id, audio_end_ms,
                )
            self._turn.cancelled_response_id = self._turn.current_response_id
            if self._turn.current_item_id is not None:
                self._transcript.mark_status(
                    self._turn.current_item_id, 'interrupted'
                )
            await websocket.send(json.dumps(dict(type='response.cancel')))
        self._turn.current_item_id = None
        self._audio.reset_played()
        item_id = event.get('item_id')
        if item_id is not None:
            self._transcript.get_or_create(item_id, 'user')

    async def _on_function_call_done(self, event, websocket):
        logger.info('Event: %s - %s', event['type'], event)
        tool_handler = TOOL_HANDLERS.get(event.get('name'))
        if tool_handler:
            arguments = json.loads(event.get('arguments') or '{}')
            tool_handler(self._client, arguments)

    async def _on_response_done(self, event, websocket):
        logger.debug('%s: %s', event['type'], event)
        self._turn.current_item_id = None
        self._turn.current_response_id = None
        done_response_id = event.get('response', {}).get('id')
        if done_response_id and done_response_id == self._turn.cancelled_response_id:
            self._turn.cancelled_response_id = None
        if self._client._ending:
            remaining_seconds = self._audio.play_buffer_seconds()
            logger.info(
                'Waiting %.2fs for the goodbye message to finish playing',
                remaining_seconds,
            )
            await asyncio.sleep(remaining_seconds + 0.5)
            logger.info('Ending conversation as requested by the assistant')
            self._client.stop()

    async def _on_error(self, event, websocket):
        logger.error('Event: %s - %s', event['type'], event)
