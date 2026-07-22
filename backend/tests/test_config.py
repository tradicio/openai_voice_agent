from src.realtime.config import (
    DEFAULT_MODEL,
    DEFAULT_VOICE,
    MODEL_KEYS,
    MODELS,
    VOICE_KEYS,
    VOICES,
    build_api_config,
    build_realtime_url,
    build_session_update,
)


def test_defaults_are_in_allowlists():
    assert DEFAULT_MODEL in MODEL_KEYS
    assert DEFAULT_VOICE in VOICE_KEYS


def test_models_and_voices_shape():
    assert {"gpt-realtime-2", "gpt-realtime"} == MODEL_KEYS
    assert len(VOICES) == 10
    assert "cedar" in VOICE_KEYS
    for item in [*MODELS, *VOICES]:
        assert set(item) == {"key", "label"}


def test_build_realtime_url_uses_model():
    assert build_realtime_url("gpt-realtime") == (
        "wss://api.openai.com/v1/realtime?model=gpt-realtime"
    )
    assert build_realtime_url() == (
        "wss://api.openai.com/v1/realtime?model=gpt-realtime-2"
    )


def test_build_api_config_injects_voice_without_shared_mutation():
    a = build_api_config("verse")
    b = build_api_config("coral")
    assert a["audio"]["output"]["voice"] == "verse"
    assert b["audio"]["output"]["voice"] == "coral"
    # Distinct nested dicts, not a shared/mutated module-level object.
    assert a["audio"]["output"] is not b["audio"]["output"]


def test_build_session_update_carries_voice_and_instructions():
    payload = build_session_update("be nice", voice="sage")
    assert payload["type"] == "session.update"
    assert payload["session"]["instructions"] == "be nice"
    assert payload["session"]["audio"]["output"]["voice"] == "sage"
