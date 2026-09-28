from dataclasses import asdict, dataclass
from typing import Any, Protocol

import numpy as np


API_VERSION = "1"
DEFAULT_SAMPLE_RATE = 24_000


@dataclass(frozen=True)
class SynthesisRequest:
    text: str
    audio_prompt_path: str | None = None
    temperature: float = 0.8
    seed: int = 0
    min_p: float = 0.0
    top_p: float = 0.95
    top_k: int = 1000
    repetition_penalty: float = 1.2
    norm_loudness: bool = True

    def parameters(self) -> dict[str, Any]:
        values = asdict(self)
        values.pop("text")
        values.pop("audio_prompt_path")
        return values


@dataclass(frozen=True)
class AudioResult:
    sample_rate: int
    samples: np.ndarray


class InferenceBackend(Protocol):
    @property
    def label(self) -> str: ...

    @property
    def sample_rate(self) -> int: ...

    def capabilities(self) -> dict[str, Any]: ...

    def synthesize(self, request: SynthesisRequest) -> AudioResult: ...
