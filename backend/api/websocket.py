import asyncio
import base64
import json
import logging
import os
import time
from collections import deque

import av
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from api.models import (
    AudioMessage,
    ConfigMessage,
    ControlMessage,
    IncomingMessage,
)
from src.audio.audio_utils import (
    audio_frame_to_pcm_audio,
    pcm_audio_to_audio_frame,
)
from src.prompts.prompts import load_prompts
from src.realtime.config import (
    CLIENT_CHANNELS,
    CLIENT_SAMPLE_RATE,
    CLIENT_SAMPLE_WIDTH,
    FORMAT_MAPPING,
    LAYOUT_MAPPING,
)
from src.realtime.realtime_client import OpenAIRealtimeAPIWrapper

logger = logging.getLogger(__name__)

# Audio streaming tuning knobs.
AUDIO_CHUNK_SIZE = 4096
MONITOR_POLL_INTERVAL_S = 0.3
STREAM_IDLE_SLEEP_S = 0.01
MONITOR_TASK_TIMEOUT_S = 2
API_TASK_TIMEOUT_S = 5
STREAM_TASK_TIMEOUT_S = 2

# Reject oversized messages and cap the audio frame rate so a single
# client can't exhaust memory/CPU.
MAX_MESSAGE_BYTES = 128 * 1024
MAX_AUDIO_MESSAGES_PER_SECOND = 50

_incoming_message_adapter: TypeAdapter = TypeAdapter(IncomingMessage)


