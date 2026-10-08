import base64
import hmac
import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import soundfile as sf
import uvicorn

from inference.contract import API_VERSION, SynthesisRequest
from app_logic.logging_setup import build_log_config
from webui.config import MODEL_CACHE_DIR


load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR))

from model_service.runtime import ChatterboxRuntime


class ReferenceAudio(BaseModel):
    filename: str
    data: str = Field(max_length=70_000_000)


class SynthesisPayload(BaseModel):
    api_version: str
    text: str = Field(min_length=1, max_length=10_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    reference_audio: ReferenceAudio | None = None
    reference_session: str | None = Field(default=None, min_length=16, max_length=128)


MODEL_API_KEY = os.getenv("VOXBENCH_MODEL_API_KEY", "")
runtime = ChatterboxRuntime()


@asynccontextmanager
async def lifespan(_application: FastAPI):
    yield
    runtime.close()


model_app = FastAPI(title="VoxBench Model Service", version=API_VERSION, lifespan=lifespan)


def require_api_key(authorization: str | None = Header(default=None)) -> None:
    expected = f"Bearer {MODEL_API_KEY}"
    if MODEL_API_KEY and not hmac.compare_digest(authorization or "", expected):
        raise HTTPException(status_code=401, detail="Invalid model-service API key.")


def decode_reference_audio(reference: ReferenceAudio) -> bytes:
    try:
        return base64.b64decode(reference.data, validate=True)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Invalid reference audio.") from error


@model_app.get(f"/v{API_VERSION}/health", dependencies=[])
def health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_api_key(authorization)
    return {"status": "ok", "api_version": API_VERSION}


@model_app.get(f"/v{API_VERSION}/capabilities", dependencies=[])
def capabilities(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    require_api_key(authorization)
    return {"api_version": API_VERSION, **runtime.capabilities()}


@model_app.post(f"/v{API_VERSION}/reference-sessions", dependencies=[])
def create_reference_session(
    reference: ReferenceAudio,
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    require_api_key(authorization)
    try:
        session_id = runtime.create_reference_session(
            reference.filename,
            decode_reference_audio(reference),
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"id": session_id}


@model_app.delete(f"/v{API_VERSION}/reference-sessions/{{session_id}}", dependencies=[])
def delete_reference_session(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> Response:
    require_api_key(authorization)
    runtime.close_reference_session(session_id)
    return Response(status_code=204)


@model_app.post(f"/v{API_VERSION}/synthesize", dependencies=[])
def synthesize(
    payload: SynthesisPayload,
    authorization: str | None = Header(default=None),
) -> Response:
    require_api_key(authorization)
    if payload.api_version != API_VERSION:
        raise HTTPException(status_code=409, detail="Incompatible API version.")
    if payload.reference_audio and payload.reference_session:
        raise HTTPException(
            status_code=400,
            detail="Provide reference audio or a reference session, not both.",
        )
    reference_path = None
    temporary_reference = False
    if payload.reference_audio:
        reference_path = runtime.save_reference(
            payload.reference_audio.filename,
            decode_reference_audio(payload.reference_audio),
        )
        temporary_reference = True
    elif payload.reference_session:
        reference_path = runtime.reference_for_session(payload.reference_session)
        if reference_path is None:
            raise HTTPException(status_code=404, detail="Reference session was not found or expired.")
    try:
        request = SynthesisRequest(
            text=payload.text,
            audio_prompt_path=reference_path,
            **payload.parameters,
        )
        result = runtime.synthesize(request)
        output = io.BytesIO()
        sf.write(output, result.samples, result.sample_rate, format="WAV", subtype="FLOAT")
        return Response(output.getvalue(), media_type="audio/wav")
    except TypeError as error:
        raise HTTPException(status_code=400, detail="Invalid synthesis parameters.") from error
    finally:
        if temporary_reference and reference_path:
            Path(reference_path).unlink(missing_ok=True)


def main() -> None:
    host = os.getenv("VOXBENCH_MODEL_HOST", "127.0.0.1")
    port = int(os.getenv("VOXBENCH_MODEL_PORT", "7861"))
    if host not in {"127.0.0.1", "localhost", "::1"} and not MODEL_API_KEY:
        raise RuntimeError(
            "VOXBENCH_MODEL_API_KEY is required when the model service is "
            "bound beyond the local machine."
        )
    uvicorn.run(
        model_app,
        host=host,
        port=port,
        log_config=build_log_config(Path(__file__).resolve().parent, "model"),
    )


if __name__ == "__main__":
    main()
