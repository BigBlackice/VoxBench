import html
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph


MAX_DOCX_ENTRIES = 10_000
MAX_DOCX_BYTES = 250 * 1024 * 1024


class DocxError(ValueError):
    """Raised when a DOCX cannot be read safely."""


@dataclass(frozen=True)
class DocxSection:
    title: str
    text: str
    source_html: str


def _validate_package(source: Path) -> None:
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise DocxError("The DOCX contains too many files.")
            if any(entry.flag_bits & 0x1 for entry in entries):
                raise DocxError("Encrypted DOCX files are not supported.")
            if sum(entry.file_size for entry in entries) > MAX_DOCX_BYTES:
                raise DocxError("The expanded DOCX is too large.")
    except zipfile.BadZipFile as error:
        raise DocxError("The uploaded file is not a valid DOCX document.") from error


def _heading_level(paragraph: Paragraph) -> int | None:
    style = paragraph.style
    style_name = (style.name or "") if style is not None else ""
    style_id = (style.style_id or "") if style is not None else ""
    match = re.match(r"heading\s*([1-6])$", style_name, re.IGNORECASE)
    if match is None:
        match = re.match(r"heading([1-6])$", style_id, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _paragraph_html(paragraph: Paragraph, heading_level: int | None) -> str:
    text = html.escape(paragraph.text).replace("\n", "<br>")
    if not text:
        return ""
    tag = f"h{heading_level}" if heading_level else "p"
    return f"<{tag}>{text}</{tag}>"


def _table_content(table: Table) -> tuple[str, str]:
    text_rows = []
    html_rows = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells]
        if not any(cells):
            continue
        text_rows.append(" | ".join(cells))
        html_rows.append(
            "<tr>"
            + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells)
            + "</tr>"
        )
    return "\n".join(text_rows), (
        f"<table><tbody>{''.join(html_rows)}</tbody></table>" if html_rows else ""
    )


def read_docx_sections(source: Path) -> list[DocxSection]:
    """Read paragraphs and tables in order, splitting sections at headings."""
    _validate_package(source)
    try:
        document = Document(str(source))
    except (OSError, KeyError, ValueError, PackageNotFoundError) as error:
        raise DocxError("The uploaded DOCX could not be read.") from error

    default_title = (document.core_properties.title or "").strip() or "Document"
    sections: list[DocxSection] = []
    title = default_title
    text_blocks: list[str] = []
    html_blocks: list[str] = []

    def flush() -> None:
        nonlocal text_blocks, html_blocks
        text = "\n\n".join(block for block in text_blocks if block).strip()
        if text:
            sections.append(
                DocxSection(
                    title=title,
                    text=text,
                    source_html="".join(html_blocks),
                )
            )
        text_blocks = []
        html_blocks = []

    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            paragraph_text = block.text.strip()
            heading_level = _heading_level(block)
            if heading_level and paragraph_text:
                flush()
                title = paragraph_text
            if paragraph_text:
                text_blocks.append(paragraph_text)
                html_blocks.append(_paragraph_html(block, heading_level))
        elif isinstance(block, Table):
            table_text, table_html = _table_content(block)
            if table_text:
                text_blocks.append(table_text)
                html_blocks.append(table_html)

    flush()
    return sections
