import os
import random
import re
from pathlib import Path

# Keep downloaded model files inside this project instead of the user profile.
PROJECT_DIR = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(PROJECT_DIR / ".cache" / "huggingface"))

import gradio as gr
import numpy as np
import torch

from chatterbox.tts_turbo import ChatterboxTurboTTS


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
EVENT_TAGS = [
    "[clear throat]",
    "[sigh]",
    "[shush]",
    "[cough]",
    "[groan]",
    "[sniff]",
    "[gasp]",
    "[chuckle]",
    "[laugh]",
]

CUSTOM_CSS = """
.tag-container {
    display: flex !important;
    flex-wrap: wrap !important;
    gap: 8px !important;
    margin: 5px 0 10px !important;
    border: none !important;
    background: transparent !important;
}
.tag-btn {
    min-width: fit-content !important;
    width: auto !important;
    height: 32px !important;
    font-size: 13px !important;
    background: #eef2ff !important;
    border: 1px solid #c7d2fe !important;
    color: #3730a3 !important;
    border-radius: 6px !important;
    padding: 0 10px !important;
    margin: 0 !important;
    box-shadow: none !important;
}
.tag-btn:hover {
    background: #c7d2fe !important;
    transform: translateY(-1px);
}
#generated_audio .timestamps {
    margin-top: 8px !important;
}
"""

INSERT_TAG_JS = """
(tag, currentText) => {
    const textarea = document.querySelector('#main_textbox textarea');
    if (!textarea) return currentText + ' ' + tag;
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const prefix = start === 0 || currentText[start - 1] === ' ' ? '' : ' ';
    const suffix = end >= currentText.length || currentText[end] === ' ' ? '' : ' ';
    return currentText.slice(0, start) + prefix + tag + suffix + currentText.slice(end);
}
"""


def set_seed(seed: int) -> None:
    torch.manual_seed(seed)
    random.seed(seed)
    np.random.seed(seed)


def load_model():
    print(f"Loading Chatterbox-Nano with {DEVICE_LABEL} ({DEVICE})...")
    return ChatterboxTurboTTS.from_pretrained(device=DEVICE, nano=True)


def split_text(text: str, max_chars: int) -> list[str]:
    """Split text at paragraph/sentence boundaries, then at words if necessary."""
    text = re.sub(r"[ \t]+", " ", text.strip())
    if not text:
        return []

    units = re.split(r"(?<=[.!?])\s+|\n+", text)
    chunks: list[str] = []
    current = ""

    for unit in filter(None, (part.strip() for part in units)):
        words = unit.split()
        pieces: list[str] = []
        piece = ""

        for word in words:
            if len(word) > max_chars:
                if piece:
                    pieces.append(piece)
                    piece = ""
                pieces.extend(word[i : i + max_chars] for i in range(0, len(word), max_chars))
            elif not piece or len(piece) + 1 + len(word) <= max_chars:
                piece = word if not piece else f"{piece} {word}"
            else:
                pieces.append(piece)
                piece = word

        if piece:
            pieces.append(piece)

        for part in pieces:
            candidate = part if not current else f"{current} {part}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = part

    if current:
        chunks.append(current)
    return chunks


def load_text_file(file_path: str | None) -> str:
    """Read a dropped text file and return its contents for the prompt textbox."""
    if not file_path:
        return ""

    path = Path(file_path)
    if path.suffix.lower() not in {".txt", ".text", ".md"}:
        raise gr.Error("Please upload a .txt, .text, or .md file.")

    data = path.read_bytes()
    if len(data) > 5 * 1024 * 1024:
        raise gr.Error("Text files must be 5 MB or smaller.")

    encodings = ["utf-8-sig"]
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.append("utf-16")
    encodings.append("cp1252")

    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise gr.Error("The text file encoding could not be recognized.")


