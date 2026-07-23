import asyncio
import base64
import logging

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from api.models import (
    AudioMessage,
    ConfigMessage,
    ControlMessage,
    IncomingMessage,
)
from api.ws.constants import (
    API_TASK_TIMEOUT_S,
    AUDIO_CHUNK_SIZE,
    MAX_AUDIO_MESSAGES_PER_SECOND,
    MAX_MESSAGE_BYTES,
    MONITOR_POLL_INTERVAL_S,
    MONITOR_TASK_TIMEOUT_S,
    STREAM_IDLE_SLEEP_S,
    STREAM_TASK_TIMEOUT_S,
)
from api.ws.limits import RateLimiter
from api.ws.messenger import ClientMessenger
from src.prompts import load_prompts
from src.realtime import OpenAIRealtimeAPIWrapper
from src.realtime.config import (
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    MODEL_KEYS,
    VOICE_KEYS,
)

logger = logging.getLogger(__name__)

_incoming_message_adapter: TypeAdapter = TypeAdapter(IncomingMessage)


class AudioStreamSession:
    """Manages a single WebSocket connection's audio session"""

    def __init__(self, websocket: WebSocket, api_key: str):
        self.websocket = websocket
        self.messenger = ClientMessenger(websocket)
        self.rate_limiter = RateLimiter(MAX_AUDIO_MESSAGES_PER_SECOND)
        self.api_wrapper = OpenAIRealtimeAPIWrapper(api_key=api_key)
        self.recording = False
        self.api_task = None
        self.monitor_task = None
        self.stream_task = None
        prompts = load_prompts()
        self.prompt_key = next(iter(prompts), "default")
        self.model = DEFAULT_MODEL
        self.voice = DEFAULT_VOICE
        self.loop = asyncio.get_event_loop()
        # item_id -> chars already forwarded
        self.last_transcript_lengths: dict[str, int] = {}

    async def handle(self):
        """Main WebSocket message handler"""
        await self.websocket.accept()
        logger.info("WebSocket connection accepted")

        try:
            while True:
                data = await self.websocket.receive_text()

                if len(data) > MAX_MESSAGE_BYTES:
                    logger.warning("Rejected oversized WebSocket message")
                    await self.messenger.send_status("Message too large")
                    continue

                try:
                    message = _incoming_message_adapter.validate_json(data)
                except ValidationError as exc:
                    logger.warning(f"Rejected malformed message: {exc}")
                    await self.messenger.send_status("Invalid message")
                    continue

                if isinstance(message, ControlMessage):
                    if message.action == "start":
                        await self._start_conversation()
                    elif message.action == "stop":
                        await self._stop_conversation()
                elif isinstance(message, AudioMessage):
                    if self.rate_limiter.is_limited():
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
            await self.messenger.send_status("An unexpected error occurred")

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
        await self.messenger.send_status(reason)

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
                items = self.api_wrapper.transcript_snapshot()
                for item_id, item in items:
                    text = item.get("text")
                    if not text:
                        continue
                    prev_len = self.last_transcript_lengths.get(item_id, 0)
                    if len(text) > prev_len:
                        delta = text[prev_len:]
                        await self.messenger.send_transcript(
                            item.get("role"), item.get("seq"), delta
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
                    await self.messenger.send_clear_audio()
                pcm_audio = self.api_wrapper.read_client_pcm(
                    AUDIO_CHUNK_SIZE, partial=True
                )
                if pcm_audio:
                    base64_audio = base64.b64encode(pcm_audio).decode('utf-8')
                    await self.messenger.send_audio(base64_audio)
                    logger.debug(
                        f"Sent {len(pcm_audio)} bytes of audio to client"
                    )
                else:
                    if (
                        self.recording
                        and self.api_task is not None
                        and self.api_task.done()
                    ):
                        self.recording = False
                        await self.messenger.send_conversation_ended()
                        break
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

            self.api_wrapper.write_client_pcm(audio_bytes)
            logger.debug(f"Wrote {len(audio_bytes)} bytes to audio stream")
        except Exception as e:
            logger.error(f"Audio frame error: {e}")

    async def _handle_config(self, message: ConfigMessage):
        """Apply a client-requested prompt, model, and/or voice change.

        Parameters
        ----------
        message : ConfigMessage
            The requested configuration update; any field may be omitted.
        """
        try:
            if message.prompt_key is not None:
                prompts = load_prompts()
                if message.prompt_key in prompts:
                    self.prompt_key = message.prompt_key
                    self.api_wrapper.set_instructions(
                        prompts[self.prompt_key]["instructions"]
                    )
                    await self.messenger.send_status("Prompt updated")
                else:
                    await self.messenger.send_status(
                        f"Prompt '{message.prompt_key}' not found"
                    )

            if message.model is not None:
                if message.model in MODEL_KEYS:
                    self.model = message.model
                    self.api_wrapper.set_model(self.model)
                    await self.messenger.send_status("Model updated")
                else:
                    await self.messenger.send_status(
                        f"Model '{message.model}' not found"
                    )

            if message.voice is not None:
                if message.voice in VOICE_KEYS:
                    self.voice = message.voice
                    self.api_wrapper.set_voice(self.voice)
                    await self.messenger.send_status("Voice updated")
                else:
                    await self.messenger.send_status(
                        f"Voice '{message.voice}' not found"
                    )
        except Exception as e:
            logger.error(f"Error handling config: {e}")
            await self.messenger.send_status("Failed to apply configuration")

    async def _start_conversation(self):
        """Start recording and API connection"""
        if self.recording:
            return

        self.recording = True
        await self.messenger.send_status("Starting conversation...")

        try:
            self.api_wrapper.reset_streams()
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
            await self.messenger.send_status("Failed to start conversation")
            self.recording = False

    async def _shutdown_task(self, task, timeout, name):
        """Await a background task, cancelling it if it overruns ``timeout``.

        Parameters
        ----------
        task : asyncio.Task | None
            The task to wind down; ``None`` or already-done tasks are skipped.
        timeout : float
            Seconds to wait before cancelling.
        name : str
            Human-readable task name used in the timeout warning.
        """
        if task and not task.done():
            try:
                await asyncio.wait_for(task, timeout=timeout)
            except TimeoutError:
                logger.warning(
                    f"{name} task did not complete within timeout"
                )
                task.cancel()

    async def _stop_conversation(self):
        """Stop recording and close API connection"""
        if not self.recording:
            return

        self.api_wrapper.stop()
        self.recording = False

        for task, timeout, name in (
            (self.monitor_task, MONITOR_TASK_TIMEOUT_S, "Monitor"),
            (self.api_task, API_TASK_TIMEOUT_S, "API"),
            (self.stream_task, STREAM_TASK_TIMEOUT_S, "Stream"),
        ):
            await self._shutdown_task(task, timeout, name)

        await self.messenger.send_status("Conversation ended")
