from src.audio.formats import (
    CLIENT_CHANNELS,
    CLIENT_SAMPLE_RATE,
    CLIENT_SAMPLE_WIDTH,
)
from src.audio.pipeline import AudioPipeline


def _client_pcm(nsamples: int) -> bytes:
    """`nsamples` of silent client-format (48kHz stereo s16) PCM."""
    return b"\x00" * (nsamples * CLIENT_SAMPLE_WIDTH * CLIENT_CHANNELS)


def test_read_client_pcm_counts_samples():
    pipe = AudioPipeline()
    pipe.write_client_pcm(_client_pcm(480))
    # Client audio is resampled to API format for the record path, so we
    # instead exercise the play path used by read_client_pcm:
    pipe.write_api_pcm(b"\x00" * (240 * 2 * 1))  # 240 API-format samples
    assert pipe.played_samples == 0
    out = pipe.read_client_pcm(4096, partial=True)
    assert out is not None
    assert pipe.played_samples > 0


def test_reset_play_drops_buffered_audio():
    pipe = AudioPipeline()
    pipe.write_api_pcm(b"\x00" * (240 * 2 * 1))
    assert pipe.play_buffer_seconds() > 0
    pipe.reset_play()
    assert pipe.play_buffer_seconds() == 0


def test_reset_played_zeros_counter():
    pipe = AudioPipeline()
    pipe.played_samples = 5000
    pipe.reset_played()
    assert pipe.played_samples == 0
