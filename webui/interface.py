import gradio as gr

from webui.audio_processing import join_audio_chunks
from webui.config import (
    AUDIO_FILE_EXTENSIONS,
    EVENT_TAGS,
    FFMPEG_DOWNLOAD_URL,
    OUTPUT_FORMATS,
    TEXT_FILE_EXTENSIONS,
    read_asset,
)
from webui.model import generate_audio_chunk, load_model, set_seed
from webui.storage import (
    list_reference_samples,
    route_uploaded_file,
    save_generated_audio,
    save_reference_sample,
)
from webui.text_processing import split_text


def build_interface(
    device: str,
    device_label: str,
    ffmpeg_path: str | None,
) -> tuple[gr.Blocks, str]:
    custom_css = read_asset("styles.css")
    insert_tag_js = read_asset("insert_tag.js")

    def load_nano_model():
        return load_model(device, device_label)

    def persist_reference_sample(file_path):
        saved_path = save_reference_sample(file_path)
        return gr.update(
            choices=list_reference_samples(),
            value=str(saved_path) if saved_path else None,
        )

    def route_drop_target(file_path):
        file_kind, value = route_uploaded_file(file_path)
        if file_kind == "text":
            return value, gr.skip(), gr.skip(), None
        if file_kind == "audio":
            return (
                gr.skip(),
                str(value),
                gr.update(
                    choices=list_reference_samples(),
                    value=str(value),
                ),
                None,
            )
        return gr.skip(), gr.skip(), gr.skip(), None

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
        persistent_storage,
        output_directory,
        output_format,
        progress=gr.Progress(),
    ):
        if not text or not text.strip():
            raise gr.Error("Enter some text to synthesize.")

        if model is None:
            model = load_nano_model()

        if seed_num:
            set_seed(int(seed_num))

        chunks = split_text(text, int(max_chunk_chars))
        generated = []

        for index, chunk in enumerate(chunks, start=1):
            progress(
                (index - 1) / len(chunks),
                desc=f"Generating chunk {index} of {len(chunks)}",
            )
            generated.append(
                generate_audio_chunk(
                    model=model,
                    text=chunk,
                    audio_prompt_path=audio_prompt_path,
                    temperature=temperature,
                    min_p=min_p,
                    top_p=top_p,
                    top_k=int(top_k),
                    repetition_penalty=repetition_penalty,
                    norm_loudness=norm_loudness,
                )
            )

        progress(1.0, desc="Joining audio")
        audio = join_audio_chunks(generated, model.sr, pause_ms)
        audio_result = (model.sr, audio.numpy())
        if persistent_storage:
            saved_path = save_generated_audio(
                audio,
                model.sr,
                text,
                output_directory,
                output_format,
                ffmpeg_path,
            )
            gr.Info(f"Saved generated audio to {saved_path}")
            audio_result = str(saved_path)
        return model, audio_result

    with gr.Blocks(title=f"Chatterbox Nano ({device_label})") as demo:
        gr.Markdown(f"# Chatterbox Nano — {device_label}")
        gr.Markdown("The model is downloaded and loaded when the app opens for the first time.")
        assembly_button = gr.Button("Chapter assembly", size="sm")

        model_state = gr.State(None)
        assembly_button.click(
            fn=None,
            js="() => { window.open('/assemble/', '_blank', 'noopener'); }",
        )

        with gr.Row():
            with gr.Column(scale=3):
                with gr.Row(equal_height=True):
                    text = gr.Textbox(
                        value=(
                            "Hello from Chatterbox Nano! [chuckle] "
                            "This speech is generated on the CPU."
                        ),
                        label="Text to synthesize (long text is split automatically)",
                        lines=8,
                        scale=5,
                        min_width=320,
                        elem_id="main_textbox",
                    )
                    upload_file = gr.File(
                        label="Drop text or reference audio",
                        file_count="single",
                        file_types=sorted(TEXT_FILE_EXTENSIONS | AUDIO_FILE_EXTENSIONS),
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
                            js=insert_tag_js,
                        )

                audio_output = gr.Audio(label="Generated audio", elem_id="generated_audio")
                run_button = gr.Button("Generate", variant="primary")

            with gr.Column(scale=2):
                reference_audio = gr.Audio(
                    sources=["upload", "microphone"],
                    type="filepath",
                    label="Reference audio (optional)",
                )
                saved_reference = gr.Dropdown(
                    choices=list_reference_samples(),
                    label="Saved reference samples",
                    allow_custom_value=False,
                )

                with gr.Accordion("Advanced options", open=False):
                    seed_num = gr.Number(value=0, label="Random seed (0 for random)")
                    temperature = gr.Slider(
                        0.05,
                        2.0,
                        step=0.05,
                        value=0.8,
                        label="Temperature",
                    )
                    top_p = gr.Slider(0.0, 1.0, step=0.01, value=0.95, label="Top P")
                    top_k = gr.Slider(0, 1000, step=10, value=1000, label="Top K")
                    repetition_penalty = gr.Slider(
                        1.0,
                        2.0,
                        step=0.05,
                        value=1.2,
                        label="Repetition penalty",
                    )
                    min_p = gr.Slider(
                        0.0,
                        1.0,
                        step=0.01,
                        value=0.0,
                        label="Min P (0 disables it)",
                    )
                    norm_loudness = gr.Checkbox(
                        value=True,
                        label="Normalize loudness (-27 LUFS)",
                    )
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
                    persistent_storage = gr.Checkbox(
                        value=True,
                        label="Save generated audio",
                    )
                    output_directory = gr.Textbox(
                        value="outputs/",
                        label="Output folder",
                    )
                    gr.Markdown(
                        f"Formats other than .WAV require [FFmpeg]({FFMPEG_DOWNLOAD_URL})."
                    )
                    output_format = gr.Radio(
                        choices=OUTPUT_FORMATS,
                        value=".wav",
                        label="Saved format",
                        elem_id="output_format",
                    )

        demo.load(fn=load_nano_model, outputs=model_state)
        if not ffmpeg_path:
            demo.load(
                fn=None,
                js="""() => {
                    setTimeout(() => {
                        document.querySelectorAll(
                            '#output_format input[type="radio"]'
                        ).forEach((option) => {
                            option.disabled = option.value !== '.wav';
                        });
                    }, 0);
                }""",
            )
        upload_file.upload(
            fn=route_drop_target,
            inputs=upload_file,
            outputs=[text, reference_audio, saved_reference, upload_file],
        )
        reference_audio.input(
            fn=persist_reference_sample,
            inputs=reference_audio,
            outputs=saved_reference,
        )
        saved_reference.input(
            fn=lambda file_path: file_path,
            inputs=saved_reference,
            outputs=reference_audio,
        )
        persistent_storage.change(
            fn=lambda enabled: gr.update(visible=enabled),
            inputs=persistent_storage,
            outputs=output_directory,
        )
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
                persistent_storage,
                output_directory,
                output_format,
            ],
            outputs=[model_state, audio_output],
        )

    return demo, custom_css
