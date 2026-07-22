from src.audio.formats import API_SAMPLE_RATE
from src.realtime.tools import TOOL_DEFINITIONS


# Configuration for calling Realtime API
REALTIME_API_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-2"
REALTIME_API_HEADERS = {}
REALTIME_API_CONFIG = dict(
    type = 'realtime',
    output_modalities = ['audio'],
    audio = dict(
        input = dict(
            format = dict(type = 'audio/pcm', rate = API_SAMPLE_RATE),
            transcription = dict(
                model = 'gpt-4o-transcribe',
            ),
            turn_detection = dict(
                type = 'server_vad',
                interrupt_response = True,
                threshold = 0.5,
                prefix_padding_ms = 100,
                silence_duration_ms = 800,
            ),
        ),
        output = dict(
            format = dict(type = 'audio/pcm', rate = API_SAMPLE_RATE),
            voice = 'alloy',
        ),
    ),
    tools = TOOL_DEFINITIONS,
    tool_choice = 'auto',
)
