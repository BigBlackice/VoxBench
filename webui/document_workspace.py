import html
import json
import re
import shutil
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import gradio as gr
import soundfile as sf
from bs4 import BeautifulSoup
from ebooklib import epub
from pypdf import PdfReader

from webui.config import OUTPUTS_DIR, PROJECT_DIR


DOCUMENTS_DIR = PROJECT_DIR / "documents"
SUPPORTED_DOCUMENT_EXTENSIONS = {".pdf", ".epub"}
SPLIT_MARKER = "[[SPLIT HERE]]"
SAFE_EPUB_TAGS = {
    "p",
    "div",
    "span",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "ul",
    "ol",
    "li",
    "em",
    "strong",
    "b",
    "i",
    "br",
    "hr",
    "pre",
    "code",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
}


def _safe_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._-")
    return value[:80] or "document"


def _project_path(document_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", document_id or ""):
        raise gr.Error("Invalid document project.")
    path = (DOCUMENTS_DIR / document_id).resolve()
    if DOCUMENTS_DIR.resolve() not in path.parents:
        raise gr.Error("Invalid document project.")
    return path


def _manifest_path(document_id: str) -> Path:
    return _project_path(document_id) / "document.json"


def load_manifest(document_id: str) -> dict[str, Any]:
    path = _manifest_path(document_id)
    if not path.is_file():
        raise gr.Error("Document project not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(manifest: dict[str, Any]) -> None:
    path = _manifest_path(manifest["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _section_path(document_id: str, section_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{12}", section_id or ""):
        raise gr.Error("Invalid document section.")
    return _project_path(document_id) / "sections" / f"{section_id}.json"


def load_section(document_id: str, section_id: str) -> dict[str, Any]:
    path = _section_path(document_id, section_id)
    if not path.is_file():
        raise gr.Error("Document section not found.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_section(document_id: str, section: dict[str, Any]) -> None:
    path = _section_path(document_id, section["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(section, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _new_section(
    title: str,
    text: str,
    source_html: str = "",
    source_page: int | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "original_text": text,
        "text": text,
        "source_html": source_html,
        "source_page": source_page,
        "status": "Needs review",
        "audio_path": None,
    }


def _clean_extracted_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _safe_epub_html(content: bytes) -> tuple[str, str, str | None]:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "iframe", "object", "embed", "form"]):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.name not in SAFE_EPUB_TAGS:
            tag.unwrap()
            continue
        tag.attrs = {}

    heading = soup.find(["h1", "h2", "h3"])
    title = heading.get_text(" ", strip=True) if heading else None
    text = _clean_extracted_text(soup.get_text("\n"))
    return text, str(soup), title


def _extract_pdf(source: Path) -> list[dict[str, Any]]:
    reader = PdfReader(str(source))
    sections = []
    for index, page in enumerate(reader.pages, start=1):
        text = _clean_extracted_text(page.extract_text() or "")
        sections.append(
            _new_section(
                title=f"Page {index}",
                text=text,
                source_page=index,
            )
        )
    return sections


def _extract_epub(source: Path) -> list[dict[str, Any]]:
    book = epub.read_epub(str(source))
    sections = []
    seen: set[str] = set()

    for idref, _ in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or not hasattr(item, "get_content"):
            continue
        if isinstance(item, epub.EpubNav):
            continue
        item_name = item.get_name()
        if item_name in seen:
            continue
        seen.add(item_name)
        text, source_html, detected_title = _safe_epub_html(item.get_content())
        if not text:
            continue
        title = detected_title or f"Chapter {len(sections) + 1}"
        sections.append(
            _new_section(
                title=title,
                text=text,
                source_html=source_html,
            )
        )
    return sections


def import_document(file_path: str) -> str:
    source = Path(file_path).resolve()
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise gr.Error("Upload a PDF or EPUB file.")

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    base = _safe_name(source.stem)
    document_id = f"{datetime.now():%Y%m%d_%H%M%S}_{base}"
    counter = 2
    while (_project_path(document_id)).exists():
        document_id = f"{datetime.now():%Y%m%d_%H%M%S}_{base}_{counter}"
        counter += 1

    project = _project_path(document_id)
    project.mkdir(parents=True)
    stored_source = project / f"source{source.suffix.lower()}"
    shutil.copy2(source, stored_source)

    try:
        sections = (
            _extract_pdf(stored_source)
            if source.suffix.lower() == ".pdf"
            else _extract_epub(stored_source)
        )
        if not sections:
            raise gr.Error("No readable text sections were found.")
        for section in sections:
            save_section(document_id, section)
        save_manifest(
            {
                "id": document_id,
                "title": source.stem,
                "source_name": source.name,
                "source_path": str(stored_source),
                "source_type": source.suffix.lower(),
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "sections": [section["id"] for section in sections],
            }
        )
    except Exception:
        shutil.rmtree(project, ignore_errors=True)
        raise
    return document_id


def list_documents() -> list[tuple[str, str]]:
    if not DOCUMENTS_DIR.is_dir():
        return []
    documents = []
    for manifest_path in DOCUMENTS_DIR.glob("*/document.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            documents.append((manifest["title"], manifest["id"]))
        except (OSError, KeyError, json.JSONDecodeError):
            continue
    return sorted(documents, key=lambda item: item[1], reverse=True)


def clear_document_projects() -> int:
    """Remove all imported document projects without touching generated output."""
    documents_path = DOCUMENTS_DIR.resolve()
    project_path = PROJECT_DIR.resolve()
    if documents_path != project_path / "documents":
        raise gr.Error("Refusing to clear an unexpected document directory.")
    if not documents_path.exists():
        return 0

    project_count = sum(
        1
        for path in documents_path.iterdir()
        if path.is_dir() and (path / "document.json").is_file()
    )
    try:
        shutil.rmtree(documents_path)
    except OSError as error:
        raise gr.Error(f"Could not clear stored document data: {error}") from error
    return project_count


def outline_rows(document_id: str, selected: set[str] | None = None) -> list[list[Any]]:
    manifest = load_manifest(document_id)
    selected = selected or set()
    rows = []
    for index, section_id in enumerate(manifest["sections"], start=1):
        section = load_section(document_id, section_id)
        text = section["text"]
        rows.append(
            [
                section_id in selected,
                index,
                section["title"],
                len(text.split()),
                len(text),
                section["status"],
            ]
        )
    return rows


def first_section_id(document_id: str) -> str:
    manifest = load_manifest(document_id)
    return manifest["sections"][0]


def source_view_html(document_id: str, section: dict[str, Any]) -> str:
    manifest = load_manifest(document_id)
    if manifest["source_type"] == ".pdf":
        page = section.get("source_page") or 1
        return (
            '<iframe class="document-source-frame" '
            f'src="/document-source/{html.escape(document_id)}#page={page}" '
            'title="PDF source"></iframe>'
        )
    return (
        '<article class="document-source-epub">'
        f'{section.get("source_html") or "<p>No source preview available.</p>"}'
        "</article>"
    )


def load_editor_section(
    document_id: str,
    section_id: str,
) -> tuple[str, str, str]:
    section = load_section(document_id, section_id)
    return section["title"], section["text"], source_view_html(document_id, section)


def save_editor_section(
    document_id: str,
    section_id: str,
    title: str,
    text: str,
) -> None:
    section = load_section(document_id, section_id)
    section["title"] = title.strip() or section["title"]
    section["text"] = _clean_extracted_text(text)
    section["status"] = "Ready"
    save_section(document_id, section)


def restore_section(document_id: str, section_id: str) -> tuple[str, str]:
    section = load_section(document_id, section_id)
    section["text"] = section["original_text"]
    section["status"] = "Needs review"
    save_section(document_id, section)
    return section["text"], section["status"]


def clean_text(text: str, operation: str) -> str:
    if operation == "Join broken lines":
        return re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    if operation == "Repair hyphenation":
        return re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    if operation == "Normalize whitespace":
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    raise gr.Error("Unknown cleanup operation.")


def remove_repeated_headers_footers(document_id: str) -> int:
    manifest = load_manifest(document_id)
    sections = [load_section(document_id, item) for item in manifest["sections"]]
    if len(sections) < 2:
        return 0

    def edge(section: dict[str, Any], first: bool) -> str:
        lines = [line.strip() for line in section["text"].splitlines() if line.strip()]
        return (lines[0] if first else lines[-1]) if lines else ""

    candidates = []
    for first in (True, False):
        counts: dict[str, int] = {}
        for section in sections:
            value = edge(section, first)
            if value:
                counts[value] = counts.get(value, 0) + 1
        candidates.extend(
            value for value, count in counts.items() if count >= 2
        )

    changed = 0
    for section in sections:
        lines = section["text"].splitlines()
        original = list(lines)
        while lines and lines[0].strip() in candidates:
            lines.pop(0)
        while lines and lines[-1].strip() in candidates:
            lines.pop()
        if lines != original:
            section["text"] = "\n".join(lines).strip()
            section["status"] = "Needs review"
            save_section(document_id, section)
            changed += 1
    return changed


def prepare_entire_document(document_id: str) -> list[str]:
    """Apply all cleanup operations and return non-empty sections in order."""
    remove_repeated_headers_footers(document_id)
    manifest = load_manifest(document_id)
    ready: list[str] = []
    operations = [
        "Repair hyphenation",
        "Join broken lines",
        "Normalize whitespace",
    ]
    for section_id in manifest["sections"]:
        section = load_section(document_id, section_id)
        text = section["text"]
        for operation in operations:
            text = clean_text(text, operation)
        section["text"] = text.strip()
        if section["text"]:
            section["status"] = "Ready"
            ready.append(section_id)
        else:
            section["status"] = "Skipped"
            section["audio_path"] = None
        save_section(document_id, section)
    return ready


def replace_text(
    document_id: str,
    section_id: str,
    search: str,
    replacement: str,
    scope: str,
) -> int:
    if not search:
        raise gr.Error("Enter text to search for.")
    manifest = load_manifest(document_id)
    targets = (
        manifest["sections"] if scope == "Entire document" else [section_id]
    )
    total = 0
    for target in targets:
        section = load_section(document_id, target)
        count = section["text"].count(search)
        if count:
            section["text"] = section["text"].replace(search, replacement)
            section["status"] = "Needs review"
            save_section(document_id, section)
            total += count
    return total


def restructure_section(
    document_id: str,
    section_id: str,
    action: str,
) -> str:
    manifest = load_manifest(document_id)
    section_ids = manifest["sections"]
    index = section_ids.index(section_id)
    section = load_section(document_id, section_id)

    if action == "Move up" or action == "Move down":
        offset = -1 if action == "Move up" else 1
        target = min(max(index + offset, 0), len(section_ids) - 1)
        section_ids[index], section_ids[target] = section_ids[target], section_ids[index]
        save_manifest(manifest)
        return section_id

    if action == "Duplicate":
        duplicate = dict(section)
        duplicate["id"] = uuid.uuid4().hex[:12]
        duplicate["title"] = f'{section["title"]} copy'
        duplicate["audio_path"] = None
        duplicate["status"] = "Needs review"
        save_section(document_id, duplicate)
        section_ids.insert(index + 1, duplicate["id"])
        save_manifest(manifest)
        return duplicate["id"]

    if action == "Remove":
        if len(section_ids) == 1:
            raise gr.Error("A document must retain at least one section.")
        section_ids.pop(index)
        _section_path(document_id, section_id).unlink(missing_ok=True)
        save_manifest(manifest)
        return section_ids[min(index, len(section_ids) - 1)]

    if action in {"Merge previous", "Merge next"}:
        other_index = index - 1 if action == "Merge previous" else index + 1
        if other_index < 0 or other_index >= len(section_ids):
            raise gr.Error("There is no adjacent section to merge.")
        first_index, second_index = sorted((index, other_index))
        first = load_section(document_id, section_ids[first_index])
        second = load_section(document_id, section_ids[second_index])
        first["text"] = f'{first["text"]}\n\n{second["text"]}'.strip()
        first["original_text"] = (
            f'{first["original_text"]}\n\n{second["original_text"]}'.strip()
        )
        first["status"] = "Needs review"
        first["audio_path"] = None
        save_section(document_id, first)
        section_ids.pop(second_index)
        _section_path(document_id, second["id"]).unlink(missing_ok=True)
        save_manifest(manifest)
        return first["id"]

    if action == "Split":
        if SPLIT_MARKER not in section["text"]:
            raise gr.Error(f"Insert {SPLIT_MARKER} at the desired split point.")
        first_text, second_text = section["text"].split(SPLIT_MARKER, 1)
        if not first_text.strip() or not second_text.strip():
            raise gr.Error("The split marker must have text on both sides.")
        section["text"] = first_text.strip()
        section["status"] = "Needs review"
        section["audio_path"] = None
        save_section(document_id, section)
        created = _new_section(
            f'{section["title"]} (continued)',
            second_text.strip(),
            section.get("source_html", ""),
            section.get("source_page"),
        )
        save_section(document_id, created)
        section_ids.insert(index + 1, created["id"])
        save_manifest(manifest)
        return created["id"]

    raise gr.Error("Unknown section action.")


def selected_section_ids(
    document_id: str,
    rows: list[list[Any]] | None,
) -> list[str]:
    manifest = load_manifest(document_id)
    rows = rows or []
    return [
        section_id
        for section_id, row in zip(manifest["sections"], rows)
        if row and bool(row[0])
    ]


def document_source_path(document_id: str) -> Path:
    manifest = load_manifest(document_id)
    source = Path(manifest["source_path"]).resolve()
    project = _project_path(document_id)
    if project not in source.parents or not source.is_file():
        raise FileNotFoundError
    return source


def save_document_audio(
    document_id: str,
    section_id: str,
    audio,
    sample_rate: int,
) -> Path:
    manifest = load_manifest(document_id)
    section = load_section(document_id, section_id)
    order = manifest["sections"].index(section_id) + 1
    output_dir = OUTPUTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    document_prefix = f"{document_id[:15]}_{_safe_name(manifest['title'])}"
    target = output_dir / (
        f"{document_prefix}_{order:04d}_{_safe_name(section['title'])}.wav"
    )
    audio_data = audio.detach().cpu().float().numpy() if hasattr(audio, "detach") else audio
    sf.write(target, audio_data, sample_rate, format="WAV", subtype="PCM_16")
    section["audio_path"] = str(target.resolve())
    section["status"] = "Generated"
    save_section(document_id, section)
    return target
