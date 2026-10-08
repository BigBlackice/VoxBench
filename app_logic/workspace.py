import html
import json
import re
import shutil
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from webui.errors import VoxBenchError
import soundfile as sf
from bs4 import BeautifulSoup

from webui.config import OUTPUTS_DIR, PROJECT_DIR
from app_logic.docx_reader import DocxError, read_docx_sections
from app_logic.epub_reader import EpubError, EpubNavigation, read_epub_document
from app_logic.pdf_reader import PdfChapter, PdfError, pdf_page_count, read_pdf_document


DOCUMENTS_DIR = PROJECT_DIR / "documents"
SUPPORTED_DOCUMENT_EXTENSIONS = {".docx", ".epub", ".pdf"}
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
BOOKMARK_MATCH_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)
EXTRACTION_CLEANUP_TRANSLATION = str.maketrans(
    {
        "\u00a0": " ",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
    }
)


def _safe_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._-")
    return value[:80] or "document"


def _project_path(document_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", document_id or ""):
        raise VoxBenchError("Invalid document project.")
    path = (DOCUMENTS_DIR / document_id).resolve()
    if DOCUMENTS_DIR.resolve() not in path.parents:
        raise VoxBenchError("Invalid document project.")
    return path


def _manifest_path(document_id: str) -> Path:
    return _project_path(document_id) / "document.json"


def load_manifest(document_id: str) -> dict[str, Any]:
    path = _manifest_path(document_id)
    if not path.is_file():
        raise VoxBenchError("Document project not found.")
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
        raise VoxBenchError("Invalid document section.")
    return _project_path(document_id) / "sections" / f"{section_id}.json"


def load_section(document_id: str, section_id: str) -> dict[str, Any]:
    path = _section_path(document_id, section_id)
    if not path.is_file():
        raise VoxBenchError("Document section not found.")
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
    chapter_title: str | None = None,
    chapter_level: int | None = None,
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "original_text": text,
        "text": text,
        "source_html": source_html,
        "source_page": source_page,
        "chapter_title": chapter_title,
        "chapter_level": chapter_level,
        "status": "Needs review",
        "audio_path": None,
    }


def _clean_extracted_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _bookmark_match_text(text: str) -> str:
    """Normalize common typographic variants without altering saved text."""
    return text.translate(BOOKMARK_MATCH_TRANSLATION)


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


def _split_epub_navigation(
    content: bytes,
    entries: list[EpubNavigation],
) -> list[tuple[EpubNavigation | None, bytes]]:
    """Split one EPUB spine item at its table-of-contents anchors."""
    if not entries:
        return [(None, content)]

    # BeautifulSoup honors an EPUB document's declared encoding (including UTF-16).
    source = BeautifulSoup(content, "html.parser").decode()
    boundaries: list[tuple[int, EpubNavigation]] = []
    for entry in entries:
        if not entry.fragment:
            boundaries.append((0, entry))
            continue
        match = re.search(
            r"<[^>]*\b(?:id|name)\s*=\s*(['\"])"
            + re.escape(entry.fragment)
            + r"\1[^>]*>",
            source,
            re.IGNORECASE,
        )
        if match:
            boundaries.append((match.start(), entry))
    if not boundaries:
        return [(entries[0], content)]
    if min(offset for offset, _entry in boundaries) > 0:
        boundaries.append((0, entries[0]))

    unique_boundaries: list[tuple[int, EpubNavigation]] = []
    for offset, entry in sorted(boundaries, key=lambda item: item[0]):
        if not unique_boundaries or offset != unique_boundaries[-1][0]:
            unique_boundaries.append((offset, entry))
    return [
        (entry, source[offset:next_offset].encode("utf-8"))
        for (offset, entry), (next_offset, _next_entry) in zip(
            unique_boundaries,
            unique_boundaries[1:] + [(len(source), unique_boundaries[-1][1])],
        )
    ]


def _pdf_page_sections(pages: list[Any]) -> list[dict[str, Any]]:
    return [
        _new_section(
            title=f"Page {page.number}",
            text=_clean_extracted_text(page.text),
            source_page=page.number,
        )
        for page in pages
    ]


def _extract_pdf(source: Path) -> list[dict[str, Any]]:
    try:
        pages, _chapters = read_pdf_document(source)
    except PdfError as error:
        raise VoxBenchError(str(error)) from error
    return _pdf_page_sections(pages)


