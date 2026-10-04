"""The single-page NiceGUI interface for VoxBench.

The UI intentionally owns document handling, output files, and FFmpeg work.  The
inference backend is only asked to turn one prepared text chunk into audio.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from nicegui import run, ui

from application.audiobook import SynthesisSettings, create_audiobook
from application.uploads import discard_upload, store_upload
from inference import InferenceError
from webui.config import (
    AUDIO_FILE_EXTENSIONS,
    FFMPEG_DOWNLOAD_URL,
    MAX_REFERENCE_AUDIO_BYTES,
    OUTPUTS_DIR,
    REFERENCE_AUDIO_DIR,
)
from webui.app_config import (
    ModelConnection,
    ModelConnectionSettings,
    masked_secret,
    updated_secret,
)
from app_logic.workspace import (
    SUPPORTED_DOCUMENT_EXTENSIONS,
    apply_cleanup_to_sections,
    clear_document_projects,
    document_page_count,
    document_source_path,
    import_document,
    list_documents,
    load_editor_section,
    load_manifest,
    remove_repeated_headers_footers,
    restore_section,
    save_editor_section,
    set_empty_sections_ignored,
)
from webui.errors import VoxBenchError
from app_logic.storage import (
    clear_uploaded_reference_audio,
    default_reference_sample,
    replace_uploaded_reference_audio,
)


def _button(label: str, callback=None, *, icon: str | None = None) -> ui.button:
    return ui.button(label, on_click=callback, icon=icon).classes("vox-button")


def _format_file_size(size: int) -> str:
    """Format a byte count for the compact upload status row."""
    units = ("B", "KB", "MB", "GB")
    amount = float(max(size, 0))
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{size} B"


def _section_rows(document_id: str) -> list[dict[str, Any]]:
    manifest = load_manifest(document_id)
    return [
        {"id": section_id, "page": index}
        for index, section_id in enumerate(manifest["sections"], start=1)
    ]


def build_interface(
    *,
    model_connection: ModelConnection,
    ffmpeg_path: str | None,
    ffprobe_path: str | None,
) -> None:
    """Build the page for one NiceGUI client."""
    stored_documents = list_documents()
    stored_manifest = load_manifest(stored_documents[0][1]) if stored_documents else None
    bundled_reference = default_reference_sample()
    reference_workspace = REFERENCE_AUDIO_DIR / uuid.uuid4().hex
    state: dict[str, Any] = {
        "document_id": stored_manifest["id"] if stored_manifest else None,
        "reference_audio": None,
        "reference_name": None,
        "default_reference_audio": str(bundled_reference) if bundled_reference else None,
        "busy": False,
        "progress": "Ready.",
        "settings": SynthesisSettings(),
        "output_format": ".m4b" if ffmpeg_path and ffprobe_path else ".wav",
        "use_pdf_bookmarks": True,
        "pdf_bookmark_depth": 1,
        "skip_pdf_table_of_contents": True,
        "ignore_empty_pages": False,
        "selection_version": 0,
        "editor_section_id": None,
        "editor_section_title": "",
    }

    def cleanup_reference_workspace() -> None:
        try:
            clear_uploaded_reference_audio(reference_workspace)
        except OSError:
            pass

    ui.context.client.on_disconnect(cleanup_reference_workspace)
    stored_document_size = 0
    stored_document_pages = 0
    if stored_manifest:
        try:
            stored_document_size = document_source_path(stored_manifest["id"]).stat().st_size
        except OSError:
            pass
        stored_document_pages = document_page_count(stored_manifest["id"])

    ui.add_head_html("<title>VoxBench</title>")
    with ui.column().classes("w-full max-w-6xl mx-auto p-4 gap-5"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-3"):
                ui.image("/static/favicon.png").classes("w-11 h-11 rounded-lg")
                with ui.column().classes("gap-0"):
                    ui.label("VoxBench").classes("vox-page-title text-3xl font-bold")
                    ui.label("Create text to speech and complete audiobooks.").classes(
                        "vox-muted"
                    )
            with ui.row().classes("items-center"):
                settings_button = _button("Settings", icon="settings")
                advanced_button = _button("Advanced editing", icon="edit_note")

        if not ffmpeg_path or not ffprobe_path:
            with ui.row().classes("vox-card w-full p-3 items-center gap-2"):
                ui.label("FFmpeg is required for document audiobooks.")
                ui.link("Download FFmpeg", FFMPEG_DOWNLOAD_URL, new_tab=True).classes(
                    "vox-muted"
                )

        status = ui.label("").classes("vox-muted")
        with ui.row().classes("w-full items-center gap-3"):
            progress_bar = ui.linear_progress(value=0).classes("flex-1")
            progress_percent = ui.label("0.0%").classes("vox-muted text-sm")
        output_area = ui.column().classes("w-full")

        with ui.tabs().classes("w-full") as tabs:
            document_tab = ui.tab("Document", icon="description")
            text_tab = ui.tab("Text", icon="text_fields")
        with ui.tab_panels(tabs, value=document_tab).classes("w-full"):
            with ui.tab_panel(document_tab):
                with ui.card().classes("vox-card w-full p-5"):
                    ui.label("1. Upload your document").classes("vox-primary-heading text-lg font-medium")
                    ui.label("PDF, EPUB, or DOCX.").classes(
                        "vox-muted"
                    )
                    async def remove_document() -> None:
                        await run.io_bound(clear_document_projects)
                        state["document_id"] = None
                        state["ignore_empty_pages"] = False
                        document_upload_progress.visible = False
                        document_check.visible = False
                        document_remove.visible = False
                        document_file_label.set_text("No document selected.")
                        document_upload.reset()
                        status.set_text("Document removed.")

                    async def receive_document(event) -> None:
                        suffixes = SUPPORTED_DOCUMENT_EXTENSIONS
                        uploaded: Path | None = None
                        try:
                            data = event.content.read()
                            uploaded = store_upload(event.name, data, suffixes)
                            status.set_text("Reading document…")
                            await run.io_bound(clear_document_projects)
                            state["document_id"] = None
                            state["ignore_empty_pages"] = False
                            document_id = await run.io_bound(
                                import_document,
                                str(uploaded),
                                event.name,
                            )
                            state["document_id"] = document_id
                            manifest = await run.io_bound(load_manifest, document_id)
                            page_count = await run.io_bound(document_page_count, document_id)
                            document_file_label.set_text(
                                f"{manifest['source_name']} ({_format_file_size(len(data))}) - "
                                f"{page_count} Pages."
                            )
                            document_check.visible = True
                            document_remove.visible = True
                            status.set_text("Document ready.")
                        except (OSError, VoxBenchError) as error:
                            ui.notify(str(error), type="negative")
                            if not state["document_id"]:
                                document_file_label.set_text("No document selected.")
                            status.set_text("Document could not be loaded.")
                        finally:
                            document_upload_progress.visible = False
                            document_upload.reset()
                            if uploaded:
                                discard_upload(uploaded)

                    with ui.element("div").classes("vox-upload-shell vox-document-upload-shell w-full mt-3"):
                        document_upload = ui.upload(
                            on_upload=receive_document,
                            on_begin_upload=lambda _: _begin_document_upload(),
                            auto_upload=True,
                            max_files=1,
                            label="",
                        ).props("accept=.pdf,.epub,.docx flat hide-upload-btn").classes("vox-upload w-full")
                        ui.icon("description").classes("vox-upload-icon")

                    with ui.element("div").classes("vox-upload-status w-full mt-2"):
                        document_upload_progress = ui.linear_progress(value=0).props("indeterminate").classes(
                            "vox-upload-progress w-full"
                        )
                        with ui.row().classes("w-full items-center no-wrap gap-2"):
                            document_check = ui.icon("check_circle").classes("vox-upload-success")
                            document_file_label = ui.label(
                                (
                                    f"{stored_manifest['source_name']} ({_format_file_size(stored_document_size)}) - "
                                    f"{stored_document_pages} pages ready."
                                    if stored_manifest
                                    else "No document selected."
                                )
                            ).classes("vox-upload-file-label")
                            document_remove = ui.button(icon="close", on_click=remove_document).classes(
                                "vox-upload-remove ml-auto"
                            ).tooltip("Delete document")

                    document_upload_progress.visible = False
                    document_check.visible = bool(stored_manifest)
                    document_remove.visible = bool(stored_manifest)

                    def _begin_document_upload() -> None:
                        document_upload_progress.visible = True
                        document_check.visible = False
                        document_remove.visible = False
                        document_file_label.set_text("Uploading document…")

            with ui.tab_panel(text_tab):
                with ui.card().classes("vox-card w-full p-5"):
                    ui.label("1. Paste text").classes("vox-primary-heading text-lg font-medium")
                    text_input = ui.textarea(
                        placeholder="Paste the text you want VoxBench to narrate…"
                    ).classes("vox-text-input w-full").props("outlined autogrow")

        with ui.card().classes("vox-card w-full p-5"):
            ui.label("2. Add a voice sample (optional)").classes("vox-primary-heading text-lg font-medium")

            def default_reference_label() -> str:
                default_reference = state["default_reference_audio"]
                if default_reference:
                    return f"Using default voice"
                return "No reference audio selected."

            def reference_label() -> str:
                reference = state["reference_audio"]
                if reference:
                    return f"{state['reference_name'] or Path(reference).name} (uploaded reference)"
                return default_reference_label()

            async def remove_reference() -> None:
                if state["reference_audio"]:
                    try:
                        await run.io_bound(clear_uploaded_reference_audio, reference_workspace)
                    except (OSError, VoxBenchError) as error:
                        ui.notify(str(error), type="negative")
                        return
                state["reference_audio"] = None
                state["reference_name"] = None
                reference_upload_progress.visible = False
                reference_check.visible = False
                reference_remove.visible = False
                reference_file_label.set_text(default_reference_label())
                reference_upload.reset()
                status.set_text("Reference audio removed.")

            async def receive_reference(event) -> None:
                uploaded: Path | None = None
                try:
                    data = event.content.read()
                    if len(data) > MAX_REFERENCE_AUDIO_BYTES:
                        raise VoxBenchError("Reference audio must be 10 MB or smaller.")
                    uploaded = store_upload(event.name, data, AUDIO_FILE_EXTENSIONS)
                    sample = await run.io_bound(
                        replace_uploaded_reference_audio,
                        str(uploaded),
                        reference_workspace,
                    )
                    state["reference_audio"] = str(sample) if sample else None
                    state["reference_name"] = Path(event.name).name if sample else None
                    reference_file_label.set_text(
                        f"{state['reference_name']} ({_format_file_size(len(data))})"
                        if sample
                        else default_reference_label()
                    )
                    reference_check.visible = bool(sample)
                    reference_remove.visible = bool(sample)
                    status.set_text("Reference audio ready.")
                except (OSError, VoxBenchError) as error:
                    ui.notify(str(error), type="negative")
                finally:
                    reference_upload_progress.visible = False
                    reference_upload.reset()
                    if uploaded:
                        discard_upload(uploaded)

            with ui.element("div").classes("vox-upload-shell vox-audio-upload-shell w-full mt-3"):
                reference_upload = ui.upload(
                    on_upload=receive_reference,
                    on_begin_upload=lambda _: _begin_reference_upload(),
                    on_rejected=lambda _: ui.notify(
                        "Reference audio must be 10 MB or smaller.", type="warning"
                    ),
                    auto_upload=True,
                    max_files=1,
                    max_file_size=MAX_REFERENCE_AUDIO_BYTES,
                    label="",
                ).props("accept=.wav,.mp3,.m4a,.ogg,.flac,.webm flat hide-upload-btn").classes(
                    "vox-upload w-full"
                )
                ui.icon("music_note").classes("vox-upload-icon")

            with ui.element("div").classes("vox-upload-status w-full mt-2"):
                reference_upload_progress = ui.linear_progress(value=0).props("indeterminate").classes(
                    "vox-upload-progress w-full"
                )
                with ui.row().classes("w-full items-center no-wrap gap-2"):
                    reference_check = ui.icon("check_circle").classes("vox-upload-success")
                    reference_file_label = ui.label(reference_label()).classes(
                        "vox-upload-file-label"
                    )
                    reference_remove = ui.button(icon="close", on_click=remove_reference).classes(
                        "vox-upload-remove ml-auto"
                    ).tooltip("Delete reference audio")

            reference_upload_progress.visible = False
            reference_check.visible = bool(state["reference_audio"])
            reference_remove.visible = bool(state["reference_audio"])

            def _begin_reference_upload() -> None:
                reference_upload_progress.visible = True
                reference_check.visible = False
                reference_remove.visible = False
                reference_file_label.set_text("Uploading reference audio…")

        def show_output(result) -> None:
            output_area.clear()
            with output_area:
                with ui.card().classes("vox-card w-full p-4"):
                    ui.label("Audiobook ready").classes("vox-primary-heading text-lg font-medium")
                    ui.label(result.output_path.name).classes("vox-muted")
                    ui.audio(f"/outputs/{result.output_path.name}").classes("w-full")
                    _button("Download", lambda: ui.download(result.output_path))

        async def create() -> None:
            if state["busy"]:
                return
            document_id = state["document_id"] if tabs.value == document_tab.props["name"] else None
            pasted_text = text_input.value if tabs.value == text_tab.props["name"] else None
            if not document_id and not (pasted_text or "").strip():
                ui.notify("Upload a document or paste text to begin.", type="warning")
                return
            if state["output_format"] != ".wav" and not ffmpeg_path:
                ui.notify("FFmpeg is required for the selected output format.", type="negative")
                return
            if state["output_format"] == ".m4b" and not ffprobe_path:
                ui.notify("FFprobe is required for chaptered M4B output.", type="negative")
                return
            if document_id and (not ffmpeg_path or not ffprobe_path):
                ui.notify("FFmpeg and FFprobe are required to assemble document chapters.", type="negative")
                return
            state["busy"] = True
            create_button.disable()
            progress_bar.value = 0
            progress_percent.set_text("0.0%")
            state["progress"] = (0.0, "Starting")
            status.set_text("Starting generation…")

            def report(value: float, message: str) -> None:
                state["progress"] = (max(0.0, min(1.0, value)), message)

            try:
                result = await run.io_bound(
                    create_audiobook,
                    backend=model_connection.backend,
                    document_path=None,
                    document_id=document_id,
                    pasted_text=pasted_text,
                    reference_audio=state["reference_audio"] or state["default_reference_audio"],
                    settings=state["settings"],
                    ffmpeg_path=ffmpeg_path,
                    ffprobe_path=ffprobe_path,
                    output_directory=str(OUTPUTS_DIR),
                    output_format=state["output_format"],
                    use_pdf_bookmarks=state["use_pdf_bookmarks"],
                    pdf_bookmark_depth=state["pdf_bookmark_depth"],
                    skip_pdf_table_of_contents=state["skip_pdf_table_of_contents"],
                    progress=report,
                )
                show_output(result)
                progress_bar.value = 1
                progress_percent.set_text("100.0%")
                status.set_text("Finished.")
            except (InferenceError, OSError, VoxBenchError) as error:
                ui.notify(str(error), type="negative")
                status.set_text("Generation failed.")
            finally:
                state["busy"] = False
                create_button.enable()

        create_button = _button("3. Create audiobook", create, icon="auto_awesome").classes(
            "w-full text-lg py-3"
        )

        def update_progress() -> None:
            if state["busy"]:
                value, message = state["progress"]
                progress_bar.value = value
                progress_percent.set_text(f"{value * 100:.1f}%")
                status.set_text(message)

        ui.timer(0.25, update_progress)

        with ui.dialog() as settings_dialog, ui.card().classes("vox-card w-[min(94vw,680px)] p-5"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Generation settings").classes("vox-primary-heading text-xl font-medium")
                _button("Close", settings_dialog.close, icon="close")
            ui.label("M4B is the default and writes chapter markers from document pages.").classes(
                "vox-muted"
            )
            available_formats = {
                ".m4b": "M4B audiobook (chaptered)",
                ".mp3": "MP3 audio",
                ".wav": "WAV audio",
                ".m4a": "M4A audio",
                ".ogg": "Ogg audio",
                ".webm": "WebM audio",
            }
            if not ffmpeg_path:
                available_formats = {".wav": available_formats[".wav"]}
            output_format = ui.select(
                available_formats,
                value=state["output_format"],
                label="Output file type",
            ).classes("w-full")
            with ui.expansion("Synthesis controls", icon="tune").classes("w-full"):
                ui.label("These settings apply to all chunks and document sections.").classes("vox-muted")
                with ui.row().classes("w-full gap-3"):
                    temperature = ui.number("Temperature", value=0.8, min=0, max=2, step=0.05).classes("flex-1")
                    seed = ui.number("Seed (0 = random)", value=0, min=0, precision=0).classes("flex-1")
                    max_chunk_chars = ui.number("Chunk length", value=300, min=50, max=2_000, precision=0).classes("flex-1")
                with ui.row().classes("w-full gap-3"):
                    min_p = ui.number("Min P", value=0.0, min=0, max=1, step=0.01).classes("flex-1")
                    top_p = ui.number("Top P", value=0.95, min=0, max=1, step=0.01).classes("flex-1")
                    top_k = ui.number("Top K", value=1000, min=0, precision=0).classes("flex-1")
                with ui.row().classes("w-full gap-3 items-center"):
                    repetition_penalty = ui.number("Repetition penalty", value=1.2, min=0.5, max=3, step=0.05).classes("flex-1")
                    pause_ms = ui.number("Pause between chunks (ms)", value=250, min=0, max=5_000, precision=0).classes("flex-1")
                    norm_loudness = ui.switch("Normalize loudness", value=True).classes("flex-1")

            def save_settings() -> None:
                state["settings"] = SynthesisSettings(
                    temperature=float(temperature.value),
                    seed=int(seed.value),
                    min_p=float(min_p.value),
                    top_p=float(top_p.value),
                    top_k=int(top_k.value),
                    repetition_penalty=float(repetition_penalty.value),
                    norm_loudness=bool(norm_loudness.value),
                    max_chunk_chars=int(max_chunk_chars.value),
                    pause_ms=int(pause_ms.value),
                )
                state["output_format"] = output_format.value
                ui.notify("Generation settings saved.", type="positive")

            _button("Save settings", save_settings, icon="save").classes("w-full")

            ui.separator()
            ui.label("Model connection").classes("vox-primary-heading text-lg font-medium")
            connection_type = ui.select(
                {
                    "service": "VoxBench model service",
                    "provider": "Generic provider API",
                },
                value=model_connection.settings.connection_type,
                label="Connection type",
            ).classes("w-full")
            with ui.column().classes("w-full gap-3") as service_fields:
                ui.label("The default connects to a local model service at 127.0.0.1:7861.").classes(
                    "vox-muted"
                )
                service_url = ui.input(
                    "Model service URL", value=model_connection.settings.service_url
                ).classes("w-full")
                service_api_key = ui.input(
                    "Model service API key (optional)",
                    placeholder=masked_secret(model_connection.settings.service_api_key),
                    password=True,
                ).classes("vox-secret-input w-full")
            with ui.column().classes("w-full gap-3") as provider_fields:
                ui.label("Use this only for a provider compatible with VoxBench's generic JSON adapter.").classes(
                    "vox-muted"
                )
                with ui.row().classes("w-full gap-3"):
                    provider_url = ui.input(
                        "Provider API URL", value=model_connection.settings.provider_url
                    ).classes("flex-1")
                    provider_model = ui.input(
                        "Provider model", value=model_connection.settings.provider_model
                    ).classes("flex-1")
                provider_api_key = ui.input(
                    "Provider API key",
                    placeholder=masked_secret(model_connection.settings.provider_api_key),
                    password=True,
                ).classes("vox-secret-input w-full")
            timeout_seconds = ui.number(
                "Request timeout (seconds)",
                value=model_connection.settings.timeout_seconds,
                min=1,
                precision=0,
            ).classes("w-full")

            def update_connection_fields() -> None:
                is_service = connection_type.value == "service"
                service_fields.set_visibility(is_service)
                provider_fields.set_visibility(not is_service)

            connection_type.on_value_change(update_connection_fields)
            update_connection_fields()

            def save_connection() -> None:
                try:
                    settings = ModelConnectionSettings(
                            connection_type=connection_type.value,
                            service_url=service_url.value.strip(),
                            service_api_key=updated_secret(
                                service_api_key.value,
                                model_connection.settings.service_api_key,
                            ),
                            timeout_seconds=float(timeout_seconds.value),
                            provider_url=provider_url.value.strip(),
                            provider_api_key=updated_secret(
                                provider_api_key.value,
                                model_connection.settings.provider_api_key,
                            ),
                            provider_model=provider_model.value.strip(),
                        )
                    model_connection.update(settings)
                except (RuntimeError, ValueError, VoxBenchError) as error:
                    ui.notify(str(error), type="negative")
                    return
                service_api_key.set_value("")
                provider_api_key.set_value("")
                service_api_key.props(
                    f"placeholder={masked_secret(settings.service_api_key)}"
                )
                provider_api_key.props(
                    f"placeholder={masked_secret(settings.provider_api_key)}"
                )
                ui.notify("Model connection saved.", type="positive")

            _button("Save model connection", save_connection, icon="save").classes("w-full")

        with ui.dialog().props("maximized") as advanced_dialog, ui.card().classes(
            "vox-card relative w-[96vw] max-w-none"
        ):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Advanced document editing").classes("vox-primary-heading text-xl font-medium")
                with ui.row().classes("items-center gap-3") as source_chapter_controls:
                    pdf_chapter_toggle = ui.checkbox(
                        "Use source chapters for output",
                        value=state["use_pdf_bookmarks"],
                    )
                    skip_pdf_toc = ui.checkbox(
                        "Skip printed table of contents",
                        value=state["skip_pdf_table_of_contents"],
                    )
                    pdf_chapter_depth = ui.select(
                        {
                            0: "Top level only",
                            1: "1 level deep",
                            2: "2 levels deep",
                            3: "3 levels deep",
                            4: "4 levels deep",
                        },
                        value=state["pdf_bookmark_depth"],
                        label="Chapter depth",
                    ).classes("w-44")
                _button("Close", advanced_dialog.close, icon="close")
            with ui.row().classes("w-full no-wrap gap-4"):
                with ui.column().classes("basis-[13%] min-w-[150px] gap-3"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Pages").classes("vox-primary-heading text-lg font-medium")
                        selected_count = ui.label("0 selected").classes("vox-muted text-sm")
                    section_table = ui.table(
                        columns=[
                            {"name": "page", "label": "Page", "field": "page", "align": "left"},
                        ],
                        rows=[],
                        row_key="id",
                        selection="multiple",
                    ).classes("vox-section-table w-full").style("height: 74vh")
                with ui.column().classes("basis-[35%] min-w-0 gap-3"):
                    ui.label("Parsed text").classes("vox-primary-heading text-lg font-medium")
                    editor = ui.textarea().classes("vox-document-editor w-full").props("outlined autogrow")
                    with ui.row().classes("w-full gap-2"):
                        restore_button = _button("Restore original")
                        ignore_empty_button = _button("Ignore empty", icon="block")
                        create_selected_button = _button("Create", icon="auto_awesome")
                    with ui.element("div").classes("vox-page-fixes w-full"):
                        ui.label("Apply before generating selected pages").classes("vox-muted text-sm")
                        with ui.row().classes("w-full gap-x-4 gap-y-1").props("wrap"):
                            fix_headers = ui.checkbox("Remove repeated headers/footers", value=True)
                            fix_artifacts = ui.checkbox("Clean extraction artifacts", value=True)
                            fix_hyphenation = ui.checkbox("Repair hyphenation", value=True)
                            fix_lines = ui.checkbox("Join broken lines", value=True)
                            fix_whitespace = ui.checkbox("Normalize whitespace", value=True)
                with ui.column().classes("basis-[52%] min-w-0"):
                    ui.label("Source document").classes("vox-primary-heading text-lg font-medium")
                    # The workspace sanitizes imported EPUB/Docx HTML before it is stored.
                    source = ui.html("").classes("w-full")

            with ui.row().classes("vox-global-page-counter items-center"):
                with ui.element("div").classes("vox-page-navigator") as page_navigator:
                    with ui.row().classes("items-center gap-2"):
                        page_input = ui.input(placeholder="Page").classes("w-20").props("type=number min=1")
                        page_total = ui.label("/ 0").classes("vox-muted")

            async def save_current_editor() -> None:
                document_id = state["document_id"]
                section_id = state.get("editor_section_id")
                if document_id and section_id:
                    await run.io_bound(
                        save_editor_section,
                        document_id,
                        section_id,
                        state.get("editor_section_title", ""),
                        editor.value or "",
                    )

            def set_ignore_button(ignored: bool) -> None:
                ignore_empty_button.classes(
                    add="vox-ignore-empty-active" if ignored else None,
                    remove=None if ignored else "vox-ignore-empty-active",
                )

            async def load_selected(
                document_id: str,
                section_id: str,
                selection_version: int,
            ) -> None:
                """Load a page only if it is still the most recent selection."""
                title, text, viewer = await run.io_bound(
                    load_editor_section, document_id, section_id
                )
                if (
                    selection_version != state["selection_version"]
                    or section_id != state.get("selected_section_id")
                ):
                    return
                state["editor_section_id"] = section_id
                state["editor_section_title"] = title
                editor.set_value(text)
                editor.update()
                source.content = viewer
                source.update()

            async def select_section(section_id: str, page: int, *, save_current: bool = True) -> None:
                state["selection_version"] += 1
                selection_version = state["selection_version"]
                if save_current:
                    await save_current_editor()
                if selection_version != state["selection_version"]:
                    return
                state["selected_section_id"] = section_id
                state["displayed_page"] = page
                page_input.set_value(str(page))
                await load_selected(state["document_id"], section_id, selection_version)

            async def reload_selected() -> None:
                document_id = state["document_id"]
                section_id = state.get("selected_section_id")
                if not document_id or not section_id:
                    return
                state["selection_version"] += 1
                await load_selected(document_id, section_id, state["selection_version"])

            async def select_table_row(event) -> None:
                row = event.args
                if isinstance(row, dict):
                    await select_section(row["id"], row["page"])

            def update_selected_count(event) -> None:
                selected_count.set_text(f"{len(event.selection)} selected")

            async def select_page() -> None:
                try:
                    page = int(page_input.value)
                except (TypeError, ValueError):
                    ui.notify("Enter a page number.", type="warning")
                    return
                if page == state.get("displayed_page"):
                    return
                rows = section_table.rows
                if not 1 <= page <= len(rows):
                    ui.notify(f"Enter a page from 1 to {len(rows)}.", type="warning")
                    return
                row = rows[page - 1]
                await select_section(row["id"], row["page"])

            async def scroll_pages(event) -> None:
                try:
                    wheel_delta = float(event.args)
                except (TypeError, ValueError):
                    return
                rows = section_table.rows
                current_page = int(state.get("displayed_page") or 1)
                target_page = max(1, min(len(rows), current_page + (1 if wheel_delta > 0 else -1)))
                if target_page == current_page:
                    return
                row = rows[target_page - 1]
                await select_section(row["id"], row["page"])

            async def restore_selected() -> None:
                if state["document_id"] and state.get("selected_section_id"):
                    text, _ = await run.io_bound(
                        restore_section, state["document_id"], state["selected_section_id"]
                    )
                    editor.set_value(text)
                    editor.update()
                    ui.notify("Original text restored.")

            async def toggle_ignore_empty_pages() -> None:
                document_id = state["document_id"]
                if not document_id:
                    return
                ignored = not state["ignore_empty_pages"]
                changed = await run.io_bound(set_empty_sections_ignored, document_id, ignored)
                state["ignore_empty_pages"] = ignored
                set_ignore_button(ignored)
                ui.notify(
                    f"Ignoring {changed} empty page(s) during creation."
                    if ignored
                    else f"Restored {changed} empty page(s).",
                    type="positive",
                )

            async def apply_generation_fixes(document_id: str, selected: list[str]) -> int:
                changed = 0
                if fix_headers.value:
                    changed += await run.io_bound(
                        remove_repeated_headers_footers, document_id, selected
                    )
                for enabled, operation in (
                    (fix_artifacts.value, "Clean extraction artifacts"),
                    (fix_hyphenation.value, "Repair hyphenation"),
                    (fix_lines.value, "Join broken lines"),
                    (fix_whitespace.value, "Normalize whitespace"),
                ):
                    if enabled:
                        changed += await run.io_bound(
                            apply_cleanup_to_sections, document_id, selected, operation
                        )
                return changed

            async def create_selected_pages() -> None:
                if state["busy"]:
                    return
                document_id = state["document_id"]
                selected = [row["id"] for row in section_table.selected]
                if not document_id or not selected:
                    ui.notify("Select at least one page to create an audiobook.", type="warning")
                    return
                if not ffmpeg_path or not ffprobe_path:
                    ui.notify("FFmpeg and FFprobe are required to assemble document chapters.", type="negative")
                    return
                await save_current_editor()
                state["busy"] = True
                create_button.disable()
                create_selected_button.disable()
                progress_bar.value = 0
                progress_percent.set_text("0.0%")
                state["progress"] = (0.0, "Starting selected-page generation")
                status.set_text("Starting selected-page generation…")

                def report(value: float, message: str) -> None:
                    state["progress"] = (max(0.0, min(1.0, value)), message)

                try:
                    changed = await apply_generation_fixes(document_id, selected)
                    if changed:
                        await reload_selected()
                    result = await run.io_bound(
                        create_audiobook,
                        backend=model_connection.backend,
                        document_path=None,
                        document_id=document_id,
                        section_ids=selected,
                        pasted_text=None,
                        reference_audio=state["reference_audio"] or state["default_reference_audio"],
                        settings=state["settings"],
                        ffmpeg_path=ffmpeg_path,
                        ffprobe_path=ffprobe_path,
                        output_directory=str(OUTPUTS_DIR),
                        output_format=state["output_format"],
                        use_pdf_bookmarks=state["use_pdf_bookmarks"],
                        pdf_bookmark_depth=state["pdf_bookmark_depth"],
                        skip_pdf_table_of_contents=state["skip_pdf_table_of_contents"],
                        progress=report,
                    )
                    show_output(result)
                    progress_bar.value = 1
                    progress_percent.set_text("100.0%")
                    status.set_text("Finished selected-page generation.")
                    ui.notify("Selected pages created.", type="positive")
                except (InferenceError, OSError, VoxBenchError) as error:
                    ui.notify(str(error), type="negative")
                    status.set_text("Selected-page generation failed.")
                finally:
                    state["busy"] = False
                    create_button.enable()
                    create_selected_button.enable()

            section_table.on("row-click", select_table_row, js_handler="(_, row) => emit(row)")
            pdf_chapter_toggle.on_value_change(
                lambda event: state.__setitem__("use_pdf_bookmarks", bool(event.value))
            )
            skip_pdf_toc.on_value_change(
                lambda event: state.__setitem__("skip_pdf_table_of_contents", bool(event.value))
            )
            pdf_chapter_depth.on_value_change(
                lambda event: state.__setitem__("pdf_bookmark_depth", int(event.value))
            )
            section_table.on_select(update_selected_count)
            page_input.on_value_change(select_page)
            page_navigator.on(
                "wheel",
                scroll_pages,
                js_handler="(event) => { event.preventDefault(); emit(event.deltaY); }",
            )
            restore_button.on_click(restore_selected)
            ignore_empty_button.on_click(toggle_ignore_empty_pages)
            create_selected_button.on_click(create_selected_pages)
            advanced_dialog.on("hide", save_current_editor)

        async def show_advanced() -> None:
            if not state["document_id"]:
                documents = await run.io_bound(list_documents)
                if not documents:
                    ui.notify("Upload a document before opening the editor.", type="warning")
                    return
                state["document_id"] = documents[0][1]
            rows = await run.io_bound(_section_rows, state["document_id"])
            manifest = await run.io_bound(load_manifest, state["document_id"])
            section_table.rows = rows
            section_table.selected = []
            section_table.update()
            selected_count.set_text("0 selected")
            page_total.set_text(f"/ {len(rows)}")
            set_ignore_button(state["ignore_empty_pages"])
            source_chapter_controls.set_visibility(manifest.get("source_type") in {".pdf", ".epub"})
            skip_pdf_toc.set_visibility(manifest.get("source_type") == ".pdf")
            state["selected_section_id"] = None
            state["editor_section_id"] = None
            state["editor_section_title"] = ""
            if rows:
                await select_section(rows[0]["id"], rows[0]["page"], save_current=False)
            advanced_dialog.open()

        advanced_button.on_click(show_advanced)
        settings_button.on_click(settings_dialog.open)
