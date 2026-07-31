from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfError(ValueError):
    """Raised when a PDF cannot be read."""


@dataclass(frozen=True)
class PdfPage:
    number: int
    text: str


def read_pdf_pages(source: Path) -> list[PdfPage]:
    """Extract text from each PDF page without changing page order."""
    try:
        reader = PdfReader(str(source))
        return [
            PdfPage(number=index, text=page.extract_text() or "")
            for index, page in enumerate(reader.pages, start=1)
        ]
    except (OSError, PdfReadError, ValueError) as error:
        raise PdfError("The uploaded PDF could not be read.") from error
