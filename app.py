"""Run the VoxBench NiceGUI application.

The app process owns uploads, documents, audio files, and FFmpeg.  It connects
to the model service through the framework-independent inference interface.
"""

import os
import shutil

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from nicegui import app, ui
from starlette.middleware.sessions import SessionMiddleware

from webui.auth import (
    SharedAuthMiddleware,
    authenticate_login,
    load_auth_settings,
    login_page,
)
from webui.config import MODEL_CACHE_DIR, OUTPUTS_DIR, PROJECT_DIR
from webui.app_config import ModelConnection, ModelConnectionSettings
from webui.document_workspace import document_source_path
from webui.errors import VoxBenchError
from webui.nicegui_interface import build_interface
from webui.themes import themed_styles


os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR))

AUTH_SETTINGS = load_auth_settings()
SHARED_LOCAL_MODE = os.getenv("VOXBENCH_SHARED_LOCAL_MODE") == "1"
MODEL_CONNECTION = ModelConnection(
    ModelConnectionSettings() if SHARED_LOCAL_MODE else None
)
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

if AUTH_SETTINGS.enabled:
    app.add_middleware(SharedAuthMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=AUTH_SETTINGS.session_secret,
        session_cookie="voxbench_session",
        same_site="lax",
        https_only=AUTH_SETTINGS.cookie_secure,
        max_age=60 * 60 * 24 * 30,
    )


@app.get("/login", include_in_schema=False)
def show_login(next: str = "/"):
    if not AUTH_SETTINGS.enabled:
        return RedirectResponse("/")
    return login_page(next)


@app.post("/login", include_in_schema=False)
async def submit_login(request: Request):
    if not AUTH_SETTINGS.enabled:
        return RedirectResponse("/")
    return await authenticate_login(request, AUTH_SETTINGS)


@app.get("/logout", include_in_schema=False)
def logout(request: Request):
    if AUTH_SETTINGS.enabled:
        request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/document-source/{document_id}", include_in_schema=False)
def serve_document_source(document_id: str) -> FileResponse:
    try:
        path = document_source_path(document_id)
    except (FileNotFoundError, VoxBenchError) as error:
        raise HTTPException(status_code=404) from error
    return FileResponse(path)


OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
app.add_static_files("/outputs", OUTPUTS_DIR, max_cache_age=0)
app.add_static_files("/static", PROJECT_DIR / "webui" / "static")


@ui.page("/")
def index() -> None:
    ui.add_head_html(
        f'<link rel="icon" type="image/png" href="/static/favicon.png">'
        f"<style>{themed_styles()}</style>"
    )
    ui.dark_mode().enable()
    build_interface(
        model_connection=MODEL_CONNECTION,
        ffmpeg_path=FFMPEG_PATH,
        ffprobe_path=FFPROBE_PATH,
    )


def main() -> None:
    ui.run(
        host=AUTH_SETTINGS.host,
        port=AUTH_SETTINGS.port,
        title="VoxBench",
        show=False,
        reload=False,
    )


if __name__ == "__main__":
    main()
