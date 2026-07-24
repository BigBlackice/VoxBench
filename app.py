import os

from webui.config import MODEL_CACHE_DIR, PROJECT_DIR


# Set the cache location before importing PyTorch, Gradio, or Hugging Face.
os.environ.setdefault("HF_HOME", str(MODEL_CACHE_DIR))

import torch


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

from webui.interface import build_interface


demo, CUSTOM_CSS = build_interface(DEVICE, DEVICE_LABEL)


def main() -> None:
    demo.queue(max_size=10, default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        inbrowser=True,
        share=False,
        css=CUSTOM_CSS,
        allowed_paths=[str(PROJECT_DIR)],
    )


if __name__ == "__main__":
    main()
