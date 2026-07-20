import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for audio streaming"""
    try:
        await websocket.accept()
        logger.info("WebSocket connection accepted")

        # Send initial status
        await websocket.send_json({
            "type": "status",
            "message": "Connected to audio WebSocket"
        })

        # Echo incoming messages
        while True:
            data = await websocket.receive_text()
            logger.debug(f"Received data: {data[:50]}...")

            # Echo the message back
            await websocket.send_json({
                "type": "echo",
                "data": data
            })

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except Exception:
            pass
