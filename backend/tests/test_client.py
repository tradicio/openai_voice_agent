from src.realtime import OpenAIRealtimeAPIWrapper
from src.realtime.config import DEFAULT_MODEL, DEFAULT_VOICE


def _make():
    return OpenAIRealtimeAPIWrapper(api_key="test-key")


def test_defaults_for_model_and_voice():
    w = _make()
    assert w._model == DEFAULT_MODEL
    assert w._voice == DEFAULT_VOICE


def test_set_model_and_voice():
    w = _make()
    w.set_model("gpt-realtime")
    w.set_voice("verse")
    assert w._model == "gpt-realtime"
    assert w._voice == "verse"


def test_constructor_overrides():
    w = OpenAIRealtimeAPIWrapper(
        api_key="k", model="gpt-realtime", voice="coral"
    )
    assert w._model == "gpt-realtime"
    assert w._voice == "coral"


def test_timeout_api_removed():
    w = _make()
    assert not hasattr(w, "timer")
    assert not hasattr(w, "set_session_timeout")
    assert not hasattr(w, "_session_timeout")
