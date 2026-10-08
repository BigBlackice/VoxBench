from contextlib import contextmanager
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile
from typing import Callable, Iterator

import numpy as np
import soundfile as sf

from inference.contract import AudioResult, InferenceBackend, SynthesisRequest
from app_logic.generation_control import GenerationController
from app_logic.audio_processing import join_audio_chunks
from app_logic.chapter_assembly import assemble_chapters, assemble_document_chapters, create_batch_item
from app_logic.workspace import (
    clear_document_audio_paths,
    document_generation_groups,
    import_document,
    load_manifest,
    load_section,
    prepare_entire_document,
    table_of_contents_section_ids,
)
from webui.errors import VoxBenchError
from app_logic.storage import resolve_output_directory, save_generated_audio, save_generated_wav
from app_logic.text_processing import split_text


ProgressCallback = Callable[[float, str], None]
SUPPORTED_AUDIOBOOK_FORMATS = (".m4b", ".mp3", ".wav", ".m4a", ".ogg", ".webm")
STREAM_PASTED_TEXT_AT_CHARS = 10_000


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
    incomplete: bool = False


class GenerationCancelled(VoxBenchError):
    """Raised at a safe chunk boundary when the user aborts generation."""

    def __init__(self, keep_partial: bool) -> None:
        super().__init__("Generation was aborted.")
        self.keep_partial = keep_partial


class _PartialGenerationCancelled(GenerationCancelled):
    def __init__(self, path: Path, sample_rate: int) -> None:
        super().__init__(True)
        self.path = path
        self.sample_rate = sample_rate


def _retain_incomplete_wavs(
    generated_paths: list[tuple[Path, str]], output_directory: str
) -> None:
    recovery_directory = resolve_output_directory(output_directory) / "incomplete"
    recovery_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for index, (path, _title) in enumerate(generated_paths, start=1):
        target = recovery_directory / f"{timestamp}_{index:04d}.wav"
        try:
            shutil.move(str(path), target)
        except OSError:
            pass


@contextmanager
def _reference_synthesizer(
    backend: InferenceBackend,
    reference_audio: str | None,
) -> Iterator[Callable[[SynthesisRequest], AudioResult]]:
    """Use a backend reference session when available, otherwise synthesize normally."""
    open_session = getattr(backend, "reference_session", None)
    if callable(open_session):
        with open_session(reference_audio) as synthesize:
            yield synthesize
        return
    yield backend.synthesize


