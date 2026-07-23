import random

import numpy as np
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)


def load_model(device: str, device_label: str) -> ChatterboxTurboTTS:
    print(f"Loading Chatterbox-Nano with {device_label} ({device})...")
    return ChatterboxTurboTTS.from_pretrained(device=device, nano=True)


def generate_audio_chunk(
    model: ChatterboxTurboTTS,
    text: str,
    audio_prompt_path: str | None,
    temperature: float,
    min_p: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
    norm_loudness: bool,
) -> torch.Tensor:
    wav = model.generate(
        text,
        audio_prompt_path=audio_prompt_path,
        temperature=temperature,
        min_p=min_p,
        top_p=top_p,
        top_k=top_k,
        repetition_penalty=repetition_penalty,
        norm_loudness=norm_loudness,
    )
    return wav.squeeze(0).detach().cpu().float()
