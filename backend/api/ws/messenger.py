import json

from fastapi import WebSocket


class ClientMessenger:
    """Owns all outbound WebSocket envelopes for a session.

    Best-effort methods swallow send failures (status the client can
    live without). Raising methods let failures propagate so a dead
    socket trips the caller's halt path.
    """

    def __init__(self, websocket: WebSocket):
        self._websocket = websocket

    # --- best-effort: swallow send failures ---

    async def send_status(self, message: str) -> None:
        """Send a status message, ignoring send failures."""
        try:
            await self._websocket.send_text(
                json.dumps({"type": "status", "message": message})
            )
        except Exception:
            pass

    async def send_conversation_ended(self) -> None:
        """Tell the client the call ended server-side, ignoring failures."""
        try:
            await self._websocket.send_text(
                json.dumps({"type": "conversation_ended"})
            )
        except Exception:
            pass

    # --- raising: let failures propagate ---

    async def send_transcript(self, role, seq, delta: str) -> None:
        """Forward a transcript delta to the client."""
        await self._websocket.send_text(
            json.dumps({
                "type": "transcript",
                "role": role,
                "seq": seq,
                "delta": delta,
            })
        )

    async def send_audio(self, b64_data: str) -> None:
        """Send a base64-encoded PCM audio chunk to the client."""
        await self._websocket.send_text(
            json.dumps({"type": "audio", "data": b64_data})
        )

    async def send_clear_audio(self) -> None:
        """Tell the client to drop audio it has already scheduled."""
        await self._websocket.send_text(
            json.dumps({"type": "clear_audio"})
        )
