import gradio as gr

from webui.audio_processing import join_audio_chunks
from webui.config import read_asset
from webui.document_workspace import (
    SPLIT_MARKER,
    clear_document_projects,
    clean_text,
    first_section_id,
    import_document,
    list_documents,
    load_editor_section,
    load_manifest,
    load_section,
    outline_rows,
    prepare_entire_document,
    remove_repeated_headers_footers,
    reorder_sections,
    replace_text,
    restore_section,
    restructure_section,
    save_document_audio,
    save_editor_section,
    save_section,
    selected_section_ids,
)
from webui.model import generate_audio_chunk, load_model, set_seed
from webui.text_processing import split_text
from webui.themes import themed_styles


OUTLINE_HEADERS = ["", "Select", "#", "Section", "Words", "Characters", "Status"]


def build_document_interface(
    device: str,
    device_label: str,
    model_cache: dict,
) -> tuple[gr.Blocks, str]:
    custom_css = themed_styles()

    def get_model():
        if model_cache.get("model") is not None:
            return model_cache["model"]
        with model_cache["load_lock"]:
            if model_cache.get("model") is None:
                model_cache["model"] = load_model(device, device_label)
        return model_cache["model"]

    def document_outputs(document_id):
        section_id = first_section_id(document_id)
        title, text, viewer = load_editor_section(document_id, section_id)
        return (
            gr.update(choices=list_documents(), value=document_id),
            document_id,
            section_id,
            outline_rows(document_id),
            title,
            text,
            gr.update(value=viewer, visible=True),
            gr.update(value=None, visible=False),
            gr.update(visible=True),
        )

    def import_file(file_path):
        if not file_path:
            raise gr.Error("Upload a PDF or EPUB file.")
        document_id = import_document(file_path)
        return document_outputs(document_id)

    def open_document(document_id):
        if not document_id:
            return (
                None,
                None,
                [],
                "",
                "",
                gr.update(
                    value="<p>Drop or upload a document to begin.</p>",
                    visible=False,
                ),
                gr.update(value=None, visible=True),
                gr.update(visible=False),
            )
        section_id = first_section_id(document_id)
        title, text, viewer = load_editor_section(document_id, section_id)
        return (
            document_id,
            section_id,
            outline_rows(document_id),
            title,
            text,
            gr.update(value=viewer, visible=True),
            gr.update(value=None, visible=False),
            gr.update(visible=True),
        )

    def clear_and_show_document_upload():
        removed = clear_document_projects()
        gr.Info(f"Cleared {removed} stored document project(s).")
        return (
            gr.update(choices=[], value=None),
            None,
            None,
            [],
            "",
            "",
            gr.update(value=None, visible=True),
            gr.update(
                value="<p>Drop or upload a document to begin.</p>",
                visible=False,
            ),
            gr.update(visible=False),
            None,
        )

    def select_outline(document_id, rows, evt: gr.SelectData):
        if not document_id or not evt.index:
            return gr.skip(), gr.skip(), gr.skip(), gr.skip()
        if isinstance(evt.index, (tuple, list)) and evt.index[1] == 0:
            return gr.skip(), gr.skip(), gr.skip(), gr.skip()
        row_index = evt.index[0] if isinstance(evt.index, (tuple, list)) else evt.index
        manifest = load_manifest(document_id)
        if row_index < 0 or row_index >= len(manifest["sections"]):
            return gr.skip(), gr.skip(), gr.skip(), gr.skip()
        section_id = manifest["sections"][row_index]
        title, text, viewer = load_editor_section(document_id, section_id)
        return section_id, title, text, viewer

    def save_current(document_id, section_id, title, text, rows):
        save_editor_section(document_id, section_id, title, text)
        selected = set(selected_section_ids(document_id, rows))
        gr.Info("Section saved.")
        return outline_rows(document_id, selected)

    def autosave_current(document_id, section_id, title, text, rows):
        if not document_id or not section_id:
            return gr.skip()
        save_editor_section(document_id, section_id, title, text)
        selected = set(selected_section_ids(document_id, rows))
        return outline_rows(document_id, selected)

    def restore_current(document_id, section_id, rows):
        text, _ = restore_section(document_id, section_id)
        selected = set(selected_section_ids(document_id, rows))
        return text, outline_rows(document_id, selected)

    def apply_cleanup(text, operation):
        return clean_text(text, operation)

    def clean_headers(document_id, section_id, rows):
        changed = remove_repeated_headers_footers(document_id)
        section = load_section(document_id, section_id)
        selected = set(selected_section_ids(document_id, rows))
        gr.Info(f"Updated {changed} sections.")
        return section["text"], outline_rows(document_id, selected)

    def replace(document_id, section_id, search, replacement, scope, rows):
        count = replace_text(
            document_id,
            section_id,
            search,
            replacement,
            scope,
        )
        section = load_section(document_id, section_id)
        selected = set(selected_section_ids(document_id, rows))
        gr.Info(f"Replaced {count} occurrence(s).")
        return section["text"], outline_rows(document_id, selected)

    def reorder_queue(document_id, order_value, rows):
        if not document_id or not order_value:
            return gr.skip()
        selected = set(selected_section_ids(document_id, rows))
        try:
            order = [int(value) for value in order_value.split(",")]
        except ValueError as error:
            raise gr.Error("The document queue returned an invalid order.") from error
        reorder_sections(document_id, order)
        return outline_rows(document_id, selected)

    def restructure(document_id, section_id, title, text, action, rows):
        save_editor_section(document_id, section_id, title, text)
        target = restructure_section(document_id, section_id, action)
        selected = set(selected_section_ids(document_id, rows))
        title, text, viewer = load_editor_section(document_id, target)
        return (
            target,
            outline_rows(document_id, selected),
            title,
            text,
            viewer,
        )

    def synthesize(
        mode,
        document_id,
        section_id,
        title,
        text,
        rows,
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
        if not document_id or not section_id:
            raise gr.Error("Open a document first.")
        save_editor_section(document_id, section_id, title, text)
        manifest = load_manifest(document_id)
        if mode == "Current":
            targets = [section_id]
        elif mode == "Selected":
            targets = selected_section_ids(document_id, rows)
            if not targets:
                raise gr.Error("Select at least one section.")
        else:
            targets = prepare_entire_document(document_id)
            if not targets:
                raise gr.Error("The document contains no text to synthesize.")

        for target in targets:
            queued = load_section(document_id, target)
            queued["status"] = "Queued"
            save_section(document_id, queued)

        if seed_num:
            set_seed(int(seed_num))
        model = get_model()
        last_audio = None
        failures: list[str] = []

        for target_index, target in enumerate(targets, start=1):
            section = load_section(document_id, target)
            section["status"] = "Generating"
            save_section(document_id, section)
            chunks = split_text(section["text"], int(max_chunk_chars))
            if not chunks:
                section["status"] = "Failed"
                save_section(document_id, section)
                failures.append(section["title"])
                continue

            generated = []
            try:
                with model_cache["generation_lock"]:
                    for chunk_index, chunk in enumerate(chunks, start=1):
                        progress(
                            (
                                (target_index - 1)
                                + (chunk_index - 1) / len(chunks)
                            )
                            / len(targets),
                            desc=(
                                f"{section['title']}: chunk "
                                f"{chunk_index}/{len(chunks)}"
                            ),
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
                audio = join_audio_chunks(generated, model.sr, pause_ms)
                last_audio = save_document_audio(
                    document_id,
                    target,
                    audio,
                    model.sr,
                )
            except Exception:
                section = load_section(document_id, target)
                section["status"] = "Failed"
                save_section(document_id, section)
                failures.append(section["title"])

        progress(1.0, desc="Document synthesis complete")
        if failures:
            gr.Warning("Failed: " + ", ".join(failures))
        elif last_audio:
            gr.Info(f"Generated {len(targets)} section(s).")
        selected = set(selected_section_ids(document_id, rows))
        return outline_rows(document_id, selected), (
            str(last_audio) if last_audio else None
        )

    documents = list_documents()
    initial_document = documents[0][1] if documents else None
    initial_section = (
        first_section_id(initial_document) if initial_document else None
    )

    with gr.Blocks(title="Document workspace") as demo:
        gr.Markdown(f"# Document workspace — {device_label}")
        with gr.Row():
            document_picker = gr.Dropdown(
                choices=documents,
                value=initial_document,
                label="Saved documents",
                scale=5,
            )
            main_button = gr.Button("Main synthesizer", scale=1)

        document_state = gr.State(initial_document)
        active_section = gr.State(initial_section)

        with gr.Row(equal_height=False):
            with gr.Column(scale=1, min_width=420):
                gr.Markdown("## Text editor")
                outline = gr.Dataframe(
                    value=outline_rows(initial_document) if initial_document else [],
                    headers=OUTLINE_HEADERS,
                    datatype=[
                        "str",
                        "bool",
                        "number",
                        "str",
                        "number",
                        "number",
                        "str",
                    ],
                    type="array",
                    label="Document outline and generation queue",
                    interactive=True,
                    column_count=7,
                    row_count=0,
                    max_height=300,
                    wrap=True,
                    elem_id="document_outline",
                )
                reorder_signal = gr.Textbox(
                    container=False,
                    elem_id="document_queue_order",
                    elem_classes=["document-queue-order"],
                )
                section_title = gr.Textbox(
                    label="Section title",
                    value=(
                        load_section(initial_document, initial_section)["title"]
                        if initial_document
                        else ""
                    ),
                )
                editor = gr.Textbox(
                    label="Editable extracted text",
                    value=(
                        load_section(initial_document, initial_section)["text"]
                        if initial_document
                        else ""
                    ),
                    lines=24,
                    elem_id="document_editor",
                )
                with gr.Row():
                    save_button = gr.Button("Save", variant="primary")
                    restore_button = gr.Button("Restore original")
                    insert_split = gr.Button("Insert split marker")

                with gr.Accordion("Cleanup and structure", open=False):
                    with gr.Row():
                        cleanup_operation = gr.Dropdown(
                            choices=[
                                "Join broken lines",
                                "Repair hyphenation",
                                "Normalize whitespace",
                            ],
                            value="Join broken lines",
                            label="Cleanup",
                        )
                        cleanup_button = gr.Button("Apply to editor")
                        headers_button = gr.Button("Remove repeated headers/footers")
                    with gr.Row():
                        duplicate = gr.Button("Duplicate")
                        remove = gr.Button("Remove")
                    with gr.Row():
                        merge_previous = gr.Button("Merge previous")
                        merge_next = gr.Button("Merge next")
                        split_button = gr.Button("Split at marker")
                    with gr.Group():
                        with gr.Row():
                            search = gr.Textbox(label="Find")
                            replacement = gr.Textbox(label="Replace with")
                            replace_scope = gr.Radio(
                                choices=["Current section", "Entire document"],
                                value="Current section",
                                label="Scope",
                            )
                            replace_button = gr.Button("Replace")

            with gr.Column(scale=1, min_width=420):
                gr.Markdown("## Document viewer")
                document_upload = gr.File(
                    label="Drop or upload a PDF or EPUB",
                    file_types=[".pdf", ".epub"],
                    type="filepath",
                    height=760,
                    visible=not bool(initial_document),
                    elem_id="document_source_upload",
                )
                source_viewer = gr.HTML(
                    value=(
                        load_editor_section(
                            initial_document,
                            initial_section,
                        )[2]
                        if initial_document
                        else "<p>Import or select a document.</p>"
                    ),
                    elem_id="document_source_viewer",
                    min_height=760,
                    visible=bool(initial_document),
                )
                replace_document = gr.Button(
                    "Replace document",
                    visible=bool(initial_document),
                    variant="stop",
                )

        with gr.Group(elem_classes=["voxbench-surface"]):
            gr.Markdown("## Synthesize document")
            gr.Markdown(
                "Sections are processed sequentially; each section still uses "
                "automatic character-based chunking."
            )
            with gr.Row():
                reference_audio = gr.Audio(
                    sources=["upload", "microphone"],
                    type="filepath",
                    label="Reference audio (optional)",
                    elem_classes=["audio-waveform"],
                )
                generated_audio = gr.Audio(
                    type="filepath",
                    label="Latest generated section",
                    elem_classes=["audio-waveform"],
                )
            with gr.Accordion("Synthesis settings", open=False):
                with gr.Row():
                    seed_num = gr.Number(value=0, label="Random seed (0 for random)")
                    temperature = gr.Slider(
                        0.05, 2.0, value=0.8, step=0.05, label="Temperature"
                    )
                    norm_loudness = gr.Checkbox(
                        value=True,
                        label="Normalize loudness (-27 LUFS)",
                    )
                with gr.Row():
                    min_p = gr.Slider(0, 1, value=0, step=0.01, label="Min P")
                    top_p = gr.Slider(0, 1, value=0.95, step=0.01, label="Top P")
                    top_k = gr.Slider(0, 1000, value=1000, step=10, label="Top K")
                    repetition_penalty = gr.Slider(
                        1, 2, value=1.2, step=0.05, label="Repetition penalty"
                    )
                with gr.Row():
                    max_chunk_chars = gr.Slider(
                        100,
                        1000,
                        value=300,
                        step=25,
                        label="Maximum characters per chunk",
                    )
                    pause_ms = gr.Slider(
                        0,
                        1000,
                        value=250,
                        step=25,
                        label="Pause between chunks (ms)",
                    )
            with gr.Row():
                synth_current = gr.Button(
                    "Synthesize current section",
                    elem_classes=["voxbench-button"],
                )
                synth_selected = gr.Button(
                    "Synthesize selected sections",
                    elem_classes=["voxbench-button"],
                )
                synth_all = gr.Button(
                    "Synthesize entire document",
                    variant="primary",
                    elem_classes=["voxbench-button"],
                )

        main_button.click(
            fn=None,
            js="() => { window.open('/', '_blank', 'noopener'); }",
        )
        document_upload.upload(
            fn=import_file,
            inputs=document_upload,
            outputs=[
                document_picker,
                document_state,
                active_section,
                outline,
                section_title,
                editor,
                source_viewer,
                document_upload,
                replace_document,
            ],
        )
        replace_document.click(
            fn=clear_and_show_document_upload,
            outputs=[
                document_picker,
                document_state,
                active_section,
                outline,
                section_title,
                editor,
                document_upload,
                source_viewer,
                replace_document,
                generated_audio,
            ],
        )
        document_picker.change(
            fn=open_document,
            inputs=document_picker,
            outputs=[
                document_state,
                active_section,
                outline,
                section_title,
                editor,
                source_viewer,
                document_upload,
                replace_document,
            ],
        )
        outline.select(
            fn=select_outline,
            inputs=[document_state, outline],
            outputs=[active_section, section_title, editor, source_viewer],
        )
        reorder_signal.input(
            fn=reorder_queue,
            inputs=[document_state, reorder_signal, outline],
            outputs=outline,
        )
        save_button.click(
            fn=save_current,
            inputs=[
                document_state,
                active_section,
                section_title,
                editor,
                outline,
            ],
            outputs=outline,
        )
        editor.blur(
            fn=autosave_current,
            inputs=[
                document_state,
                active_section,
                section_title,
                editor,
                outline,
            ],
            outputs=outline,
        )
        section_title.blur(
            fn=autosave_current,
            inputs=[
                document_state,
                active_section,
                section_title,
                editor,
                outline,
            ],
            outputs=outline,
        )
        restore_button.click(
            fn=restore_current,
            inputs=[document_state, active_section, outline],
            outputs=[editor, outline],
        )
        insert_split.click(
            fn=None,
            inputs=editor,
            outputs=editor,
            js=f"""(text) => {{
                const box = document.querySelector('#document_editor textarea');
                if (!box) return text + '\\n{SPLIT_MARKER}\\n';
                const start = box.selectionStart;
                return text.slice(0, start) + '\\n{SPLIT_MARKER}\\n' + text.slice(start);
            }}""",
        )
        cleanup_button.click(
            fn=apply_cleanup,
            inputs=[editor, cleanup_operation],
            outputs=editor,
        )
        headers_button.click(
            fn=clean_headers,
            inputs=[document_state, active_section, outline],
            outputs=[editor, outline],
        )
        replace_button.click(
            fn=replace,
            inputs=[
                document_state,
                active_section,
                search,
                replacement,
                replace_scope,
                outline,
            ],
            outputs=[editor, outline],
        )

        structure_inputs = [
            document_state,
            active_section,
            section_title,
            editor,
        ]
        structure_outputs = [
            active_section,
            outline,
            section_title,
            editor,
            source_viewer,
        ]
        for button, action in [
            (duplicate, "Duplicate"),
            (remove, "Remove"),
            (merge_previous, "Merge previous"),
            (merge_next, "Merge next"),
            (split_button, "Split"),
        ]:
            button.click(
                fn=lambda doc, section, title, text, rows, action=action: restructure(
                    doc,
                    section,
                    title,
                    text,
                    action,
                    rows,
                ),
                inputs=[*structure_inputs, outline],
                outputs=structure_outputs,
            )

        demo.load(fn=None, js=read_asset("document_queue.js"))

        synthesis_inputs = [
            document_state,
            active_section,
            section_title,
            editor,
            outline,
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
        ]
        for button, mode in [
            (synth_current, "Current"),
            (synth_selected, "Selected"),
            (synth_all, "Entire"),
        ]:
            button.click(
                fn=lambda *args, mode=mode: synthesize(mode, *args),
                inputs=synthesis_inputs,
                outputs=[outline, generated_audio],
            )

    return demo, custom_css
