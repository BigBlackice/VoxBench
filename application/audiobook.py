from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from inference.contract import InferenceBackend, SynthesisRequest
from webui.audio_processing import join_audio_chunks
from webui.chapter_assembly import assemble_chapters, create_batch_item
from webui.document_workspace import (
    clear_document_audio_paths,
    import_document,
    load_manifest,
    load_section,
    prepare_entire_document,
    save_document_audio,
)
from webui.errors import VoxBenchError
from webui.storage import save_generated_audio
from webui.text_processing import split_text


ProgressCallback = Callable[[float, str], None]
SUPPORTED_AUDIOBOOK_FORMATS = (".m4b", ".mp3", ".wav", ".m4a", ".ogg", ".webm")


@dataclass(frozen=True)
class SynthesisSettings:
    temperature: float = 0.8
    seed: int = 0
    min_p: float = 0.0
    top_p: float = 0.95
    top_k: int = 1000
    repetition_penalty: float = 1.2
    norm_loudness: bool = True
    max_chunk_chars: int = 300
    pause_ms: int = 250


@dataclass(frozen=True)
class AudiobookResult:
    output_path: Path
    document_id: str | None
    section_count: int


def _synthesize_text(
    backend: InferenceBackend,
    text: str,
    reference_audio: str | None,
    settings: SynthesisSettings,
    progress: ProgressCallback,
    progress_start: float,
    progress_span: float,
) -> tuple[int, np.ndarray]:
    chunks = split_text(text, settings.max_chunk_chars)
    if not chunks:
        raise VoxBenchError("There is no text to synthesize.")
    audio_chunks: list[np.ndarray] = []
    sample_rate = backend.sample_rate
    for index, chunk in enumerate(chunks, start=1):
        progress(
            progress_start + progress_span * (index - 1) / len(chunks),
            f"Generating chunk {index} of {len(chunks)}",
        )
        result = backend.synthesize(
            SynthesisRequest(
                text=chunk,
                audio_prompt_path=reference_audio,
                temperature=settings.temperature,
                seed=(settings.seed + index - 1) if settings.seed else 0,
                min_p=settings.min_p,
                top_p=settings.top_p,
                top_k=settings.top_k,
                repetition_penalty=settings.repetition_penalty,
                norm_loudness=settings.norm_loudness,
            )
        )
        if audio_chunks and result.sample_rate != sample_rate:
            raise VoxBenchError("The inference sample rate changed between chunks.")
        sample_rate = result.sample_rate
        audio_chunks.append(result.samples)
    progress(progress_start + progress_span, "Joining generated audio")
    return sample_rate, join_audio_chunks(audio_chunks, sample_rate, settings.pause_ms)


def create_audiobook(
    *,
    backend: InferenceBackend,
    document_path: str | None,
    pasted_text: str | None,
    reference_audio: str | None,
    settings: SynthesisSettings,
    ffmpeg_path: str | None,
    ffprobe_path: str | None,
    output_directory: str,
    document_id: str | None = None,
    section_ids: list[str] | None = None,
    output_format: str = ".m4b",
    progress: ProgressCallback = lambda _value, _message: None,
) -> AudiobookResult:
    """Create an audiobook, using document sections as chapter boundaries."""
    if output_format not in SUPPORTED_AUDIOBOOK_FORMATS:
        raise VoxBenchError("Unsupported audiobook format.")
    if document_path or document_id:
        if document_path:
            document_id = import_document(document_path)
        assert document_id is not None
        if section_ids is None:
            sections_to_generate = prepare_entire_document(document_id)
        else:
            manifest = load_manifest(document_id)
            known_ids = set(manifest["sections"])
            requested_ids = set(section_ids)
            if not requested_ids:
                raise VoxBenchError("Select at least one page to create an audiobook.")
            if not requested_ids <= known_ids:
                raise VoxBenchError("One or more selected pages are no longer available.")
            sections_to_generate = []
            for section_id in manifest["sections"]:
                if section_id not in requested_ids:
                    continue
                section = load_section(document_id, section_id)
                if section["status"] != "Skipped" and section["text"].strip():
                    sections_to_generate.append(section_id)
        if not sections_to_generate:
            raise VoxBenchError("The document contains no readable text.")
        generated_paths: list[Path] = []
        for section_index, section_id in enumerate(sections_to_generate, start=1):
            section = load_section(document_id, section_id)
            start = (section_index - 1) / len(sections_to_generate)
            sample_rate, audio = _synthesize_text(
                backend,
                section["text"],
                reference_audio,
                settings,
                progress,
                start,
                1 / len(sections_to_generate),
            )
            generated_paths.append(
                save_document_audio(document_id, section_id, audio, sample_rate)
            )
        if not ffmpeg_path or not ffprobe_path:
            raise VoxBenchError("FFmpeg and FFprobe are required to create an audiobook.")
        progress(1.0, "Assembling audiobook chapters")
        batch = [create_batch_item(str(path), ffprobe_path) for path in generated_paths]
        output = assemble_chapters(
            batch,
            "Silence",
            500,
            0.0,
            False,
            output_format,
            output_directory,
            ffmpeg_path,
        )
        for generated_path in generated_paths:
            try:
                generated_path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            clear_document_audio_paths(document_id, sections_to_generate)
        except (OSError, VoxBenchError):
            pass
        return AudiobookResult(output, document_id, len(sections_to_generate))

    if not pasted_text or not pasted_text.strip():
        raise VoxBenchError("Upload a document or paste text to begin.")
    sample_rate, audio = _synthesize_text(
        backend,
        pasted_text,
        reference_audio,
        settings,
        progress,
        0.0,
        1.0,
    )
    if output_format == ".m4b":
        if not ffmpeg_path or not ffprobe_path:
            raise VoxBenchError("FFmpeg and FFprobe are required for M4B output.")
        temporary_wav = save_generated_audio(
            audio, sample_rate, pasted_text, output_directory, ".wav", ffmpeg_path
        )
        try:
            progress(1.0, "Writing M4B chapter metadata")
            batch = [create_batch_item(str(temporary_wav), ffprobe_path)]
            output = assemble_chapters(
                batch,
                "Silence",
                0,
                0.0,
                False,
                ".m4b",
                output_directory,
                ffmpeg_path,
            )
        finally:
            temporary_wav.unlink(missing_ok=True)
    else:
        output = save_generated_audio(
            audio,
            sample_rate,
            pasted_text,
            output_directory,
            output_format,
            ffmpeg_path,
        )
    return AudiobookResult(output, None, 1)
