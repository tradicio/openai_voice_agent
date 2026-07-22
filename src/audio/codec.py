import av
import numpy as np


def audio_frame_to_pcm_audio(frame: av.AudioFrame) -> bytes:
    return frame.to_ndarray().tobytes()


def pcm_audio_to_audio_frame(
    pcm_audio: bytes,
    *,
    format: str,
    layout: str,
    sample_rate: int
) -> av.AudioFrame:
    raw_data = np.frombuffer(pcm_audio, np.int16).reshape(1, -1)
    frame = av.AudioFrame.from_ndarray(raw_data, format=format, layout=layout)
    frame.sample_rate = sample_rate
    return frame
