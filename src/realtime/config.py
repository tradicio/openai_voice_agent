from src.audio.formats import API_SAMPLE_RATE
from src.realtime.tools import TOOL_DEFINITIONS

# Selectable realtime models (single source of truth; served by the API and
# used to validate client-requested values).
MODELS = [
    {"key": "gpt-realtime-2", "label": "GPT Realtime 2"},
    {"key": "gpt-realtime", "label": "GPT Realtime"},
]
DEFAULT_MODEL = "gpt-realtime-2"

# Selectable assistant voices.
VOICES = [
    {"key": "alloy", "label": "Alloy"},
    {"key": "ash", "label": "Ash"},
    {"key": "ballad", "label": "Ballad"},
    {"key": "coral", "label": "Coral"},
    {"key": "echo", "label": "Echo"},
    {"key": "sage", "label": "Sage"},
    {"key": "shimmer", "label": "Shimmer"},
    {"key": "verse", "label": "Verse"},
    {"key": "marin", "label": "Marin"},
    {"key": "cedar", "label": "Cedar"},
]
DEFAULT_VOICE = "alloy"

MODEL_KEYS = {m["key"] for m in MODELS}
VOICE_KEYS = {v["key"] for v in VOICES}

# Extra headers for the Realtime API handshake (none required today).
REALTIME_API_HEADERS = {}


def build_realtime_url(model: str = DEFAULT_MODEL) -> str:
    """Build the Realtime API WebSocket URL for the given model.

    Parameters
    ----------
    model : str
        The realtime model key (e.g. ``"gpt-realtime-2"``).

    Returns
    -------
    str
        The full ``wss://`` URL including the ``model`` query parameter.
    """
    return f"wss://api.openai.com/v1/realtime?model={model}"


# Backward-compat: ``client.py`` still imports this default URL until Task 2
# migrates it to ``build_realtime_url(self._model)``. Remove in Task 2.
REALTIME_API_URL = build_realtime_url()


def build_api_config(voice: str = DEFAULT_VOICE) -> dict:
    """Build a fresh Realtime session config with the given output voice.

    A new dict (including nested dicts) is returned on every call so callers
    can safely inject per-session values without mutating shared state.

    Parameters
    ----------
    voice : str
        The output voice key (e.g. ``"alloy"``).

    Returns
    -------
    dict
        The ``session`` config payload minus ``instructions``.
    """
    return dict(
        type='realtime',
        output_modalities=['audio'],
        audio=dict(
            input=dict(
                format=dict(type='audio/pcm', rate=API_SAMPLE_RATE),
                transcription=dict(
                    model='gpt-4o-transcribe',
                ),
                turn_detection=dict(
                    type='server_vad',
                    interrupt_response=True,
                    threshold=0.5,
                    prefix_padding_ms=100,
                    silence_duration_ms=800,
                ),
            ),
            output=dict(
                format=dict(type='audio/pcm', rate=API_SAMPLE_RATE),
                voice=voice,
            ),
        ),
        tools=TOOL_DEFINITIONS,
        tool_choice='auto',
    )


def build_session_update(
    instructions: str, voice: str = DEFAULT_VOICE
) -> dict:
    """Build the ``session.update`` payload with instructions and voice.

    Parameters
    ----------
    instructions : str
        The assistant system prompt.
    voice : str
        The output voice key.

    Returns
    -------
    dict
        A ready-to-send ``session.update`` message.
    """
    return dict(
        type='session.update',
        session=dict(build_api_config(voice), instructions=instructions),
    )
