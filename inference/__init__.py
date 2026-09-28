"""UI-independent inference clients and shared request types."""

from inference.client import (
    GenericProviderClient,
    InferenceError,
    VoxBenchModelClient,
    create_inference_backend,
)
from inference.contract import AudioResult, SynthesisRequest

__all__ = [
    "AudioResult",
    "GenericProviderClient",
    "InferenceError",
    "SynthesisRequest",
    "VoxBenchModelClient",
    "create_inference_backend",
]