def _extract_docx(source: Path) -> list[dict[str, Any]]:
    try:
        sections = read_docx_sections(source)
    except DocxError as error:
        raise VoxBenchError(str(error)) from error
    return [
        _new_section(
            title=section.title,
            text=_clean_extracted_text(section.text),
            source_html=section.source_html,
        )
        for section in sections
    ]


def _extract_epub(source: Path) -> list[dict[str, Any]]:
    sections = []
    try:
        chapters, navigation = read_epub_document(source)
    except EpubError as error:
        raise VoxBenchError(str(error)) from error

    navigation_by_path: dict[str, list[EpubNavigation]] = {}
    for entry in navigation:
        navigation_by_path.setdefault(entry.path, []).append(entry)
    for chapter in chapters:
        for entry, content in _split_epub_navigation(
            chapter.content,
            navigation_by_path.get(chapter.path, []),
        ):
            text, source_html, detected_title = _safe_epub_html(content)
            if not text:
                continue
            title = (entry.title if entry else None) or detected_title or f"Chapter {len(sections) + 1}"
            sections.append(
                _new_section(
                    title=title,
                    text=text,
                    source_html=source_html,
                    chapter_title=entry.title if entry else None,
                    chapter_level=entry.level if entry else None,
                )
            )
    return sections


