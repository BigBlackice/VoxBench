from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable, Iterator

import numpy as np
import soundfile as sf

from inference.contract import AudioResult, InferenceBackend, SynthesisRequest
from app_logic.audio_processing import join_audio_chunks
from app_logic.chapter_assembly import assemble_chapters, create_batch_item
from app_logic.workspace import (
    clear_document_audio_paths,
    import_document,
    load_manifest,
    load_section,
    prepare_entire_document,
    save_document_audio,
)
from webui.errors import VoxBenchError
from app_logic.storage import save_generated_audio
from app_logic.text_processing import split_text


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
) -> Iterator[tuple[int, np.ndarray, bool]]:
    """Yield validated generated chunks without retaining completed audio."""
    chunks = split_text(text, settings.max_chunk_chars)
    if not chunks:
        raise VoxBenchError("There is no text to synthesize.")
    sample_rate: int | None = None
    for index, chunk in enumerate(chunks, start=1):
        progress(
            progress_start + progress_span * (index - 1) / len(chunks),
            f"Generating chunk {index} of {len(chunks)}",
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
) -> tuple[int, Path]:
    """Stream one document section to WAV without retaining its chunks in RAM."""
    with NamedTemporaryFile(prefix="voxbench_section_", suffix=".wav", delete=False) as temporary:
        target = Path(temporary.name)
    sample_rate = backend.sample_rate
    writer: sf.SoundFile | None = None
    silence: np.ndarray | None = None
    try:
        for sample_rate, samples, has_previous in _synthesize_chunks(
            synthesize_chunk,
            text,
            reference_audio,
            settings,
            progress,
            progress_start,
            progress_span,
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
                silence = np.zeros(
                    round(sample_rate * settings.pause_ms / 1000.0),
                    dtype=np.float32,
                )
            elif has_previous and silence is not None and silence.size:
                writer.write(silence)
            writer.write(samples)
        progress(progress_start + progress_span, "Writing generated audio")
        return sample_rate, target
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
    output_format: str = ".m4b",
    progress: ProgressCallback = lambda _value, _message: None,
    synthesize_chunk: Callable[[SynthesisRequest], AudioResult] | None = None,
) -> AudiobookResult:
    """Create an audiobook, using document sections as chapter boundaries."""
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
        generated_paths: list[Path] = []
        try:
            for section_index, section_id in enumerate(sections_to_generate, start=1):
                section = load_section(document_id, section_id)
                start = (section_index - 1) / len(sections_to_generate)
                sample_rate, temporary_wav = _synthesize_text_to_wav(
                    backend,
                    synthesize_chunk,
                    section["text"],
                    reference_audio,
                    settings,
                    progress,
                    start,
                    1 / len(sections_to_generate),
                )
                try:
                    generated_paths.append(
                        save_document_audio(document_id, section_id, temporary_wav, sample_rate)
                    )
                except Exception:
                    temporary_wav.unlink(missing_ok=True)
                    raise
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
            return AudiobookResult(output, document_id, len(sections_to_generate))
        finally:
            for generated_path in generated_paths:
                try:
                    generated_path.unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                clear_document_audio_paths(document_id, sections_to_generate)
            except (OSError, VoxBenchError):
                pass

    if not pasted_text or not pasted_text.strip():
        raise VoxBenchError("Upload a document or paste text to begin.")
    sample_rate, audio = _synthesize_text(
        backend,
        synthesize_chunk,
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
            output_format=output_format,
            progress=progress,
            synthesize_chunk=synthesize_chunk,
        )
