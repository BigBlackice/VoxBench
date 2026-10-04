import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium


class PdfError(ValueError):
    """Raised when a PDF cannot be read."""


@dataclass(frozen=True)
class PdfPage:
    number: int
    text: str


@dataclass(frozen=True)
class PdfChapter:
    title: str
    level: int
    page: int


def normalize_pdf_text(text: str) -> str:
    """Convert compatibility glyphs, including common ligatures, to text."""
    return unicodedata.normalize("NFKC", text)


def read_pdf_document(source: Path) -> tuple[list[PdfPage], list[PdfChapter]]:
    """Extract page text and bookmark metadata in one PDF pass."""
    try:
        document = pdfium.PdfDocument(source)
        try:
            chapters = []
            for bookmark in document.get_toc():
                destination = bookmark.get_dest()
                page_index = destination.get_index() if destination else None
                title = normalize_pdf_text(bookmark.get_title() or "").strip()
                if title and page_index is not None and 0 <= page_index < len(document):
                    chapters.append(
                        PdfChapter(title=title, level=bookmark.level, page=page_index + 1)
                    )
            pages = []
            for index in range(len(document)):
                page = document[index]
                try:
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_range()
                    finally:
                        text_page.close()
                finally:
                    page.close()
                pages.append(
                    PdfPage(number=index + 1, text=normalize_pdf_text(text))
                )
            return pages, chapters
        finally:
            document.close()
    except (OSError, pdfium.PdfiumError, ValueError) as error:
        raise PdfError("The uploaded PDF could not be read.") from error


def read_pdf_pages(source: Path) -> list[PdfPage]:
    """Extract text from each PDF page without changing page order."""
    return read_pdf_document(source)[0]


def pdf_page_count(source: Path) -> int:
    """Read a PDF's declared page count without extracting page text."""
    try:
        document = pdfium.PdfDocument(source)
        try:
            return len(document)
        finally:
            document.close()
    except (OSError, pdfium.PdfiumError, ValueError) as error:
        raise PdfError("The uploaded PDF could not be read.") from error