def import_document(file_path: str, source_name: str | None = None) -> str:
    source = Path(file_path).resolve()
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
        raise VoxBenchError("Upload a PDF, EPUB, or DOCX file.")
    display_name = Path(source_name or source.name).name

    DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)
    base = _safe_name(Path(display_name).stem)
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
        source_type = source.suffix.lower()
        extractors = {
            ".docx": _extract_docx,
            ".epub": _extract_epub,
        }
        pdf_bookmarks: list[PdfChapter] = []
        if source_type == ".pdf":
            try:
                pages, pdf_bookmarks = read_pdf_document(stored_source)
            except PdfError as error:
                raise VoxBenchError(str(error)) from error
            sections = _pdf_page_sections(pages)
        else:
            sections = extractors[source_type](stored_source)
        if not sections:
            raise VoxBenchError("No readable text sections were found.")
        for section in sections:
            save_section(document_id, section)
        save_manifest(
            {
                "id": document_id,
                "title": Path(display_name).stem,
                "source_name": display_name,
                "source_path": str(stored_source),
                "source_type": source_type,
                "pdf_bookmarks": [
                    {"title": item.title, "level": item.level, "page": item.page}
                    for item in pdf_bookmarks
                ],
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


def document_page_count(document_id: str) -> int:
    """Return the source PDF page count, or section count for reflowable files."""
    manifest = load_manifest(document_id)
    if manifest.get("source_type") != ".pdf":
        return len(manifest["sections"])
    try:
        return pdf_page_count(Path(manifest["source_path"]))
    except (KeyError, PdfError):
        return len(manifest["sections"])


def _bookmark_pattern(title: str) -> re.Pattern[str] | None:
    words = _bookmark_match_text(title).split()
    if not words:
        return None
    number = r"\d+(?:\.\d+)*(?:\.)?"
    return re.compile(
        r"(?<!\w)(?:"
        + number
        + r"[ \t]+)?"
        + r"\s+".join(re.escape(word) for word in words)
        + r"(?:[ \t]+"
        + number
        + r")?(?!\w)",
        re.IGNORECASE,
    )


def _pdf_bookmark_parts(
    text: str,
    bookmarks: list[PdfChapter],
) -> list[tuple[str | None, str]]:
    """Return page text fragments, with a title where a bookmark begins."""
    parts: list[tuple[str | None, str]] = []
    match_text = _bookmark_match_text(text)
    cursor = 0
    found_boundary = False
    for bookmark in bookmarks:
        pattern = _bookmark_pattern(bookmark.title)
        match = pattern.search(match_text, cursor) if pattern else None
        if match is not None:
            before = text[cursor:match.start()].strip()
            if before:
                parts.append((None, before))
            parts.append((bookmark.title, ""))
            cursor = match.end()
            found_boundary = True
        elif not found_boundary:
            parts.append((bookmark.title, ""))
            found_boundary = True
    tail = text[cursor:].strip()
    if tail:
        parts.append((None, tail))
    return parts or [(None, text)]


def _without_leading_chapter_title(text: str, title: str) -> str:
    pattern = _bookmark_pattern(title)
    match = pattern.match(_bookmark_match_text(text)) if pattern else None
    return text[match.end():].lstrip() if match else text


def _manifest_pdf_bookmarks(manifest: dict[str, Any]) -> list[PdfChapter]:
    bookmarks = []
    for item in manifest.get("pdf_bookmarks", []):
        try:
            bookmarks.append(PdfChapter(item["title"], int(item["level"]), int(item["page"])))
        except (KeyError, TypeError, ValueError):
            continue
    return bookmarks


def table_of_contents_section_ids(
    document_id: str,
    section_ids: list[str],
) -> list[str]:
    """Return selected PDF or EPUB sections that strongly match a printed contents page."""
    manifest = load_manifest(document_id)
    source_type = manifest.get("source_type")
    if source_type not in {".pdf", ".epub"}:
        return []
    if source_type == ".pdf":
        bookmarks = _manifest_pdf_bookmarks(manifest)
        titles = [bookmark.title for bookmark in bookmarks]
    else:
        bookmarks = []
        titles = [
            str(load_section(document_id, section_id).get("chapter_title") or "")
            for section_id in manifest["sections"]
        ]
    patterns = [pattern for title in titles if (pattern := _bookmark_pattern(title))]
    if not patterns:
        return []
    first_chapter_page = None
    if bookmarks:
        top_level = min(item.level for item in bookmarks)
        first_chapter_page = min(item.page for item in bookmarks if item.level == top_level)
    selected = set(section_ids)
    skipped = []
    for section_id in manifest["sections"]:
        if section_id not in selected:
            continue
        section = load_section(document_id, section_id)
        if first_chapter_page is not None and int(section.get("source_page") or 0) >= first_chapter_page:
            continue
        text = section.get("original_text") or section["text"]
        leader_lines = sum(
            bool(re.search(r"(?:\.\s*){3,}\d+\s*$", line))
            for line in text.splitlines()
        )
        title_matches = sum(
            bool(pattern and pattern.search(_bookmark_match_text(text)))
            for pattern in patterns
        )
        if leader_lines >= 2 and title_matches >= 3:
            skipped.append(section_id)
    return skipped


def document_generation_groups(
    document_id: str,
    section_ids: list[str],
    *,
    use_pdf_bookmarks: bool,
    bookmark_depth: int,
) -> list[dict[str, Any]]:
    """Group editable pages into output chapters without changing the editor."""
    manifest = load_manifest(document_id)
    selected = set(section_ids)
    ordered_selected = [item for item in manifest["sections"] if item in selected]
    if not ordered_selected:
        return []
    page_positions = {section_id: index for index, section_id in enumerate(ordered_selected, start=1)}

    def page_groups() -> list[dict[str, Any]]:
        groups = []
        for section_id in ordered_selected:
            section = load_section(document_id, section_id)
            groups.append(
                {
                    "title": section["title"],
                    "is_bookmark": False,
                    "parts": [{
                        "section_id": section_id,
                        "page_index": page_positions[section_id],
                        "text": section["text"],
                    }],
                }
            )
        return groups

    if not use_pdf_bookmarks:
        return page_groups()

    if manifest.get("source_type") == ".epub":
        groups: list[dict[str, Any]] = []
        current_title: str | None = None
        current_is_bookmark = False
        current_parts: list[dict[str, Any]] = []

        def finish_group() -> None:
            nonlocal current_parts
            if current_parts:
                groups.append(
                    {
                        "title": current_title or "Untitled chapter",
                        "is_bookmark": current_is_bookmark,
                        "parts": current_parts,
                    }
                )
            current_parts = []

        for section_id in manifest["sections"]:
            section = load_section(document_id, section_id)
            title = section.get("chapter_title")
            level = section.get("chapter_level")
            try:
                is_chapter = bool(title) and int(level) <= max(0, int(bookmark_depth))
            except (TypeError, ValueError):
                is_chapter = False
            if section_id not in selected:
                finish_group()
                if is_chapter:
                    current_title = title
                    current_is_bookmark = True
                continue
            if is_chapter:
                finish_group()
                current_title = title
                current_is_bookmark = True
            if current_title is None:
                groups.append(
                    {
                        "title": section["title"],
                        "is_bookmark": False,
                        "parts": [{
                            "section_id": section_id,
                            "page_index": page_positions[section_id],
                            "text": section["text"],
                        }],
                    }
                )
                continue
            current_parts.append(
                {
                    "section_id": section_id,
                    "page_index": page_positions[section_id],
                    "text": _without_leading_chapter_title(section["text"], title)
                    if is_chapter else section["text"],
                }
            )
        finish_group()
        return groups

    if manifest.get("source_type") != ".pdf":
        return page_groups()

    bookmarks_by_page: dict[int, list[PdfChapter]] = {}
    for bookmark in _manifest_pdf_bookmarks(manifest):
        if bookmark.level <= max(0, int(bookmark_depth)):
            bookmarks_by_page.setdefault(bookmark.page, []).append(bookmark)
    if not bookmarks_by_page:
        return page_groups()

    groups: list[dict[str, Any]] = []
    current_title: str | None = None
    current_is_bookmark = False
    current_parts: list[dict[str, Any]] = []

    def finish_group() -> None:
        nonlocal current_parts
        if current_parts:
            groups.append(
                {
                    "title": current_title or "Untitled chapter",
                    "is_bookmark": current_is_bookmark,
                    "parts": current_parts,
                }
            )
        current_parts = []

    for section_id in manifest["sections"]:
        section = load_section(document_id, section_id)
        source_page = int(section.get("source_page") or 0)
        parts = _pdf_bookmark_parts(
            section["text"],
            bookmarks_by_page.get(source_page, []),
        )
        if section_id not in selected:
            finish_group()
            for title, _text in parts:
                if title:
                    current_title = title
                    current_is_bookmark = True
            continue
        for title, text in parts:
            if title:
                finish_group()
                current_title = title
                current_is_bookmark = True
            if not text:
                continue
            if current_title is None:
                current_title = section["title"]
                current_is_bookmark = False
            current_parts.append(
                {
                    "section_id": section_id,
                    "page_index": page_positions[section_id],
                    "text": text,
                }
            )
    finish_group()
    return groups


def clear_document_projects() -> int:
    """Remove all imported document projects without touching generated output."""
    documents_path = DOCUMENTS_DIR.resolve()
    project_path = PROJECT_DIR.resolve()
    if documents_path != project_path / "documents":
        raise VoxBenchError("Refusing to clear an unexpected document directory.")
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
        raise VoxBenchError(f"Could not clear stored document data: {error}") from error
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
                "⋮⋮",
                section_id in selected,
                index,
                section["title"],
                len(text.split()),
                len(text),
                section["status"],
            ]
        )
    return rows