class AudioStreamSession:
    """Manages a single WebSocket connection's audio session"""

    def __init__(self, websocket: WebSocket, api_key: str):
        self.websocket = websocket
        self.api_wrapper = OpenAIRealtimeAPIWrapper(api_key=api_key)
        self.recording = False
        self.api_task = None
        self.monitor_task = None
        self.stream_task = None
        self.session_timeout = 120
        prompts = load_prompts()
        self.prompt_key = next(iter(prompts), "default")
        self.loop = asyncio.get_event_loop()
        # item_id -> chars already forwarded
        self.last_transcript_lengths: dict[str, int] = {}
        self._audio_message_times: deque = deque()

    async def handle(self):
        """Main WebSocket message handler"""
        await self.websocket.accept()
        logger.info("WebSocket connection accepted")

        try:
            while True:
                data = await self.websocket.receive_text()

                if len(data) > MAX_MESSAGE_BYTES:
                    logger.warning("Rejected oversized WebSocket message")
                    await self._send_status("Message too large")
                    continue

                try:
                    message = _incoming_message_adapter.validate_json(data)
                except ValidationError as exc:
                    logger.warning(f"Rejected malformed message: {exc}")
                    await self._send_status("Invalid message")
                    continue

                if isinstance(message, ControlMessage):
                    if message.action == "start":
                        await self._start_conversation()
                    elif message.action == "stop":
                        await self._stop_conversation()
                elif isinstance(message, AudioMessage):
                    if self._audio_rate_limited():
                        continue
                    await self._handle_audio_frame(message)
                elif isinstance(message, ConfigMessage):
                    await self._handle_config(message)

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
            if self.api_wrapper.recording:
                self.api_wrapper.stop()
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            await self._send_status("An unexpected error occurred")

    async def _send_status(self, message: str) -> None:
        """Send a status message to the client, ignoring send failures.

        Parameters
        ----------
        message : str
            The user-facing status text to deliver.
        """
        try:
            await self.websocket.send_text(
                json.dumps({"type": "status", "message": message})
            )
        except Exception:
            pass

    def _audio_rate_limited(self) -> bool:
        """Check and record whether the incoming audio rate is exceeded.

        Returns
        -------
        bool
            True if the client has sent more than
            ``MAX_AUDIO_MESSAGES_PER_SECOND`` audio frames within the
            trailing one-second window and the current frame should be
            dropped.
        """
        now = time.monotonic()
        window = self._audio_message_times
        while window and now - window[0] > 1:
            window.popleft()
        if len(window) >= MAX_AUDIO_MESSAGES_PER_SECOND:
            logger.warning("Audio message rate limit exceeded, dropping frame")
            return True
        window.append(now)
        return False

    async def _notify_and_halt(self, reason: str) -> None:
        """Stop the session and tell the client why.

        Used when a background streaming task dies unexpectedly, so the
        client isn't left waiting on a conversation that will never
        produce further audio or transcript updates.

        Parameters
        ----------
        reason : str
            User-facing explanation sent to the client as a status message.
        """
        self.recording = False
        await self._send_status(reason)

    async def _monitor_messages(self):
        """Monitor and forward transcript growth from API to client.

        Items are mutated in place as transcript deltas stream in (text
        starts as '' and grows), so we track how many characters of each
        item we've already forwarded, keyed by the API's stable ``item_id``,
        and send only the newly-added substring. The forwarded ``seq`` gives
        the client a stable creation order for the rows.
        """
        try:
            while self.recording:
                # Snapshot: receive() may insert items mid-iteration (which
                # would raise RuntimeError); new ones are picked up next poll.
                items = list(self.api_wrapper._items.items())
                for item_id, item in items:
                    text = item.get("text")
                    if not text:
                        continue
                    prev_len = self.last_transcript_lengths.get(item_id, 0)
                    if len(text) > prev_len:
                        delta = text[prev_len:]
                        await self.websocket.send_text(
                            json.dumps({
                                "type": "transcript",
                                "role": item.get("role"),
                                "seq": item.get("seq"),
                                "delta": delta,
                            })
                        )
                        self.last_transcript_lengths[item_id] = len(text)
                        logger.debug(
                            f"Forwarded {item.get('role')} transcript "
                            "delta to client"
                        )
                await asyncio.sleep(MONITOR_POLL_INTERVAL_S)
        except Exception as e:
            logger.error(f"Error monitoring messages: {e}")
            await self._notify_and_halt(
                "Transcript streaming stopped unexpectedly"
            )

    async def _stream_audio_responses(self):
        """Stream audio responses from OpenAI back to client"""
        try:
            while self.recording:
                if self.api_wrapper.consume_barge_in():
                    # User interrupted: tell the client to stop audio it has
                    # already scheduled instead of waiting it out.
                    await self.websocket.send_text(
                        json.dumps({"type": "clear_audio"})
                    )
                frame = self.api_wrapper.read_play_audio(
                    AUDIO_CHUNK_SIZE, partial=True
                )
                if frame:
                    pcm_audio = audio_frame_to_pcm_audio(frame)
                    base64_audio = base64.b64encode(
                        pcm_audio
                    ).decode('utf-8')
                    await self.websocket.send_text(
                        json.dumps({"type": "audio", "data": base64_audio})
                    )
                    logger.debug(
                        f"Sent {len(pcm_audio)} bytes of audio to client"
                    )
                else:
                    await asyncio.sleep(STREAM_IDLE_SLEEP_S)
        except Exception as e:
            logger.error(f"Error streaming audio responses: {e}")
            await self._notify_and_halt("Audio streaming stopped unexpectedly")

    async def _handle_audio_frame(self, message: AudioMessage):
        """Decode and enqueue an incoming client audio frame.

        Parameters
        ----------
        message : AudioMessage
            The base64-encoded PCM audio frame received from the client.
        """
        if not self.recording:
            return

        try:
            audio_bytes = base64.b64decode(message.data)
            if not audio_bytes:
                return

            frame = pcm_audio_to_audio_frame(
                audio_bytes,
                format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
                layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
                sample_rate=CLIENT_SAMPLE_RATE
            )

            self.api_wrapper._record_stream.write(frame)
            logger.debug(f"Wrote {len(audio_bytes)} bytes to audio stream")
        except Exception as e:
            logger.error(f"Audio frame error: {e}")

    async def _handle_config(self, message: ConfigMessage):
        """Apply a client-requested session timeout and/or prompt change.

        Parameters
        ----------
        message : ConfigMessage
            The requested configuration update; either field may be
            omitted.
        """
        try:
            if message.timeout is not None:
                self.session_timeout = message.timeout
                self.api_wrapper.set_session_timeout(self.session_timeout)
                await self._send_status("Timeout updated")

            if message.prompt_key is not None:
                prompts = load_prompts()
                if message.prompt_key in prompts:
                    self.prompt_key = message.prompt_key
                    self.api_wrapper.set_instructions(prompts[self.prompt_key]["instructions"])
                    await self._send_status("Prompt updated")
                else:
                    await self._send_status(
                        f"Prompt '{message.prompt_key}' not found"
                    )
        except Exception as e:
            logger.error(f"Error handling config: {e}")
            await self._send_status("Failed to apply configuration")

    async def _start_conversation(self):
        """Start recording and API connection"""
        if self.recording:
            return

        self.recording = True
        await self._send_status("Starting conversation...")

        try:
            self.api_wrapper._record_stream = av.audio.fifo.AudioFifo(
                format=self.api_wrapper._resampler_for_api.format,
                layout=self.api_wrapper._resampler_for_api.layout,
            )
            self.api_wrapper._play_stream = av.audio.fifo.AudioFifo(
                format=self.api_wrapper._resampler_for_client.format,
                layout=self.api_wrapper._resampler_for_client.layout,
            )

            # Run the API connection in the background so the handler loop
            # keeps servicing the client.
            self.api_task = asyncio.create_task(self.api_wrapper.run())
            self.last_transcript_lengths = {}
            self.monitor_task = asyncio.create_task(
                self._monitor_messages()
            )
            self.stream_task = asyncio.create_task(
                self._stream_audio_responses()
            )
        except Exception as e:
            logger.error(f"Conversation error: {e}")
            await self._send_status("Failed to start conversation")
            self.recording = False

    async def _stop_conversation(self):
        """Stop recording and close API connection"""
        if not self.recording:
            return

        self.api_wrapper.stop()
        self.recording = False

        if self.monitor_task and not self.monitor_task.done():
            try:
                await asyncio.wait_for(
                    self.monitor_task, timeout=MONITOR_TASK_TIMEOUT_S
                )
            except TimeoutError:
                logger.warning("Monitor task did not complete within timeout")
                self.monitor_task.cancel()

        if self.api_task and not self.api_task.done():
            try:
                await asyncio.wait_for(
                    self.api_task, timeout=API_TASK_TIMEOUT_S
                )
            except TimeoutError:
                logger.warning("API task did not complete within timeout")
                self.api_task.cancel()

        if self.stream_task and not self.stream_task.done():
            try:
                await asyncio.wait_for(
                    self.stream_task, timeout=STREAM_TASK_TIMEOUT_S
                )
            except TimeoutError:
                logger.warning("Stream task did not complete within timeout")
                self.stream_task.cancel()

        await self._send_status("Conversation ended")