def generate(
    model,
    text,
    audio_prompt_path,
    temperature,
    seed_num,
    min_p,
    top_p,
    top_k,
    repetition_penalty,
    norm_loudness,
    max_chunk_chars,
    pause_ms,
    progress=gr.Progress(),
):
    if not text or not text.strip():
        raise gr.Error("Enter some text to synthesize.")

    if model is None:
        model = load_model()

    if seed_num:
        set_seed(int(seed_num))

    chunks = split_text(text, int(max_chunk_chars))
    generated = []
    silence = None

    for index, chunk in enumerate(chunks, start=1):
        progress((index - 1) / len(chunks), desc=f"Generating chunk {index} of {len(chunks)}")
        wav = model.generate(
            chunk,
            audio_prompt_path=audio_prompt_path,
            temperature=temperature,
            min_p=min_p,
            top_p=top_p,
            top_k=int(top_k),
            repetition_penalty=repetition_penalty,
            norm_loudness=norm_loudness,
        )
        audio_chunk = wav.squeeze(0).detach().cpu().float()
        generated.append(audio_chunk)
        if silence is None:
            silence = torch.zeros(round(model.sr * float(pause_ms) / 1000.0))

    progress(1.0, desc="Joining audio")
    joined = []
    for index, audio_chunk in enumerate(generated):
        if index and silence is not None and silence.numel():
            joined.append(silence)
        joined.append(audio_chunk)
    audio = torch.cat(joined).numpy()
    return model, (model.sr, audio)


with gr.Blocks(title=f"Chatterbox Nano ({DEVICE_LABEL})") as demo:
    gr.Markdown(f"# Chatterbox Nano — {DEVICE_LABEL}")
    gr.Markdown("The model is downloaded and loaded when the app opens for the first time.")

    model_state = gr.State(None)

    with gr.Row():
        with gr.Column(scale=3):
            with gr.Row(equal_height=True):
                text = gr.Textbox(
                    value="Hello from Chatterbox Nano! [chuckle] This speech is generated on the CPU.",
                    label="Text to synthesize (long text is split automatically)",
                    lines=8,
                    scale=5,
                    min_width=320,
                    elem_id="main_textbox",
                )
                text_file = gr.File(
                    label="Drop or upload text",
                    file_count="single",
                    file_types=[".txt", ".text", ".md"],
                    type="filepath",
                    height=200,
                    scale=1,
                    min_width=140,
                )

            with gr.Row(elem_classes=["tag-container"]):
                for tag in EVENT_TAGS:
                    button = gr.Button(tag, elem_classes=["tag-btn"])
                    button.click(
                        fn=None,
                        inputs=[button, text],
                        outputs=text,
                        js=INSERT_TAG_JS,
                    )

            audio_output = gr.Audio(label="Generated audio", elem_id="generated_audio")
            run_button = gr.Button("Generate", variant="primary")

        with gr.Column(scale=2):
            reference_audio = gr.Audio(
                sources=["upload", "microphone"],
                type="filepath",
                label="Reference audio (optional)",
            )

            with gr.Accordion("Advanced options", open=False):
                seed_num = gr.Number(value=0, label="Random seed (0 for random)")
                temperature = gr.Slider(0.05, 2.0, step=0.05, value=0.8, label="Temperature")
                top_p = gr.Slider(0.0, 1.0, step=0.01, value=0.95, label="Top P")
                top_k = gr.Slider(0, 1000, step=10, value=1000, label="Top K")
                repetition_penalty = gr.Slider(
                    1.0, 2.0, step=0.05, value=1.2, label="Repetition penalty"
                )
                min_p = gr.Slider(0.0, 1.0, step=0.01, value=0.0, label="Min P (0 disables it)")
                norm_loudness = gr.Checkbox(value=True, label="Normalize loudness (-27 LUFS)")
                max_chunk_chars = gr.Slider(
                    100,
                    1000,
                    step=25,
                    value=300,
                    label="Maximum characters per chunk",
                )
                pause_ms = gr.Slider(
                    0,
                    1000,
                    step=25,
                    value=250,
                    label="Pause between chunks (milliseconds)",
                )

    demo.load(fn=load_model, outputs=model_state)
    text_file.change(fn=load_text_file, inputs=text_file, outputs=text)
    run_button.click(
        fn=generate,
        inputs=[
            model_state,
            text,
            reference_audio,
            temperature,
            seed_num,
            min_p,
            top_p,
            top_k,
            repetition_penalty,
            norm_loudness,
            max_chunk_chars,
            pause_ms,
        ],
        outputs=[model_state, audio_output],
    )


if __name__ == "__main__":
    demo.queue(max_size=10, default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        inbrowser=True,
        share=False,
        css=CUSTOM_CSS,
    )
