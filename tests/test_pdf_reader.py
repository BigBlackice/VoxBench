import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app_logic import pdf_reader
from app_logic.pdf_reader import PdfError, normalize_pdf_text, pdf_page_count, read_pdf_document, read_pdf_pages
from tests.pdf_fixture import write_blank_pdf


class PdfReaderTests(unittest.TestCase):
    def test_reads_bookmark_title_level_and_destination(self):
        destination = MagicMock()
        destination.get_index.return_value = 0
        bookmark = MagicMock(level=1)
        bookmark.get_dest.return_value = destination
        bookmark.get_title.return_value = "Part" + chr(0xFB01) + "rst"
        text_page = MagicMock()
        text_page.get_text_range.return_value = "Page text"
        page = MagicMock()
        page.get_textpage.return_value = text_page
        document = MagicMock()
        document.__len__.return_value = 1
        document.__getitem__.return_value = page
        document.get_toc.return_value = [bookmark]

        with patch.object(pdf_reader.pdfium, "PdfDocument", return_value=document):
            pages, chapters = read_pdf_document(Path("book.pdf"))

        self.assertEqual(pages[0].text, "Page text")
        self.assertEqual([(chapter.title, chapter.level, chapter.page) for chapter in chapters], [
            ("Partfirst", 1, 1),
        ])

    def test_normalizes_standard_ligatures(self):
        text = (
            "o" + chr(0xFB03) + "ce " + chr(0xFB02) + "ows speci"
            + chr(0xFB01) + "c " + chr(0xFB00) + " " + chr(0xFB04)
            + " " + chr(0xFB05) + " " + chr(0xFB06)
        )
        self.assertEqual(normalize_pdf_text(text), "office flows specific ff ffl st st")

    def test_preserves_page_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pages.pdf"
            write_blank_pdf(source, page_count=2)

            pages = read_pdf_pages(source)

        self.assertEqual([page.number for page in pages], [1, 2])

    def test_reads_page_count_without_extracting_text(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pages.pdf"
            write_blank_pdf(source, page_count=3)
            self.assertEqual(pdf_page_count(source), 3)

    def test_rejects_invalid_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.pdf"
            source.write_bytes(b"not a pdf")
            with self.assertRaisesRegex(PdfError, "could not be read"):
                read_pdf_pages(source)


if __name__ == "__main__":
    unittest.main()
