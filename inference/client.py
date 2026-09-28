import base64
import io
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np
import soundfile as sf

from inference.contract import (
    API_VERSION,
    DEFAULT_SAMPLE_RATE,
    AudioResult,
    SynthesisRequest,
)


class InferenceError(RuntimeError):
    """Raised when an inference backend cannot complete a request."""


def _reference_payload(path_value: str | None) -> dict[str, str] | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_file():
        raise InferenceError("The reference-audio file could not be found.")
    return {
        "filename": path.name,
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _decode_audio(content: bytes) -> AudioResult:
    try:
        samples, sample_rate = sf.read(
            io.BytesIO(content),
            dtype="float32",
            always_2d=False,
        )
    except (RuntimeError, ValueError) as error:
        raise InferenceError("The inference backend returned invalid audio.") from error
    if samples.ndim > 1:
        samples = np.mean(samples, axis=1, dtype=np.float32)
    return AudioResult(int(sample_rate), np.asarray(samples, dtype=np.float32))


class _JsonHttpClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout: float = 600.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[bytes, str]:
        headers = {"Accept": "application/json, audio/wav"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read(), response.headers.get_content_type()
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except (json.JSONDecodeError, AttributeError):
                pass
            raise InferenceError(
                f"Inference endpoint returned HTTP {error.code}: {detail}"
            ) from error
        except (URLError, TimeoutError, OSError) as error:
            raise InferenceError(
                f"Could not connect to inference endpoint {self.base_url}: {error}"
            ) from error

    def _json(self, method: str, path: str) -> dict[str, Any]:
        content, _ = self._request(method, path)
        try:
            result = json.loads(content)
        except json.JSONDecodeError as error:
            raise InferenceError("Inference endpoint returned invalid JSON.") from error
        if not isinstance(result, dict):
            raise InferenceError("Inference endpoint returned an invalid response.")
        return result


class VoxBenchModelClient(_JsonHttpClient):
    """Client for a local or remote VoxBench model service."""

    def __init__(self, base_url: str, api_key: str = "", timeout: float = 600.0):
        super().__init__(base_url, api_key, timeout)
        self._capabilities: dict[str, Any] | None = None

    @property
    def label(self) -> str:
        return "VoxBench model service"

    @property
    def sample_rate(self) -> int:
        return int((self._capabilities or {}).get("sample_rate", DEFAULT_SAMPLE_RATE))

    def health(self) -> dict[str, Any]:
        return self._json("GET", f"/v{API_VERSION}/health")

    def capabilities(self) -> dict[str, Any]:
        if self._capabilities is None:
            result = self._json("GET", f"/v{API_VERSION}/capabilities")
            if str(result.get("api_version")) != API_VERSION:
                raise InferenceError("The model service API version is incompatible.")
            self._capabilities = result
        return dict(self._capabilities)

    def synthesize(self, request: SynthesisRequest) -> AudioResult:
        payload = {
            "api_version": API_VERSION,
            "text": request.text,
            "parameters": request.parameters(),
            "reference_audio": _reference_payload(request.audio_prompt_path),
        }
        content, content_type = self._request(
            "POST", f"/v{API_VERSION}/synthesize", payload
        )
        if not content_type.startswith("audio/"):
            raise InferenceError("The model service did not return audio.")
        return _decode_audio(content)


class GenericProviderClient(_JsonHttpClient):
    """Adapter for hosted TTS APIs accepting JSON and returning audio or base64."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        model: str = "",
        timeout: float = 600.0,
    ) -> None:
        super().__init__(endpoint, api_key, timeout)
        self.model = model

    @property
    def label(self) -> str:
        return "Hosted TTS provider"

    @property
    def sample_rate(self) -> int:
        return DEFAULT_SAMPLE_RATE

    def capabilities(self) -> dict[str, Any]:
        return {
            "api_version": API_VERSION,
            "backend": "provider",
            "model": self.model,
            "sample_rate": DEFAULT_SAMPLE_RATE,
            "reference_audio": True,
        }

    def synthesize(self, request: SynthesisRequest) -> AudioResult:
        payload = {
            "model": self.model,
            "text": request.text,
            "parameters": request.parameters(),
            "reference_audio": _reference_payload(request.audio_prompt_path),
        }
        content, content_type = self._request("POST", "", payload)
        if content_type.startswith("audio/"):
            return _decode_audio(content)
        try:
            response = json.loads(content)
            encoded = response["audio"]
            audio = base64.b64decode(encoded, validate=True)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise InferenceError(
                "The provider did not return raw audio or a base64 audio field."
            ) from error
        return _decode_audio(audio)


def create_inference_backend(
    *,
    mode: str = "service",
    service_url: str = "http://127.0.0.1:7861",
    service_api_key: str = "",
    timeout: float = 600.0,
    provider_url: str = "",
    provider_api_key: str = "",
    provider_model: str = "",
) -> VoxBenchModelClient | GenericProviderClient:
    """Build an inference client from application configuration, not env vars."""
    mode = mode.strip().lower()
    if mode == "provider":
        endpoint = provider_url.strip()
        if not endpoint:
            raise RuntimeError("A provider URL is required in provider mode.")
        return GenericProviderClient(
            endpoint=endpoint,
            api_key=provider_api_key,
            model=provider_model,
            timeout=timeout,
        )
    if mode != "service":
        raise RuntimeError("Inference mode must be service or provider.")
    return VoxBenchModelClient(
        base_url=service_url,
        api_key=service_api_key,
        timeout=timeout,
    )
