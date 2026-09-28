"""Compatibility helpers that route UI synthesis through an inference backend."""

from inference.client import create_inference_backend
from inference.contract import AudioResult, InferenceBackend, SynthesisRequest


def load_model(device: str = "", device_label: str = "") -> InferenceBackend:
    """Return the configured service/provider client; no model loads in the app."""
    return create_inference_backend()


def generate_audio_chunk(
    model: InferenceBackend,
    text: str,
    audio_prompt_path: str | None,
    temperature: float,
    min_p: float,
    top_p: float,
    top_k: int,
    repetition_penalty: float,
    norm_loudness: bool,
    seed: int = 0,
) -> AudioResult:
    return model.synthesize(
        SynthesisRequest(
            text=text,
            audio_prompt_path=audio_prompt_path,
            temperature=temperature,
            seed=seed,
            min_p=min_p,
            top_p=top_p,
            top_k=top_k,
            repetition_penalty=repetition_penalty,
            norm_loudness=norm_loudness,
        )
    )
