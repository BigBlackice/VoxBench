import torch


def join_audio_chunks(
    audio_chunks: list[torch.Tensor],
    sample_rate: int,
    pause_ms: float,
) -> torch.Tensor:
    """Join generated audio chunks with a fixed silence interval."""
    silence = torch.zeros(round(sample_rate * float(pause_ms) / 1000.0))
    joined: list[torch.Tensor] = []

    for index, audio_chunk in enumerate(audio_chunks):
        if index and silence.numel():
            joined.append(silence)
        joined.append(audio_chunk)

    return torch.cat(joined)
