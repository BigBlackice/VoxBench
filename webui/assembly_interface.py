from pathlib import Path

import gradio as gr

from webui.chapter_assembly import (
    ASSEMBLY_FORMATS,
    assemble_chapters,
    batch_rows,
    create_batch_item,
    default_assembly_output,
    initial_folder,
    list_folder,
    move_batch_item,
    preview_processed_audio,
    remove_batch_item,
    select_folder_dialog,
    sync_browser_selection,
    update_batch_item,
)
from webui.config import FFMPEG_DOWNLOAD_URL, read_asset


BROWSER_HEADERS = ["Add", "Name"]
BATCH_HEADERS = [
    "Chapter",
    "File",
    "Seconds",
    "Volume dB",
    "EQ",
    "Trim start ms",
    "Trim end ms",
]


def build_assembly_interface(
    ffmpeg_path: str | None,
    ffprobe_path: str | None,
) -> tuple[gr.Blocks, str]:
    custom_css = read_asset("styles.css")
    tools_available = bool(ffmpeg_path and ffprobe_path)
    initial_path = initial_folder()
    initial_rows = list_folder(initial_path)[1]

    def refresh_folder(folder, batch):
        selected = {item["path"] for item in batch or []}
        resolved, rows = list_folder(folder, selected)
        return resolved, rows

    def browse_folder(folder, batch):
        selected = select_folder_dialog(folder)
        if not selected:
            return gr.skip(), gr.skip()
        return refresh_folder(selected, batch)

    def browser_input(rows, folder, batch):
        updated = sync_browser_selection(rows, folder, batch, ffprobe_path)
        selected = {item["path"] for item in updated}
        _, refreshed = list_folder(folder, selected)
        return updated, batch_rows(updated), refreshed

    def browser_select(rows, folder, batch, evt: gr.SelectData):
        if not evt.index or len(evt.index) < 2:
            return (
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )
        row_index, column_index = evt.index
        if column_index != 1 or row_index >= len(rows):
            return (
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )

        row = rows[row_index]
        path = str((Path(folder).resolve() / str(row[1])).resolve())
        match_index = next(
            (
                index
                for index, item in enumerate(batch or [])
                if str(Path(item["path"]).resolve()) == str(Path(path).resolve())
            ),
            -1,
        )
        item = (
            batch[match_index]
            if match_index >= 0
            else create_batch_item(path, ffprobe_path)
        )
        preview = preview_processed_audio(
            path,
            item["volume_db"],
            item["equalize"],
            item["trim_start_ms"],
            item["trim_end_ms"],
            ffmpeg_path,
            ffprobe_path,
        )
        return (
            folder,
            rows,
            path,
            preview,
            item["volume_db"],
            item["equalize"],
            item["trim_start_ms"],
            item["trim_end_ms"],
            match_index,
        )

    def select_batch(batch, evt: gr.SelectData):
        if not evt.index:
            return (
                -1,
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )
        row_index = evt.index[0] if isinstance(evt.index, (list, tuple)) else evt.index
        if row_index < 0 or row_index >= len(batch or []):
            return (
                -1,
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )
        item = batch[row_index]
        preview = preview_processed_audio(
            item["path"],
            item["volume_db"],
            item["equalize"],
            item["trim_start_ms"],
            item["trim_end_ms"],
            ffmpeg_path,
            ffprobe_path,
        )
        return (
            row_index,
            item["path"],
            preview,
            item["volume_db"],
            item["equalize"],
            item["trim_start_ms"],
            item["trim_end_ms"],
        )

    def preview_changes(
        path,
        volume_db,
        equalize,
        trim_start,
        trim_end,
        batch_volume,
        batch_equalize,
    ):
        if not path:
            raise gr.Error("Select an audio file to preview.")
        return preview_processed_audio(
            path,
            float(volume_db) + float(batch_volume),
            bool(equalize) or bool(batch_equalize),
            trim_start,
            trim_end,
            ffmpeg_path,
            ffprobe_path,
        )

    def apply_item(batch, index, volume, equalize, trim_start, trim_end):
        updated = update_batch_item(
            batch,
            int(index),
            volume,
            equalize,
            trim_start,
            trim_end,
        )
        return updated, batch_rows(updated)

    def move_item(batch, index, offset):
        updated, selected = move_batch_item(batch, int(index), offset)
        return updated, batch_rows(updated), selected

    def remove_item(batch, index, folder):
        updated, selected = remove_batch_item(batch, int(index))
        _, rows = refresh_folder(folder, updated)
        return updated, batch_rows(updated), selected, rows

    def export(
        batch,
        transition_mode,
        transition_ms,
        batch_volume,
        batch_equalize,
        output_format,
        output_directory,
    ):
        target = assemble_chapters(
            batch,
            transition_mode,
            transition_ms,
            batch_volume,
            batch_equalize,
            output_format,
            output_directory,
            ffmpeg_path,
        )
        gr.Info(f"Saved assembled audio to {target}")
        return str(target), str(target)

    with gr.Blocks(title="Chapter assembly") as demo:
        gr.Markdown("# Chapter assembly")
        gr.Markdown(
            "Select files in order, preview and adjust them, then export one "
            "chaptered audio file."
        )
        if not tools_available:
            gr.Markdown(
                f"Assembly requires [FFmpeg]({FFMPEG_DOWNLOAD_URL}) and FFprobe."
            )

        batch_state = gr.State([])
        selected_batch_index = gr.State(-1)
        preview_source = gr.State(None)

        with gr.Row():
            with gr.Column(scale=3):
                with gr.Row():
                    folder = gr.Textbox(
                        value=initial_path,
                        label="Folder",
                        scale=5,
                        interactive=tools_available,
                    )
                    open_folder = gr.Button(
                        "Open",
                        interactive=tools_available,
                        scale=1,
                    )
                    browse_folder_button = gr.Button(
                        "Browse",
                        interactive=tools_available,
                        scale=1,
                    )
                browser = gr.Dataframe(
                    value=initial_rows,
                    headers=BROWSER_HEADERS,
                    datatype=["bool", "str"],
                    type="array",
                    label="Audio files — check Add to append; click a name to preview",
                    interactive=tools_available,
                    row_count=0,
                    column_count=2,
                    max_height=420,
                    wrap=True,
                )

            with gr.Column(scale=2):
                preview = gr.Audio(
                    label="Preview",
                    type="filepath",
                    interactive=False,
                    waveform_options={"show_recording_waveform": True},
                    elem_classes=["audio-waveform"],
                )
                with gr.Row():
                    preview_volume = gr.Slider(
                        -24,
                        12,
                        value=0,
                        step=0.5,
                        label="File volume (dB)",
                        interactive=tools_available,
                    )
                    preview_equalize = gr.Checkbox(
                        value=False,
                        label="Speech EQ",
                        interactive=tools_available,
                    )
                with gr.Row():
                    trim_start = gr.Number(
                        value=0,
                        minimum=0,
                        precision=0,
                        label="Trim start (ms)",
                        interactive=tools_available,
                    )
                    trim_end = gr.Number(
                        value=0,
                        minimum=0,
                        precision=0,
                        label="Trim end (ms)",
                        interactive=tools_available,
                    )
                with gr.Row():
                    preview_button = gr.Button(
                        "Preview changes",
                        interactive=tools_available,
                    )
                    apply_button = gr.Button(
                        "Apply to selected chapter",
                        variant="primary",
                        interactive=tools_available,
                    )

        batch_table = gr.Dataframe(
            value=[],
            headers=BATCH_HEADERS,
            datatype=["str", "str", "number", "number", "str", "number", "number"],
            type="array",
            label="Sequential chapter list",
            interactive=False,
            row_count=0,
            column_count=7,
            max_height=320,
            wrap=True,
        )
        with gr.Row():
            move_up = gr.Button("Move up", interactive=tools_available)
            move_down = gr.Button("Move down", interactive=tools_available)
            remove = gr.Button("Remove", interactive=tools_available)

        with gr.Group():
            gr.Markdown("### Final assembly")
            with gr.Row():
                transition_mode = gr.Radio(
                    choices=["Silence", "Crossfade"],
                    value="Silence",
                    label="Between chapters",
                    interactive=tools_available,
                )
                transition_ms = gr.Slider(
                    0,
                    5000,
                    value=500,
                    step=25,
                    label="Interval (ms)",
                    interactive=tools_available,
                )
            with gr.Row():
                batch_volume = gr.Slider(
                    -24,
                    12,
                    value=0,
                    step=0.5,
                    label="Batch volume (dB)",
                    interactive=tools_available,
                )
                batch_equalize = gr.Checkbox(
                    value=False,
                    label="Equalize entire batch",
                    interactive=tools_available,
                )
            gr.Markdown(
                "M4B exposes embedded chapters in VLC. MP3 contains ID3 "
                "chapter metadata, but VLC does not read it. WAV is lossless "
                "and has no reliable embedded chapter support."
            )
            with gr.Row():
                output_format = gr.Radio(
                    choices=[
                        ("M4B — VLC chapters", ".m4b"),
                        ("MP3 — VLC ignores chapters", ".mp3"),
                        ("WAV — no reliable chapters", ".wav"),
                    ],
                    value=".m4b",
                    label="Output format",
                    interactive=tools_available,
                )
                output_directory = gr.Textbox(
                    value=default_assembly_output(),
                    label="Output folder",
                    interactive=tools_available,
                )
            assemble_button = gr.Button(
                "Assemble and export",
                variant="primary",
                interactive=tools_available,
            )
            final_audio = gr.Audio(
                label="Assembled audio",
                type="filepath",
                elem_classes=["audio-waveform"],
            )
            final_download = gr.File(label="Download assembled file")

        open_folder.click(
            fn=refresh_folder,
            inputs=[folder, batch_state],
            outputs=[folder, browser],
        )
        folder.submit(
            fn=refresh_folder,
            inputs=[folder, batch_state],
            outputs=[folder, browser],
        )
        browse_folder_button.click(
            fn=browse_folder,
            inputs=[folder, batch_state],
            outputs=[folder, browser],
        )
        browser.input(
            fn=browser_input,
            inputs=[browser, folder, batch_state],
            outputs=[batch_state, batch_table, browser],
        )
        browser.select(
            fn=browser_select,
            inputs=[browser, folder, batch_state],
            outputs=[
                folder,
                browser,
                preview_source,
                preview,
                preview_volume,
                preview_equalize,
                trim_start,
                trim_end,
                selected_batch_index,
            ],
        )
        batch_table.select(
            fn=select_batch,
            inputs=batch_state,
            outputs=[
                selected_batch_index,
                preview_source,
                preview,
                preview_volume,
                preview_equalize,
                trim_start,
                trim_end,
            ],
        )
        preview_button.click(
            fn=preview_changes,
            inputs=[
                preview_source,
                preview_volume,
                preview_equalize,
                trim_start,
                trim_end,
                batch_volume,
                batch_equalize,
            ],
            outputs=preview,
        )
        apply_button.click(
            fn=apply_item,
            inputs=[
                batch_state,
                selected_batch_index,
                preview_volume,
                preview_equalize,
                trim_start,
                trim_end,
            ],
            outputs=[batch_state, batch_table],
        )
        move_up.click(
            fn=lambda batch, index: move_item(batch, index, -1),
            inputs=[batch_state, selected_batch_index],
            outputs=[batch_state, batch_table, selected_batch_index],
        )
        move_down.click(
            fn=lambda batch, index: move_item(batch, index, 1),
            inputs=[batch_state, selected_batch_index],
            outputs=[batch_state, batch_table, selected_batch_index],
        )
        remove.click(
            fn=remove_item,
            inputs=[batch_state, selected_batch_index, folder],
            outputs=[batch_state, batch_table, selected_batch_index, browser],
        )
        assemble_button.click(
            fn=export,
            inputs=[
                batch_state,
                transition_mode,
                transition_ms,
                batch_volume,
                batch_equalize,
                output_format,
                output_directory,
            ],
            outputs=[final_audio, final_download],
        )

    return demo, custom_css
