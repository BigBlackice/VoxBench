"""Persistent, user-editable application configuration."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from inference import GenericProviderClient, VoxBenchModelClient, create_inference_backend
from webui.config import PROJECT_DIR
from webui.errors import VoxBenchError


CONFIG_PATH = PROJECT_DIR / "voxbench.json"
CONNECTION_TYPES = ("service", "provider")
SECRET_FIELD_MASK = "••••••••"


@dataclass(frozen=True)
class ModelConnectionSettings:
    """Connection details owned by the application, never the model service."""

    connection_type: str = "service"
    service_url: str = "http://127.0.0.1:7861"
    service_api_key: str = ""
    timeout_seconds: float = 600.0
    provider_url: str = ""
    provider_api_key: str = ""
    provider_model: str = ""

    def validate(self) -> "ModelConnectionSettings":
        if self.connection_type not in CONNECTION_TYPES:
            raise VoxBenchError("Connection type must be a VoxBench service or provider API.")
        if not self.service_url.strip():
            raise VoxBenchError("Enter a VoxBench model-service URL.")
        if self.timeout_seconds <= 0:
            raise VoxBenchError("Request timeout must be greater than zero.")
        if self.connection_type == "provider" and not self.provider_url.strip():
            raise VoxBenchError("Enter a provider API URL.")
        return self


def masked_secret(value: str) -> str:
    """Return a UI-safe marker without sending a configured secret to the client."""
    return SECRET_FIELD_MASK if value else ""


def updated_secret(value: str | None, existing: str) -> str:
    """Keep a stored secret unless the settings form receives a new value."""
    value = value or ""
    return value or existing


def load_model_connection(path: Path = CONFIG_PATH) -> ModelConnectionSettings:
    """Load the project-local connection config, creating safe defaults once."""
    if not path.exists():
        settings = ModelConnectionSettings()
        save_model_connection(settings, path)
        return settings
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        settings = ModelConnectionSettings(**data.get("model_connection", {}))
        return settings.validate()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read {path.name}: {error}") from error


def save_model_connection(
    settings: ModelConnectionSettings,
    path: Path = CONFIG_PATH,
) -> None:
    settings.validate()
    payload = {"model_connection": asdict(settings)}
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def backend_for(settings: ModelConnectionSettings) -> VoxBenchModelClient | GenericProviderClient:
    settings.validate()
    return create_inference_backend(
        mode=settings.connection_type,
        service_url=settings.service_url,
        service_api_key=settings.service_api_key,
        timeout=settings.timeout_seconds,
        provider_url=settings.provider_url,
        provider_api_key=settings.provider_api_key,
        provider_model=settings.provider_model,
    )


class ModelConnection:
    """Keeps the active backend aligned with the persisted config."""

    def __init__(self, settings: ModelConnectionSettings | None = None) -> None:
        self.settings = settings or load_model_connection()
        self.backend = backend_for(self.settings)

    def update(self, settings: ModelConnectionSettings) -> None:
        settings.validate()
        self.backend = backend_for(settings)
        self.settings = settings
        save_model_connection(settings)
