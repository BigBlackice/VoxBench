import os
import platform
import random
import secrets
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


def _configure_mps_environment() -> None:
    """Enable Apple Metal optimizations before PyTorch is imported."""
    if sys.platform == "darwin" and platform.machine().lower() == "arm64":
        os.environ.setdefault("PYTORCH_MPS_FAST_MATH", "1")
        os.environ.setdefault("PYTORCH_MPS_PREFER_METAL", "1")


_configure_mps_environment()

import torch
from chatterbox.tts_turbo import ChatterboxTurboTTS

from inference.contract import AudioResult, SynthesisRequest


REFERENCE_SESSION_IDLE_SECONDS = 30 * 60
MAX_REFERENCE_SESSIONS = 16


@dataclass
class _ReferenceSession:
    path: Path
    expires_at: float


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
        self._default_conditionals: Any = None
        self._prepared_reference_key: tuple[str, bool] | None = None
        self._reference_directory = tempfile.TemporaryDirectory(prefix="voxbench_model_")
        self._reference_sessions: dict[str, _ReferenceSession] = {}
        self._reference_lock = threading.Lock()

    def capabilities(self) -> dict[str, Any]:
        return {
            "backend": "chatterbox",
            "model": "chatterbox-nano",
            "device": self.device,
            "device_label": self.device_label,
            "sample_rate": 24_000,
            "reference_audio": True,
            "reference_sessions": True,
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
                    self._default_conditionals = self._model.conds
        return self._model

    def _prepare_reference_conditionals(
        self,
        model: ChatterboxTurboTTS,
        reference_audio: str | None,
        norm_loudness: bool,
    ) -> None:
        if not reference_audio:
            model.conds = self._default_conditionals
            self._prepared_reference_key = None
            return
        key = (str(Path(reference_audio).resolve()), norm_loudness)
        if key != self._prepared_reference_key:
            model.prepare_conditionals(reference_audio, norm_loudness=norm_loudness)
            self._prepared_reference_key = key

    def synthesize(self, request: SynthesisRequest) -> AudioResult:
        model = self._get_model()
        with self._generation_lock, torch.inference_mode():
            self._prepare_reference_conditionals(
                model, request.audio_prompt_path, request.norm_loudness
            )
            if request.seed:
                torch.manual_seed(request.seed)
                random.seed(request.seed)
                np.random.seed(request.seed)
            wav = model.generate(
                request.text,
                temperature=request.temperature,
                min_p=request.min_p,
                top_p=request.top_p,
                top_k=request.top_k,
                repetition_penalty=request.repetition_penalty,
                norm_loudness=request.norm_loudness,
            )
            samples = wav.squeeze(0).detach().cpu().float().numpy().copy()
            del wav
        return AudioResult(model.sr, samples)

    def save_reference(self, filename: str, content: bytes) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}:
            suffix = ".audio"
        with tempfile.NamedTemporaryFile(
            prefix="voxbench_reference_",
            suffix=suffix,
            delete=False,
            dir=self._reference_directory.name,
        ) as temporary:
            temporary.write(content)
            return temporary.name

    def _purge_expired_reference_sessions_locked(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, session in self._reference_sessions.items()
            if session.expires_at <= now
        ]
        for token in expired:
            session = self._reference_sessions.pop(token)
            session.path.unlink(missing_ok=True)

    def create_reference_session(self, filename: str, content: bytes) -> str:
        """Store one reference clip for a bounded, idle-expiring session."""
        with self._reference_lock:
            self._purge_expired_reference_sessions_locked()
            if len(self._reference_sessions) >= MAX_REFERENCE_SESSIONS:
                raise RuntimeError("The model service has reached its reference-session limit.")
            path = Path(self.save_reference(filename, content))
            token = secrets.token_urlsafe(32)
            self._reference_sessions[token] = _ReferenceSession(
                path=path,
                expires_at=time.monotonic() + REFERENCE_SESSION_IDLE_SECONDS,
            )
            return token

    def reference_for_session(self, token: str) -> str | None:
        """Resolve and refresh an active reference session without retaining audio in RAM."""
        with self._reference_lock:
            self._purge_expired_reference_sessions_locked()
            session = self._reference_sessions.get(token)
            if session is None or not session.path.is_file():
                return None
            session.expires_at = time.monotonic() + REFERENCE_SESSION_IDLE_SECONDS
            return str(session.path)

    def close_reference_session(self, token: str) -> None:
        with self._reference_lock:
            session = self._reference_sessions.pop(token, None)
            if session:
                session.path.unlink(missing_ok=True)

    def close(self) -> None:
        """Release reference-session files during a graceful model-service shutdown."""
        with self._reference_lock:
            for session in self._reference_sessions.values():
                session.path.unlink(missing_ok=True)
            self._reference_sessions.clear()
        self._prepared_reference_key = None
        self._reference_directory.cleanup()
