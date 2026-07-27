import os
import shutil
import threading
import webbrowser

from webui.config import MODEL_CACHE_DIR, PROJECT_DIR


# Set the cache location before importing PyTorch, Gradio, or Hugging Face.
os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR))

import torch
import uvicorn
import gradio as gr
from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse


def detect_device() -> tuple[str, str]:
    """Choose the best accelerator exposed by the installed PyTorch build."""
    if torch.cuda.is_available():
        if getattr(torch.version, "hip", None):
            return "cuda", "AMD ROCm"
        return "cuda", "NVIDIA CUDA"

    mps_backend = getattr(torch.backends, "mps", None)
    if mps_backend is not None and mps_backend.is_available():
        return "mps", "Apple Metal (MPS)"

    return "cpu", "CPU"


DEVICE, DEVICE_LABEL = detect_device()
FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")

from webui.assembly_interface import build_assembly_interface
from webui.document_interface import build_document_interface
from webui.document_workspace import document_source_path
from webui.interface import build_interface


MODEL_CACHE = {
    "model": None,
    "load_lock": threading.Lock(),
    "generation_lock": threading.Lock(),
}

demo, CUSTOM_CSS = build_interface(
    DEVICE,
    DEVICE_LABEL,
    FFMPEG_PATH,
    MODEL_CACHE,
)
assembly_demo, ASSEMBLY_CSS = build_assembly_interface(
    FFMPEG_PATH,
    FFPROBE_PATH,
)
document_demo, DOCUMENT_CSS = build_document_interface(
    DEVICE,
    DEVICE_LABEL,
    MODEL_CACHE,
)

demo.queue(max_size=10, default_concurrency_limit=1)
assembly_demo.queue(max_size=10, default_concurrency_limit=1)
document_demo.queue(max_size=10, default_concurrency_limit=1)

web_app = FastAPI()


@web_app.get("/assemble", include_in_schema=False)
def redirect_to_assembly() -> RedirectResponse:
    return RedirectResponse("/assemble/")


@web_app.get("/doc", include_in_schema=False)
def redirect_to_documents() -> RedirectResponse:
    return RedirectResponse("/doc/")


@web_app.get("/document-source/{document_id}", include_in_schema=False)
def serve_document_source(document_id: str) -> FileResponse:
    try:
        path = document_source_path(document_id)
    except (FileNotFoundError, gr.Error):
        from fastapi import HTTPException

        raise HTTPException(status_code=404)
    return FileResponse(path)


web_app = gr.mount_gradio_app(
    web_app,
    document_demo,
    path="/doc",
    server_name="127.0.0.1",
    server_port=7860,
    css=DOCUMENT_CSS,
    allowed_paths=[str(PROJECT_DIR)],
)
web_app = gr.mount_gradio_app(
    web_app,
    assembly_demo,
    path="/assemble",
    server_name="127.0.0.1",
    server_port=7860,
    css=ASSEMBLY_CSS,
    allowed_paths=[str(PROJECT_DIR)],
)
web_app = gr.mount_gradio_app(
    web_app,
    demo,
    path="/",
    server_name="127.0.0.1",
    server_port=7860,
    css=CUSTOM_CSS,
    allowed_paths=[str(PROJECT_DIR)],
)


def main() -> None:
    threading.Timer(
        1.0,
        lambda: webbrowser.open("http://127.0.0.1:7860"),
    ).start()
    uvicorn.run(
        web_app,
        host="127.0.0.1",
        port=7860,
    )


if __name__ == "__main__":
    main()
