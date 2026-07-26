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
from fastapi.responses import RedirectResponse


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
from webui.interface import build_interface


demo, CUSTOM_CSS = build_interface(DEVICE, DEVICE_LABEL, FFMPEG_PATH)
assembly_demo, ASSEMBLY_CSS = build_assembly_interface(
    FFMPEG_PATH,
    FFPROBE_PATH,
)

demo.queue(max_size=10, default_concurrency_limit=1)
assembly_demo.queue(max_size=10, default_concurrency_limit=1)

web_app = FastAPI()


@web_app.get("/assemble", include_in_schema=False)
def redirect_to_assembly() -> RedirectResponse:
    return RedirectResponse("/assemble/")


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
