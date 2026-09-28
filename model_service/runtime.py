import random
import tempfile
import threading
from typing import Any

import numpy as np
import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS

from inference.contract import AudioResult, SynthesisRequest


def detect_device() -> tuple[str, str]:
    if torch.cuda.is_available():
        if getattr(torch.version, "hip", None):
            return "cuda", "AMD ROCm"
        return "cuda", "NVIDIA CUDA"
    mps_backend = getattr(torch.backends, "mps", None)
    if mps_backend is not None and mps_backend.is_available():
        return "mps", "Apple Metal (MPS)"
    return "cpu", "CPU"


class ChatterboxRuntime:
    """Lazy, serialized access to one Chatterbox Nano model."""

    def __init__(self) -> None:
        self.device, self.device_label = detect_device()
        self._model: ChatterboxTurboTTS | None = None
        self._load_lock = threading.Lock()
        self._generation_lock = threading.Lock()

    def capabilities(self) -> dict[str, Any]:
        return {
            "backend": "chatterbox",
            "model": "chatterbox-nano",
            "device": self.device,
            "device_label": self.device_label,
            "sample_rate": 24_000,
            "reference_audio": True,
            "parameters": [
                "temperature",
                "seed",
                "min_p",
                "top_p",
                "top_k",
                "repetition_penalty",
                "norm_loudness",
            ],
        }

    def _get_model(self) -> ChatterboxTurboTTS:
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    print(
                        "Loading Chatterbox-Nano with "
                        f"{self.device_label} ({self.device})..."
                    )
                    self._model = ChatterboxTurboTTS.from_pretrained(
                        device=self.device,
                        nano=True,
                    )
        return self._model

    def synthesize(self, request: SynthesisRequest) -> AudioResult:
        model = self._get_model()
        with self._generation_lock:
            if request.seed:
                torch.manual_seed(request.seed)
                random.seed(request.seed)
                np.random.seed(request.seed)
            wav = model.generate(
                request.text,
                audio_prompt_path=request.audio_prompt_path,
                temperature=request.temperature,
                min_p=request.min_p,
                top_p=request.top_p,
                top_k=request.top_k,
                repetition_penalty=request.repetition_penalty,
                norm_loudness=request.norm_loudness,
            )
            samples = wav.squeeze(0).detach().cpu().float().numpy()
        return AudioResult(model.sr, samples)

    def save_reference(self, filename: str, content: bytes) -> str:
        from pathlib import Path

        suffix = Path(filename).suffix.lower()
        if suffix not in {".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}:
            suffix = ".audio"
        with tempfile.NamedTemporaryFile(
            prefix="voxbench_reference_",
            suffix=suffix,
            delete=False,
        ) as temporary:
            temporary.write(content)
            return temporary.name
