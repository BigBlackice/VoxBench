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


def normalize_pdf_text(text: str) -> str:
    """Convert compatibility glyphs, including common ligatures, to text."""
    return unicodedata.normalize("NFKC", text)


def read_pdf_pages(source: Path) -> list[PdfPage]:
    """Extract text from each PDF page without changing page order."""
    try:
        document = pdfium.PdfDocument(source)
        try:
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
            return pages
        finally:
            document.close()
    except (OSError, pdfium.PdfiumError, ValueError) as error:
        raise PdfError("The uploaded PDF could not be read.") from error