async def audio_websocket_handler(websocket: WebSocket, api_key: str):
    """Create and run a single audio streaming session.

    Parameters
    ----------
    websocket : WebSocket
        The accepted client connection.
    api_key : str
        OpenAI API key used to open the realtime session.
    """
    session = AudioStreamSession(websocket, api_key)
    await session.handle()


def _is_allowed_origin(origin: str | None) -> bool:
    """Check whether a WebSocket handshake's Origin header is trusted.

    Parameters
    ----------
    origin : str | None
        The value of the incoming ``Origin`` header, if any.

    Returns
    -------
    bool
        True if the origin matches the configured frontend URL or the
        local backend origin, False otherwise (including when absent).
    """
    if not origin:
        return False
    allowed_origins = {
        os.getenv("FRONTEND_URL", "http://localhost:3000"),
        "http://localhost:8000",
    }
    return origin in allowed_origins


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for audio streaming"""
    if not _is_allowed_origin(websocket.headers.get("origin")):
        logger.warning(
            f"Rejected WebSocket handshake from disallowed origin: "
            f"{websocket.headers.get('origin')!r}"
        )
        await websocket.close(code=1008, reason="Origin not allowed")
        return

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        await websocket.accept()
        await websocket.send_json({
            "type": "status",
            "message": "Error: OPENAI_API_KEY not set"
        })
        await websocket.close(code=1011, reason="API key not configured")
        return

    await audio_websocket_handler(websocket, api_key)
