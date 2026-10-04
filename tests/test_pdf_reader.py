import tempfile
import unittest
from pathlib import Path

from tests.pdf_fixture import write_blank_pdf
from app_logic.pdf_reader import PdfError, normalize_pdf_text, read_pdf_pages


class PdfReaderTests(unittest.TestCase):
    def test_normalizes_standard_ligatures(self):
        self.assertEqual(
            normalize_pdf_text("oﬃce ﬂows speciﬁc ﬀ ﬄ ﬅ ﬆ"),
            "office flows specific ff ffl st st",
        )

    def test_preserves_page_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pages.pdf"
            write_blank_pdf(source, page_count=2)

            pages = read_pdf_pages(source)

        self.assertEqual([page.number for page in pages], [1, 2])

    def test_rejects_invalid_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.pdf"
            source.write_bytes(b"not a pdf")
            with self.assertRaisesRegex(PdfError, "could not be read"):
                read_pdf_pages(source)


if __name__ == "__main__":
    unittest.main()
