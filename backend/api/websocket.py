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

logger = logging.getLogger(__name__)


class AudioStreamSession:
    """Manages a single WebSocket connection's audio session"""

    def __init__(self, websocket: WebSocket, api_key: str):
        self.websocket = websocket
        self.api_wrapper = OpenAIRealtimeAPIWrapper(api_key=api_key)
        self.recording = False
        self.session_timeout = 120
        self.prompt_key = list(load_prompts().keys())[0] if load_prompts() else "default"
        self.loop = asyncio.get_event_loop()

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

    async def _handle_audio_frame(self, message: dict):
        """Process incoming audio frame"""
        if not self.recording:
            return

        try:
            # Decode base64 audio to bytes
            audio_bytes = base64.b64decode(message.get("data", ""))
            if not audio_bytes:
                return

            # Write to record stream FIFO
            # The FIFO is fed by audio_frame_callback -> send() task
            # For now, we acknowledge receipt
            logger.debug(f"Received {len(audio_bytes)} bytes of audio")
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

            # Run the API connection
            await self.api_wrapper.run()
        except Exception as e:
            logger.error(f"Conversation error: {e}")
            await self.websocket.send_text(
                json.dumps({"type": "status", "message": f"Error: {str(e)}"})
            )
        finally:
            self.recording = False

    async def _stop_conversation(self):
        """Stop recording and close API connection"""
        if not self.recording:
            return

        self.api_wrapper.stop()
        self.recording = False
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
