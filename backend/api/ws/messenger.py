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

    async def _send(self, payload: dict, *, best_effort: bool = False) -> None:
        """Serialize and send one envelope.

        With ``best_effort=True`` send failures are swallowed (status
        the client can live without); otherwise they propagate so a
        dead socket trips the caller's halt path.
        """
        if best_effort:
            try:
                await self._websocket.send_text(json.dumps(payload))
            except Exception:
                pass
        else:
            await self._websocket.send_text(json.dumps(payload))

    # --- best-effort: swallow send failures ---

    async def send_status(self, message: str) -> None:
        """Send a status message, ignoring send failures."""
        await self._send(
            {"type": "status", "message": message}, best_effort=True
        )

    async def send_conversation_ended(self) -> None:
        """Tell the client the call ended server-side, ignoring send
        failures.

        Emitted when the assistant's ``end_conversation`` tool (or the
        session timeout) stops the conversation on the server, so the
        client can reset its UI back to the idle "Start Conversation"
        state without the user having pressed stop.
        """
        await self._send({"type": "conversation_ended"}, best_effort=True)

    # --- raising: let failures propagate ---

    async def send_transcript(
        self, role: str | None, seq: int | None, delta: str
    ) -> None:
        """Forward a transcript delta to the client."""
        await self._send(
            {
                "type": "transcript",
                "role": role,
                "seq": seq,
                "delta": delta,
            }
        )

    async def send_audio(self, b64_data: str) -> None:
        """Send a base64-encoded PCM audio chunk to the client."""
        await self._send({"type": "audio", "data": b64_data})

    async def send_clear_audio(self) -> None:
        """Tell the client to drop audio it has already scheduled."""
        await self._send({"type": "clear_audio"})
