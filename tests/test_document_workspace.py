import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from ebooklib import epub
from pypdf import PdfWriter

from webui import document_workspace


class DocumentWorkspaceTests(unittest.TestCase):
    def test_imports_pdf_as_page_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=300, height=300)
            writer.add_blank_page(width=300, height=300)
            with source.open("wb") as output:
                writer.write(output)

            with patch.object(
                document_workspace,
                "DOCUMENTS_DIR",
                root / "documents",
            ):
                document_id = document_workspace.import_document(str(source))
                manifest = document_workspace.load_manifest(document_id)
                self.assertEqual(manifest["source_type"], ".pdf")
                self.assertEqual(len(manifest["sections"]), 2)
                first = document_workspace.load_section(
                    document_id,
                    manifest["sections"][0],
                )
                self.assertEqual(first["title"], "Page 1")
                self.assertEqual(first["source_page"], 1)

    def test_imports_epub_spine_and_preserves_source_html(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.epub"
            book = epub.EpubBook()
            book.set_identifier("sample")
            book.set_title("Sample")
            book.set_language("en")
            chapter = epub.EpubHtml(
                title="Opening",
                file_name="chapter.xhtml",
                lang="en",
            )
            chapter.content = (
                "<html><body><h1>Opening</h1>"
                "<p>Hello document world.</p></body></html>"
            )
            book.add_item(chapter)
            book.add_item(epub.EpubNcx())
            book.add_item(epub.EpubNav())
            book.spine = ["nav", chapter]
            epub.write_epub(str(source), book)

            with patch.object(
                document_workspace,
                "DOCUMENTS_DIR",
                root / "documents",
            ):
                document_id = document_workspace.import_document(str(source))
                section_id = document_workspace.first_section_id(document_id)
                section = document_workspace.load_section(document_id, section_id)
                self.assertEqual(section["title"], "Opening")
                self.assertIn("Hello document world.", section["text"])
                self.assertNotIn("<script", section["source_html"])

    def test_edit_restore_search_and_restructure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            with patch.object(document_workspace, "DOCUMENTS_DIR", documents):
                document_id = "test_document"
                project = documents / document_id
                project.mkdir(parents=True)
                sections = [
                    document_workspace._new_section("One", "Hello world."),
                    document_workspace._new_section("Two", "Second section."),
                ]
                for section in sections:
                    document_workspace.save_section(document_id, section)
                document_workspace.save_manifest(
                    {
                        "id": document_id,
                        "title": "Test",
                        "source_name": "test.epub",
                        "source_path": str(project / "source.epub"),
                        "source_type": ".epub",
                        "created_at": "2026-01-01T00:00:00",
                        "sections": [item["id"] for item in sections],
                    }
                )

                document_workspace.save_editor_section(
                    document_id,
                    sections[0]["id"],
                    "Renamed",
                    "Hello edited world.",
                )
                count = document_workspace.replace_text(
                    document_id,
                    sections[0]["id"],
                    "world",
                    "book",
                    "Entire document",
                )
                self.assertEqual(count, 1)
                duplicate = document_workspace.restructure_section(
                    document_id,
                    sections[0]["id"],
                    "Duplicate",
                )
                self.assertEqual(
                    len(document_workspace.load_manifest(document_id)["sections"]),
                    3,
                )
                document_workspace.restructure_section(
                    document_id,
                    duplicate,
                    "Remove",
                )
                restored, status = document_workspace.restore_section(
                    document_id,
                    sections[0]["id"],
                )
                self.assertEqual(restored, "Hello world.")
                self.assertEqual(status, "Needs review")

    def test_entire_document_cleanup_skips_empty_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            with patch.object(document_workspace, "DOCUMENTS_DIR", documents):
                document_id = "cleanup_test"
                (documents / document_id).mkdir(parents=True)
                sections = [
                    document_workspace._new_section(
                        "One",
                        "Repeated header\nA hyphen-\nated line.\nRepeated footer",
                    ),
                    document_workspace._new_section(
                        "Two",
                        "Repeated header\n\nRepeated footer",
                    ),
                ]
                for section in sections:
                    document_workspace.save_section(document_id, section)
                document_workspace.save_manifest(
                    {
                        "id": document_id,
                        "title": "Cleanup",
                        "source_name": "cleanup.pdf",
                        "source_path": str(documents / document_id / "source.pdf"),
                        "source_type": ".pdf",
                        "created_at": "2026-01-01T00:00:00",
                        "sections": [item["id"] for item in sections],
                    }
                )
                ready = document_workspace.prepare_entire_document(document_id)
                self.assertEqual(ready, [sections[0]["id"]])
                first = document_workspace.load_section(
                    document_id,
                    sections[0]["id"],
                )
                second = document_workspace.load_section(
                    document_id,
                    sections[1]["id"],
                )
                self.assertEqual(first["text"], "A hyphenated line.")
                self.assertEqual(second["status"], "Skipped")

    def test_document_audio_is_saved_under_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            outputs = root / "outputs"
            with (
                patch.object(document_workspace, "DOCUMENTS_DIR", documents),
                patch.object(document_workspace, "OUTPUTS_DIR", outputs),
            ):
                document_id = "20260101_120000_test"
                (documents / document_id).mkdir(parents=True)
                section = document_workspace._new_section("Opening", "Hello")
                document_workspace.save_section(document_id, section)
                document_workspace.save_manifest(
                    {
                        "id": document_id,
                        "title": "Test book",
                        "source_name": "test.epub",
                        "source_path": str(documents / document_id / "source.epub"),
                        "source_type": ".epub",
                        "created_at": "2026-01-01T12:00:00",
                        "sections": [section["id"]],
                    }
                )
                target = document_workspace.save_document_audio(
                    document_id,
                    section["id"],
                    np.zeros(2400, dtype=np.float32),
                    24000,
                )
                self.assertEqual(target.parent, outputs)
                self.assertTrue(target.is_file())

    def test_clearing_documents_preserves_generated_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            project = documents / "stored_document"
            project.mkdir(parents=True)
            (project / "document.json").write_text("{}", encoding="utf-8")
            outputs = root / "outputs"
            outputs.mkdir()
            generated = outputs / "chapter.wav"
            generated.write_bytes(b"generated audio")

            with (
                patch.object(document_workspace, "PROJECT_DIR", root),
                patch.object(document_workspace, "DOCUMENTS_DIR", documents),
            ):
                removed = document_workspace.clear_document_projects()

            self.assertEqual(removed, 1)
            self.assertFalse(documents.exists())
            self.assertTrue(generated.is_file())


if __name__ == "__main__":
    unittest.main()
