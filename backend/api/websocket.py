import asyncio
import av
import base64
import json
import logging
import os
import sys
from pathlib import Path

from fastapi import WebSocket, WebSocketDisconnect

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.realtime.realtime_client import OpenAIRealtimeAPIWrapper
from src.prompts.prompts import load_prompts
from src.audio.audio_utils import pcm_audio_to_audio_frame, audio_frame_to_pcm_audio
from src.realtime.config import (
    CLIENT_SAMPLE_RATE, CLIENT_SAMPLE_WIDTH, CLIENT_CHANNELS,
    FORMAT_MAPPING, LAYOUT_MAPPING
)

logger = logging.getLogger(__name__)


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
        self.prompt_key = list(load_prompts().keys())[0] if load_prompts() else "default"
        self.loop = asyncio.get_event_loop()
        self.last_transcript_lengths = {}  # message index -> chars already forwarded

    async def handle(self):
        """Main WebSocket message handler"""
        await self.websocket.accept()
        logger.info("WebSocket connection accepted")

        try:
            while True:
                # Receive message from client
                data = await self.websocket.receive_text()
                message = json.loads(data)

                if message["type"] == "control":
                    if message.get("action") == "start":
                        await self._start_conversation()
                    elif message.get("action") == "stop":
                        await self._stop_conversation()
                elif message["type"] == "audio":
                    # Audio frame from client
                    await self._handle_audio_frame(message)
                elif message["type"] == "config":
                    # Configuration update (timeout, prompt)
                    await self._handle_config(message)

        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
            if self.api_wrapper.recording:
                self.api_wrapper.stop()
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
            try:
                await self.websocket.send_text(
                    json.dumps({"type": "status", "message": f"Error: {str(e)}"})
                )
            except Exception:
                pass

    async def _monitor_messages(self):
        """Monitor and forward transcript growth from API to client

        Messages are mutated in place as transcript deltas stream in
        (e.g. assistant content starts as '' and grows), so we track how
        many characters of each message we've already forwarded by index
        and only send the newly-added substring, instead of diffing on
        message count (which would forward a message once, prematurely,
        and never send its later growth).
        """
        try:
            while self.recording:
                messages = self.api_wrapper._messages
                for idx, msg in enumerate(messages):
                    content = msg.get("content")
                    if not content:
                        continue
                    prev_len = self.last_transcript_lengths.get(idx, 0)
                    if len(content) > prev_len:
                        delta = content[prev_len:]
                        await self.websocket.send_text(
                            json.dumps({
                                "type": "transcript",
                                "role": msg.get("role"),
                                "delta": delta,
                                "index": idx,
                            })
                        )
                        self.last_transcript_lengths[idx] = len(content)
                        logger.debug(f"Forwarded {msg.get('role')} transcript delta to client")
                await asyncio.sleep(0.3)
        except Exception as e:
            logger.error(f"Error monitoring messages: {e}")

    async def _stream_audio_responses(self):
        """Stream audio responses from OpenAI back to client"""
        try:
            while self.recording:
                if self.api_wrapper.consume_barge_in():
                    # The user just interrupted the assistant: audio already sent
                    # to the client is likely still scheduled for playback there,
                    # so tell it to stop immediately instead of waiting it out.
                    await self.websocket.send_text(
                        json.dumps({"type": "clear_audio"})
                    )
                frame = self.api_wrapper._play_stream.read(4096, partial=True)
                if frame:
                    pcm_audio = audio_frame_to_pcm_audio(frame)
                    base64_audio = base64.b64encode(pcm_audio).decode('utf-8')
                    await self.websocket.send_text(
                        json.dumps({"type": "audio", "data": base64_audio})
                    )
                    logger.debug(f"Sent {len(pcm_audio)} bytes of audio to client")
                else:
                    await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"Error streaming audio responses: {e}")

    async def _handle_audio_frame(self, message: dict):
        """Process incoming audio frame"""
        if not self.recording:
            return

        try:
            # Decode base64 audio to bytes
            audio_bytes = base64.b64decode(message.get("data", ""))
            if not audio_bytes:
                return

            # Convert PCM bytes to audio frame and write to FIFO
            frame = pcm_audio_to_audio_frame(
                audio_bytes,
                format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
                layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
                sample_rate=CLIENT_SAMPLE_RATE
            )

            # Write to the record FIFO buffer
            self.api_wrapper._record_stream.write(frame)
            logger.debug(f"Wrote {len(audio_bytes)} bytes to audio stream")
        except Exception as e:
            logger.error(f"Audio frame error: {e}")

    async def _handle_config(self, message: dict):
        """Handle configuration updates"""
        try:
            if "timeout" in message:
                self.session_timeout = message["timeout"]
                self.api_wrapper.set_session_timeout(self.session_timeout)
                await self.websocket.send_text(
                    json.dumps({"type": "status", "message": "Timeout updated"})
                )

            if "prompt_key" in message:
                prompts = load_prompts()
                if message["prompt_key"] in prompts:
                    self.prompt_key = message["prompt_key"]
                    self.api_wrapper.set_instructions(prompts[self.prompt_key]["instructions"])
                    await self.websocket.send_text(
                        json.dumps({"type": "status", "message": "Prompt updated"})
                    )
                else:
                    await self.websocket.send_text(
                        json.dumps({"type": "status", "message": f"Prompt '{message['prompt_key']}' not found"})
                    )
        except Exception as e:
            logger.error(f"Error handling config: {e}")
            await self.websocket.send_text(
                json.dumps({"type": "status", "message": f"Config error: {str(e)}"})
            )

    async def _start_conversation(self):
        """Start recording and API connection"""
        if self.recording:
            return

        self.recording = True
        await self.websocket.send_text(
            json.dumps({"type": "status", "message": "Starting conversation..."})
        )

        try:
            # Set up FIFO buffers for audio
            self.api_wrapper._record_stream = av.audio.fifo.AudioFifo(
                format=self.api_wrapper._resampler_for_api.format,
                layout=self.api_wrapper._resampler_for_api.layout,
            )
            self.api_wrapper._play_stream = av.audio.fifo.AudioFifo(
                format=self.api_wrapper._resampler_for_client.format,
                layout=self.api_wrapper._resampler_for_client.layout,
            )

            # Run the API connection in background task to allow message handler to continue
            self.api_task = asyncio.create_task(self.api_wrapper.run())
            # Monitor and forward messages from API to client
            self.last_transcript_lengths = {}
            self.monitor_task = asyncio.create_task(self._monitor_messages())
            # Stream audio responses back to client
            self.stream_task = asyncio.create_task(self._stream_audio_responses())
        except Exception as e:
            logger.error(f"Conversation error: {e}")
            await self.websocket.send_text(
                json.dumps({"type": "status", "message": f"Error: {str(e)}"})
            )
            self.recording = False

    async def _stop_conversation(self):
        """Stop recording and close API connection"""
        if not self.recording:
            return

        self.api_wrapper.stop()
        self.recording = False

        # Wait for monitor task to complete
        if self.monitor_task and not self.monitor_task.done():
            try:
                await asyncio.wait_for(self.monitor_task, timeout=2)
            except asyncio.TimeoutError:
                logger.warning("Monitor task did not complete within timeout")
                self.monitor_task.cancel()

        # Wait for API task to complete
        if self.api_task and not self.api_task.done():
            try:
                await asyncio.wait_for(self.api_task, timeout=5)
            except asyncio.TimeoutError:
                logger.warning("API task did not complete within timeout")
                self.api_task.cancel()

        # Wait for stream task to complete
        if self.stream_task and not self.stream_task.done():
            try:
                await asyncio.wait_for(self.stream_task, timeout=2)
            except asyncio.TimeoutError:
                logger.warning("Stream task did not complete within timeout")
                self.stream_task.cancel()

        await self.websocket.send_text(
            json.dumps({"type": "status", "message": "Conversation ended"})
        )


async def audio_websocket_handler(websocket: WebSocket, api_key: str):
    """WebSocket endpoint handler"""
    session = AudioStreamSession(websocket, api_key)
    await session.handle()


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for audio streaming"""
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