def reorder_sections(document_id: str, order: list[int]) -> None:
    manifest = load_manifest(document_id)
    section_ids = manifest["sections"]
    expected = list(range(1, len(section_ids) + 1))
    if sorted(order) != expected:
        raise VoxBenchError("The document queue returned an invalid section order.")
    manifest["sections"] = [section_ids[index - 1] for index in order]
    save_manifest(manifest)


def first_section_id(document_id: str) -> str:
    manifest = load_manifest(document_id)
    return manifest["sections"][0]


def source_view_html(document_id: str, section: dict[str, Any]) -> str:
    manifest = load_manifest(document_id)
    if manifest["source_type"] == ".pdf":
        page = section.get("source_page") or 1
        return (
            '<iframe class="document-source-frame" '
            f'src="/document-source/{html.escape(document_id)}#page={page}&amp;zoom=75" '
            'title="PDF source"></iframe>'
        )
    return (
        '<article class="document-source-document">'
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
    if section["status"] != "Skipped" or section["text"]:
        section["status"] = "Ready"
    save_section(document_id, section)


def restore_section(document_id: str, section_id: str) -> tuple[str, str]:
    section = load_section(document_id, section_id)
    section["text"] = section["original_text"]
    section["status"] = "Needs review"
    save_section(document_id, section)
    return section["text"], section["status"]


def set_empty_sections_ignored(document_id: str, ignored: bool) -> int:
    """Set the skipped state for every empty section in a document."""
    changed = 0
    manifest = load_manifest(document_id)
    for section_id in manifest["sections"]:
        section = load_section(document_id, section_id)
        if section["text"].strip():
            continue
        target_status = "Skipped" if ignored else "Needs review"
        if section["status"] == target_status:
            continue
        section["status"] = target_status
        if ignored:
            section["audio_path"] = None
        save_section(document_id, section)
        changed += 1
    return changed


def clean_text(text: str, operation: str) -> str:
    if operation == "Clean extraction artifacts":
        text = text.translate(EXTRACTION_CLEANUP_TRANSLATION)
        text = "".join(
            character
            for character in text
            if not (0xFDD0 <= ord(character) <= 0xFDEF or ord(character) & 0xFFFE == 0xFFFE)
        )
        return re.sub(r"(?m)^[ \t]*[•◦▪‣][ \t]*", "", text)
    if operation == "Join broken lines":
        return re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    if operation == "Repair hyphenation":
        return re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    if operation == "Normalize whitespace":
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    raise VoxBenchError("Unknown cleanup operation.")


def apply_cleanup_to_sections(
    document_id: str,
    section_ids: list[str],
    operation: str,
) -> int:
    """Apply one cleanup operation to selected sections and save the result."""
    if not section_ids:
        raise VoxBenchError("Select at least one section.")
    changed = 0
    for section_id in section_ids:
        section = load_section(document_id, section_id)
        cleaned = clean_text(section["text"], operation)
        if cleaned != section["text"]:
            section["text"] = cleaned
            section["status"] = "Needs review"
            save_section(document_id, section)
            changed += 1
    return changed


def section_ids_in_page_range(
    document_id: str,
    first_page: int,
    last_page: int,
) -> list[str]:
    """Return PDF section IDs whose source pages fall in an inclusive range."""
    if first_page < 1 or last_page < first_page:
        raise VoxBenchError("Enter a valid page range, such as 300 to 500.")
    manifest = load_manifest(document_id)
    matches = [
        section_id
        for section_id in manifest["sections"]
        if (page := load_section(document_id, section_id).get("source_page"))
        is not None
        and first_page <= page <= last_page
    ]
    if not matches:
        raise VoxBenchError("No PDF pages were found in that range.")
    return matches


def remove_repeated_headers_footers(
    document_id: str,
    section_ids: list[str] | None = None,
) -> int:
    manifest = load_manifest(document_id)
    requested_ids = set(section_ids) if section_ids is not None else None
    if requested_ids is not None and not requested_ids <= set(manifest["sections"]):
        raise VoxBenchError("One or more selected sections are no longer available.")
    sections = [
        load_section(document_id, item)
        for item in manifest["sections"]
        if requested_ids is None or item in requested_ids
    ]
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
        "Clean extraction artifacts",
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
        raise VoxBenchError("Enter text to search for.")
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
            raise VoxBenchError("A document must retain at least one section.")
        section_ids.pop(index)
        _section_path(document_id, section_id).unlink(missing_ok=True)
        save_manifest(manifest)
        return section_ids[min(index, len(section_ids) - 1)]

    if action in {"Merge previous", "Merge next"}:
        other_index = index - 1 if action == "Merge previous" else index + 1
        if other_index < 0 or other_index >= len(section_ids):
            raise VoxBenchError("There is no adjacent section to merge.")
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
            raise VoxBenchError(f"Insert {SPLIT_MARKER} at the desired split point.")
        first_text, second_text = section["text"].split(SPLIT_MARKER, 1)
        if not first_text.strip() or not second_text.strip():
            raise VoxBenchError("The split marker must have text on both sides.")
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

    raise VoxBenchError("Unknown section action.")


def selected_section_ids(
    document_id: str,
    rows: list[list[Any]] | None,
) -> list[str]:
    manifest = load_manifest(document_id)
    rows = rows or []
    return [
        section_id
        for section_id, row in zip(manifest["sections"], rows)
        if row and bool(row[1])
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
    if isinstance(audio, (str, Path)):
        source = Path(audio)
        if not source.is_file():
            raise VoxBenchError("Generated section audio could not be found.")
        try:
            source.replace(target)
        except OSError:
            target.unlink(missing_ok=True)
            shutil.move(str(source), str(target))
    else:
        audio_data = audio.detach().cpu().float().numpy() if hasattr(audio, "detach") else audio
        sf.write(target, audio_data, sample_rate, format="WAV", subtype="PCM_16")
    section["audio_path"] = str(target.resolve())
    section["status"] = "Generated"
    save_section(document_id, section)
    return target


def clear_document_audio_paths(document_id: str, section_ids: list[str]) -> None:
    """Clear temporary per-section audio references after final assembly."""
    for section_id in section_ids:
        section = load_section(document_id, section_id)
        section["audio_path"] = None
        save_section(document_id, section)
