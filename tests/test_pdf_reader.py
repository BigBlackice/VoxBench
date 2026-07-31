import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from webui.pdf_reader import PdfError, read_pdf_pages


class PdfReaderTests(unittest.TestCase):
    def test_preserves_page_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pages.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            writer.add_blank_page(width=300, height=300)
            with source.open("wb") as output:
                writer.write(output)

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
