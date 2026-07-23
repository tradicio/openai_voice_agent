import logging
import os

from fastapi import WebSocket

from api.ws.session import AudioStreamSession

logger = logging.getLogger(__name__)


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