def _synthesize_chunks(
    synthesize_chunk: Callable[[SynthesisRequest], AudioResult],
    text: str,
    reference_audio: str | None,
    settings: SynthesisSettings,
    progress: ProgressCallback,
    progress_start: float,
    progress_span: float,
    progress_label: str | None = None,
    generation_control: GenerationController | None = None,
) -> Iterator[tuple[int, np.ndarray, bool]]:
    """Yield validated generated chunks without retaining completed audio."""
    chunks = split_text(text, settings.max_chunk_chars)
    if not chunks:
        raise VoxBenchError("There is no text to synthesize.")
    sample_rate: int | None = None
    for index, chunk in enumerate(chunks, start=1):
        if generation_control and generation_control.is_paused():
            progress(progress_start, "Paused")
        if generation_control:
            generation_control.wait_if_paused()
            if generation_control.is_aborted():
                raise GenerationCancelled(generation_control.keep_partial())
        progress(
            progress_start + progress_span * (index - 1) / len(chunks),
            progress_label or f"Generating chunk {index} of {len(chunks)}",
        )
        result = synthesize_chunk(
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
        if sample_rate is not None and result.sample_rate != sample_rate:
            raise VoxBenchError("The inference sample rate changed between chunks.")
        sample_rate = result.sample_rate
        samples = np.asarray(result.samples, dtype=np.float32)
        del result
        yield sample_rate, samples, index > 1


def _synthesize_text(
    backend: InferenceBackend,
    synthesize_chunk: Callable[[SynthesisRequest], AudioResult],
    text: str,
    reference_audio: str | None,
    settings: SynthesisSettings,
    progress: ProgressCallback,
    progress_start: float,
    progress_span: float,
    generation_control: GenerationController | None = None,
) -> tuple[int, np.ndarray]:
    audio_chunks: list[np.ndarray] = []
    sample_rate = backend.sample_rate
    for sample_rate, samples, _has_previous in _synthesize_chunks(
        synthesize_chunk,
        text,
        reference_audio,
        settings,
        progress,
        progress_start,
        progress_span,
        generation_control=generation_control,
    ):
        audio_chunks.append(samples)
    progress(progress_start + progress_span, "Joining generated audio")
    return sample_rate, join_audio_chunks(audio_chunks, sample_rate, settings.pause_ms)


def _synthesize_text_to_wav(
    backend: InferenceBackend,
    synthesize_chunk: Callable[[SynthesisRequest], AudioResult],
    text: str,
    reference_audio: str | None,
    settings: SynthesisSettings,
    progress: ProgressCallback,
    progress_start: float,
    progress_span: float,
    generation_control: GenerationController | None = None,
) -> tuple[int, Path]:
    """Stream one text value to WAV without retaining its chunks in RAM."""
    return _synthesize_parts_to_wav(
        backend,
        synthesize_chunk,
        [(text, progress_start, progress_span, None, None)],
        reference_audio,
        settings,
        progress,
        generation_control=generation_control,
    )


def _synthesize_parts_to_wav(
    backend: InferenceBackend,
    synthesize_chunk: Callable[[SynthesisRequest], AudioResult],
    parts: list[tuple[str, float, float, str | None, int | None]],
    reference_audio: str | None,
    settings: SynthesisSettings,
    progress: ProgressCallback,
    end_silence_ms: int = 0,
    generation_control: GenerationController | None = None,
) -> tuple[int, Path]:
    """Stream ordered text parts into one WAV without retaining audio chunks."""
    with NamedTemporaryFile(prefix="voxbench_section_", suffix=".wav", delete=False) as temporary:
        target = Path(temporary.name)
    sample_rate = backend.sample_rate
    writer: sf.SoundFile | None = None
    silences: dict[int, np.ndarray] = {}
    has_audio = False
    try:
        for text, progress_start, progress_span, progress_label, pause_before_ms in parts:
            for sample_rate, samples, _has_previous in _synthesize_chunks(
                synthesize_chunk,
                text,
                reference_audio,
                settings,
                progress,
                progress_start,
                progress_span,
                progress_label,
                generation_control,
            ):
                if writer is None:
                    writer = sf.SoundFile(
                        target,
                        mode="w",
                        samplerate=sample_rate,
                        channels=1,
                        format="WAV",
                        subtype="PCM_16",
                    )
                elif has_audio:
                    pause_ms = (
                        pause_before_ms
                        if _has_previous is False and pause_before_ms is not None
                        else settings.pause_ms
                    )
                    silence = silences.get(pause_ms)
                    if silence is None:
                        silence = np.zeros(round(sample_rate * pause_ms / 1000.0), dtype=np.float32)
                        silences[pause_ms] = silence
                    if silence.size:
                        writer.write(silence)
                writer.write(samples)
                has_audio = True
        if generation_control and generation_control.is_aborted():
            raise GenerationCancelled(generation_control.keep_partial())
        if writer is not None and has_audio and end_silence_ms:
            silence = silences.get(end_silence_ms)
            if silence is None:
                silence = np.zeros(round(sample_rate * end_silence_ms / 1000.0), dtype=np.float32)
                silences[end_silence_ms] = silence
            if silence.size:
                writer.write(silence)
        progress(
            max(start + span for _text, start, span, _label, _pause in parts),
            "Writing generated audio",
        )
        return sample_rate, target
    except GenerationCancelled as error:
        if writer is not None:
            writer.close()
            writer = None
        if error.keep_partial and has_audio:
            raise _PartialGenerationCancelled(target, sample_rate) from error
        target.unlink(missing_ok=True)
        raise
    except Exception:
        if writer is not None:
            writer.close()
            writer = None
        target.unlink(missing_ok=True)
        raise
    finally:
        if writer is not None:
            writer.close()


def _create_audiobook(
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
    use_pdf_bookmarks: bool = True,
    pdf_bookmark_depth: int = 1,
    skip_pdf_table_of_contents: bool = True,
    output_format: str = ".m4b",
    progress: ProgressCallback = lambda _value, _message: None,
    synthesize_chunk: Callable[[SynthesisRequest], AudioResult] | None = None,
    generation_control: GenerationController | None = None,
) -> AudiobookResult:
    """Create an audiobook from editable document pages and output chapters."""
    synthesize_chunk = synthesize_chunk or backend.synthesize
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
        if skip_pdf_table_of_contents:
            contents_pages = set(table_of_contents_section_ids(document_id, sections_to_generate))
            sections_to_generate = [
                section_id for section_id in sections_to_generate if section_id not in contents_pages
            ]
        if not sections_to_generate:
            raise VoxBenchError("Only table-of-contents pages were selected.")
        groups = document_generation_groups(
            document_id,
            sections_to_generate,
            use_pdf_bookmarks=use_pdf_bookmarks,
            bookmark_depth=pdf_bookmark_depth,
        )
        generated_paths: list[tuple[Path, str]] = []
        completed = False
        retain_incomplete = True
        has_bookmark_chapters = any(group.get("is_bookmark") for group in groups)
        page_counts = Counter(
            page_index
            for group in groups
            for page_index in {part["page_index"] for part in group["parts"]}
        )
        part_slots: Counter[int] = Counter()
        try:
            bookmark_number = 0
            incomplete = False
            for group in groups:
                page_parts: dict[int, list[str]] = {}
                for part in group["parts"]:
                    page_parts.setdefault(part["page_index"], []).append(part["text"])
                parts: list[tuple[str, float, float, str | None, int | None]] = []
                is_bookmark = bool(group.get("is_bookmark"))
                if is_bookmark:
                    bookmark_number += 1
                    first_page = next(iter(page_parts))
                    page_slot = part_slots[first_page]
                    page_count = page_counts[first_page]
                    title_progress = (first_page - 1 + page_slot / page_count) / len(sections_to_generate)
                    parts.append(
                        (
                            f"Chapter {bookmark_number}: {group['title']}",
                            title_progress,
                            0.0,
                            f"Generating page {first_page} of {len(sections_to_generate)}",
                            None,
                        )
                    )
                for page_index, texts in page_parts.items():
                    slot = part_slots[page_index]
                    slots = page_counts[page_index]
                    part_slots[page_index] += 1
                    parts.append(
                        (
                            "\n\n".join(text for text in texts if text.strip()),
                            (page_index - 1 + slot / slots) / len(sections_to_generate),
                            1 / (len(sections_to_generate) * slots),
                            f"Generating page {page_index} of {len(sections_to_generate)}",
                            1000 if is_bookmark and len(parts) == 1 else 500 if is_bookmark else None,
                        )
                    )
                try:
                    _sample_rate, temporary_wav = _synthesize_parts_to_wav(
                        backend,
                        synthesize_chunk,
                        parts,
                        reference_audio,
                        settings,
                        progress,
                        end_silence_ms=2000 if is_bookmark else 500 if has_bookmark_chapters else 0,
                        generation_control=generation_control,
                    )
                except _PartialGenerationCancelled as error:
                    temporary_wav = error.path
                    incomplete = True
                except GenerationCancelled as error:
                    if not error.keep_partial or not generated_paths:
                        retain_incomplete = error.keep_partial
                        raise
                    incomplete = True
                    break
                generated_paths.append((temporary_wav, group["title"]))
                if incomplete:
                    break
            if not ffmpeg_path or not ffprobe_path:
                raise VoxBenchError("FFmpeg and FFprobe are required to create an audiobook.")
            progress(1.0, "Assembling audiobook chapters")
            batch = []
            for index, (path, title) in enumerate(generated_paths, start=1):
                batch.append(
                    create_batch_item(
                        str(path),
                        ffprobe_path,
                        title or f"Chapter {index}",
                    )
                )
            output = assemble_document_chapters(
                batch,
                0 if has_bookmark_chapters else 500,
                output_format,
                output_directory,
                ffmpeg_path,
            )
            completed = True
            return AudiobookResult(output, document_id, len(sections_to_generate), incomplete)
        finally:
            if completed or not retain_incomplete:
                for generated_path, _title in generated_paths:
                    try:
                        generated_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                try:
                    clear_document_audio_paths(document_id, sections_to_generate)
                except (OSError, VoxBenchError):
                    pass
            else:
                _retain_incomplete_wavs(generated_paths, output_directory)

    if not pasted_text or not pasted_text.strip():
        raise VoxBenchError("Upload a document or paste text to begin.")
    if len(pasted_text) >= STREAM_PASTED_TEXT_AT_CHARS or generation_control:
        incomplete = False
        try:
            _sample_rate, temporary_wav = _synthesize_text_to_wav(
                backend,
                synthesize_chunk,
                pasted_text,
                reference_audio,
                settings,
                progress,
                0.0,
                1.0,
                generation_control,
            )
        except _PartialGenerationCancelled as error:
            temporary_wav = error.path
            incomplete = True
        try:
            if output_format == ".m4b":
                if not ffmpeg_path or not ffprobe_path:
                    raise VoxBenchError("FFmpeg and FFprobe are required for M4B output.")
                progress(1.0, "Writing M4B chapter metadata")
                output = assemble_chapters(
                    [create_batch_item(str(temporary_wav), ffprobe_path)],
                    "Silence",
                    0,
                    0.0,
                    False,
                    ".m4b",
                    output_directory,
                    ffmpeg_path,
                )
            else:
                output = save_generated_wav(
                    temporary_wav,
                    pasted_text,
                    output_directory,
                    output_format,
                    ffmpeg_path,
                )
        finally:
            temporary_wav.unlink(missing_ok=True)
        return AudiobookResult(output, None, 1, incomplete)
    sample_rate, audio = _synthesize_text(
        backend,
        synthesize_chunk,
        pasted_text,
        reference_audio,
        settings,
        progress,
        0.0,
        1.0,
        generation_control,
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
    use_pdf_bookmarks: bool = True,
    pdf_bookmark_depth: int = 1,
    skip_pdf_table_of_contents: bool = True,
    output_format: str = ".m4b",
    progress: ProgressCallback = lambda _value, _message: None,
    generation_control: GenerationController | None = None,
) -> AudiobookResult:
    """Create an audiobook while keeping one reference session for the full batch."""
    with _reference_synthesizer(backend, reference_audio) as synthesize_chunk:
        return _create_audiobook(
            backend=backend,
            document_path=document_path,
            pasted_text=pasted_text,
            reference_audio=reference_audio,
            settings=settings,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            output_directory=output_directory,
            document_id=document_id,
            section_ids=section_ids,
            use_pdf_bookmarks=use_pdf_bookmarks,
            pdf_bookmark_depth=pdf_bookmark_depth,
            skip_pdf_table_of_contents=skip_pdf_table_of_contents,
            output_format=output_format,
            progress=progress,
            synthesize_chunk=synthesize_chunk,
            generation_control=generation_control,
        )
