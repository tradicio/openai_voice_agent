import asyncio
import websockets
import json
import base64

async def test_conversation():
    uri = "ws://localhost:8000/ws/audio"
    async with websockets.connect(uri) as websocket:
        # Configure
        await websocket.send(json.dumps({
            "type": "config",
            "timeout": 120,
            "prompt_key": "default"
        }))
        response = await websocket.recv()
        print(f"Config response: {response}")

        # Start
        await websocket.send(json.dumps({
            "type": "control",
            "action": "start"
        }))
        response = await websocket.recv()
        print(f"Start response: {response}")

        # Send audio frame
        dummy_audio = base64.b64encode(b"\x00" * 100).decode()
        await websocket.send(json.dumps({
            "type": "audio",
            "data": dummy_audio
        }))

        # Stop
        await websocket.send(json.dumps({
            "type": "control",
            "action": "stop"
        }))
        response = await websocket.recv()
        print(f"Stop response: {response}")

asyncio.run(test_conversation())
