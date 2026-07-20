import asyncio
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

                if message["type"] == "audio":
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

        # TODO: Decode base64 audio and write to FIFO buffer
        # This will be completed in Task 4
        pass

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
