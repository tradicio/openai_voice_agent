
from src.audio.audio_utils import pcm_audio_to_audio_frame
from src.realtime.config import (
    CLIENT_CHANNELS,
    CLIENT_SAMPLE_RATE,
    CLIENT_SAMPLE_WIDTH,
    FORMAT_MAPPING,
    LAYOUT_MAPPING,
)
from src.realtime.realtime_client import (
    OpenAIRealtimeAPIWrapper,
)


def _client_frame(nsamples: int):
    """Build `nsamples` of silent client-format (48kHz stereo s16) audio."""
    pcm = b"\x00" * (nsamples * CLIENT_SAMPLE_WIDTH * CLIENT_CHANNELS)
    return pcm_audio_to_audio_frame(
        pcm,
        format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
        layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
        sample_rate=CLIENT_SAMPLE_RATE,
    )


def test_read_play_audio_counts_samples():
    wrapper = OpenAIRealtimeAPIWrapper(api_key="test-key")
    wrapper.reset_stream()
    wrapper._play_stream.write(_client_frame(480))

    assert wrapper._played_samples == 0
    out = wrapper.read_play_audio(480, partial=True)
    assert out is not None
    assert wrapper._played_samples == 480
