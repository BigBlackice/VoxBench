import numpy as np


def join_audio_chunks(
    audio_chunks: list[np.ndarray],
    sample_rate: int,
    pause_ms: float,
) -> np.ndarray:
    """Join generated audio chunks with a fixed silence interval."""
    if not audio_chunks:
        return np.empty(0, dtype=np.float32)
    silence = np.zeros(round(sample_rate * float(pause_ms) / 1000.0), dtype=np.float32)
    joined: list[np.ndarray] = []
    for index, audio_chunk in enumerate(audio_chunks):
        if index and silence.size:
            joined.append(silence)
        joined.append(np.asarray(audio_chunk, dtype=np.float32))
    return np.concatenate(joined)
