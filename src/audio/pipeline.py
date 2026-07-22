import av

from src.audio.codec import audio_frame_to_pcm_audio, pcm_audio_to_audio_frame
from src.audio.formats import (
    API_CHANNELS,
    API_SAMPLE_RATE,
    API_SAMPLE_WIDTH,
    CLIENT_CHANNELS,
    CLIENT_SAMPLE_RATE,
    CLIENT_SAMPLE_WIDTH,
    FORMAT_MAPPING,
    LAYOUT_MAPPING,
)


class AudioPipeline:
    """Owns the record/play FIFOs and the resamplers between client and API
    audio formats, plus the running count of samples sent to the client.
    """

    def __init__(self) -> None:
        self._resampler_for_api = av.audio.resampler.AudioResampler(
            format=FORMAT_MAPPING[API_SAMPLE_WIDTH],
            layout=LAYOUT_MAPPING[API_CHANNELS],
            rate=API_SAMPLE_RATE,
        )
        self._resampler_for_client = av.audio.resampler.AudioResampler(
            format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
            layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
            rate=CLIENT_SAMPLE_RATE,
        )
        self._record_stream = None
        self._play_stream = None
        self.played_samples = 0
        self.reset()

    def write_client_pcm(self, pcm_bytes: bytes) -> None:
        """Enqueue a client-format PCM frame for uplink to the API."""
        frame = pcm_audio_to_audio_frame(
            pcm_bytes,
            format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
            layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
            sample_rate=CLIENT_SAMPLE_RATE,
        )
        self._record_stream.write(frame)

    def next_api_pcm(self) -> bytes | None:
        """Drain one uplink frame, resampled to API format; None if empty."""
        frame = self._record_stream.read()
        if not frame:
            return None
        resampled, *rest = self._resampler_for_api.resample(frame)
        assert not rest
        return audio_frame_to_pcm_audio(resampled)

    def write_api_pcm(self, pcm_bytes: bytes) -> None:
        """Enqueue an API-format PCM frame for downlink, resampled to client."""
        frame = pcm_audio_to_audio_frame(
            pcm_bytes,
            format=FORMAT_MAPPING[API_SAMPLE_WIDTH],
            layout=LAYOUT_MAPPING[API_CHANNELS],
            sample_rate=API_SAMPLE_RATE,
        )
        resampled, *rest = self._resampler_for_client.resample(frame)
        assert not rest
        self._play_stream.write(resampled)

    def read_client_pcm(self, nsamples: int, partial: bool = True) -> bytes | None:
        """Drain up to nsamples of playback, counting what is sent; None if empty."""
        frame = self._play_stream.read(nsamples, partial=partial)
        if not frame:
            return None
        self.played_samples += frame.samples
        return audio_frame_to_pcm_audio(frame)

    def play_buffer_seconds(self) -> float:
        """Seconds of playback still buffered (used for the goodbye wait)."""
        return self._play_stream.samples / CLIENT_SAMPLE_RATE

    def reset_played(self) -> None:
        """Zero the played-samples counter (start of a new item/turn)."""
        self.played_samples = 0

    def reset(self) -> None:
        """Create the FIFOs if missing (does not empty existing buffers)."""
        if self._record_stream is None:
            self._record_stream = av.audio.fifo.AudioFifo(
                format=FORMAT_MAPPING[API_SAMPLE_WIDTH],
                layout=LAYOUT_MAPPING[API_CHANNELS],
            )
        if self._play_stream is None:
            self._play_stream = av.audio.fifo.AudioFifo(
                format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
                layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
            )

    def reset_play(self) -> None:
        """Force-recreate (empty) the play FIFO — drops buffered assistant audio."""
        self._play_stream = av.audio.fifo.AudioFifo(
            format=FORMAT_MAPPING[CLIENT_SAMPLE_WIDTH],
            layout=LAYOUT_MAPPING[CLIENT_CHANNELS],
        )
