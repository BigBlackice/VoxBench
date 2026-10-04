import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
from docx import Document

from tests.pdf_fixture import write_blank_pdf
from app_logic import workspace as document_workspace
from webui.errors import VoxBenchError


def write_epub(path: Path) -> None:
    container = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/package.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    package = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"
      properties="nav"/>
    <item id="opening" href="chapters/opening.xhtml"
      media-type="application/xhtml+xml"/>
    <item id="second" href="chapters/second%20chapter.xhtml"
      media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="nav"/>
    <itemref idref="opening"/>
    <itemref idref="second"/>
  </spine>
</package>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("EPUB/package.opf", package)
        archive.writestr(
            "EPUB/nav.xhtml",
            "<html><body><nav>Contents</nav></body></html>",
        )
        archive.writestr(
            "EPUB/chapters/opening.xhtml",
            "<html><body><h1>Opening</h1>"
            "<p>Hello document world.</p><script>unsafe()</script></body></html>",
        )
        archive.writestr(
            "EPUB/chapters/second chapter.xhtml",
            "<html><body><h2>Next chapter</h2><p>Second section.</p></body></html>",
        )


class DocumentWorkspaceTests(unittest.TestCase):
    def test_document_source_rejects_project_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(document_workspace, "DOCUMENTS_DIR", Path(directory) / "documents"):
                with self.assertRaises(VoxBenchError):
                    document_workspace.document_source_path("../../voxbench.json")

    def test_selects_an_inclusive_pdf_page_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            with patch.object(document_workspace, "DOCUMENTS_DIR", documents):
                document_id = "page_range"
                (documents / document_id).mkdir(parents=True)
                sections = [
                    document_workspace._new_section(
                        f"Page {page}", f"Text {page}", source_page=page
                    )
                    for page in range(1, 6)
                ]
                for section in sections:
                    document_workspace.save_section(document_id, section)
                document_workspace.save_manifest(
                    {
                        "id": document_id,
                        "sections": [item["id"] for item in sections],
                    }
                )

                selected = document_workspace.section_ids_in_page_range(
                    document_id, 2, 4
                )

                self.assertEqual(selected, [item["id"] for item in sections[1:4]])

    def test_applies_cleanup_to_selected_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            documents = root / "documents"
            with patch.object(document_workspace, "DOCUMENTS_DIR", documents):
                document_id = "batch_cleanup"
                (documents / document_id).mkdir(parents=True)
                sections = [
                    document_workspace._new_section("One", "First\nline"),
                    document_workspace._new_section("Two", "Second\nline"),
                ]
                for section in sections:
                    document_workspace.save_section(document_id, section)
                document_workspace.save_manifest(
                    {
                        "id": document_id,
                        "sections": [item["id"] for item in sections],
                    }
                )

                changed = document_workspace.apply_cleanup_to_sections(
                    document_id,
                    [sections[1]["id"]],
                    "Join broken lines",
                )

                self.assertEqual(changed, 1)
                self.assertEqual(
                    document_workspace.load_section(document_id, sections[0]["id"])[
                        "text"
                    ],
                    "First\nline",
                )
                self.assertEqual(
                    document_workspace.load_section(document_id, sections[1]["id"])[
                        "text"
                    ],
                    "Second line",
                )

    def test_ignores_an_empty_section_until_it_contains_text(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = Path(directory) / "documents"
            with patch.object(document_workspace, "DOCUMENTS_DIR", documents):
                document_id = "ignore_empty"
                (documents / document_id).mkdir(parents=True)
                section = document_workspace._new_section("Empty", "")
                document_workspace.save_section(document_id, section)
                document_workspace.save_manifest(
                    {"id": document_id, "sections": [section["id"]]}
                )

                self.assertEqual(
                    document_workspace.set_empty_sections_ignored(document_id, True), 1
                )
                document_workspace.save_editor_section(document_id, section["id"], "Empty", "")
                self.assertEqual(
                    document_workspace.load_section(document_id, section["id"])["status"], "Skipped"
                )

                self.assertEqual(
                    document_workspace.set_empty_sections_ignored(document_id, False), 1
                )
                self.assertEqual(
                    document_workspace.load_section(document_id, section["id"])["status"], "Needs review"
                )

                document_workspace.save_editor_section(document_id, section["id"], "Empty", "Has text")
                self.assertEqual(
                    document_workspace.load_section(document_id, section["id"])["status"], "Ready"
                )

    def test_removes_headers_only_from_selected_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            documents = Path(directory) / "documents"
            with patch.object(document_workspace, "DOCUMENTS_DIR", documents):
                document_id = "selected_headers"
                (documents / document_id).mkdir(parents=True)
                sections = [
                    document_workspace._new_section("One", "Header\nFirst"),
                    document_workspace._new_section("Two", "Header\nSecond"),
                    document_workspace._new_section("Three", "Header\nThird"),
                ]
                for section in sections:
                    document_workspace.save_section(document_id, section)
                document_workspace.save_manifest(
                    {"id": document_id, "sections": [section["id"] for section in sections]}
                )

                changed = document_workspace.remove_repeated_headers_footers(
                    document_id, [sections[0]["id"], sections[1]["id"]]
                )

                self.assertEqual(changed, 2)
                self.assertEqual(
                    document_workspace.load_section(document_id, sections[2]["id"])["text"],
                    "Header\nThird",
                )
    def test_imports_docx_headings_and_tables_as_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.docx"
            document = Document()
            document.core_properties.title = "Sample document"
            document.add_heading("Opening", level=1)
            document.add_paragraph("Hello from Word.")
            table = document.add_table(rows=1, cols=2)
            table.cell(0, 0).text = "Speaker"
            table.cell(0, 1).text = "Line"
            document.add_heading("Closing", level=1)
            document.add_paragraph("The end.")
            document.save(source)

            with patch.object(
                document_workspace,
                "DOCUMENTS_DIR",
                root / "documents",
            ):
                document_id = document_workspace.import_document(str(source))
                manifest = document_workspace.load_manifest(document_id)
                self.assertEqual(manifest["source_type"], ".docx")
                self.assertEqual(len(manifest["sections"]), 2)
                first = document_workspace.load_section(
                    document_id,
                    manifest["sections"][0],
                )
                second = document_workspace.load_section(
                    document_id,
                    manifest["sections"][1],
                )
                self.assertEqual(first["title"], "Opening")
                self.assertIn("Hello from Word.", first["text"])
                self.assertIn("Speaker | Line", first["text"])
                self.assertIn("<table>", first["source_html"])
                self.assertEqual(second["title"], "Closing")
                self.assertIn("The end.", second["text"])

    def test_imports_pdf_as_page_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "sample.pdf"
            write_blank_pdf(source, page_count=2)

            with patch.object(
                document_workspace,
                "DOCUMENTS_DIR",
                root / "documents",
            ):
                document_id = document_workspace.import_document(
                    str(source), source_name="Original Book.pdf"
                )
                manifest = document_workspace.load_manifest(document_id)
                self.assertEqual(manifest["source_type"], ".pdf")
                self.assertEqual(manifest["source_name"], "Original Book.pdf")
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
            write_epub(source)

            with patch.object(
                document_workspace,
                "DOCUMENTS_DIR",
                root / "documents",
            ):
                document_id = document_workspace.import_document(str(source))
                manifest = document_workspace.load_manifest(document_id)
                self.assertEqual(len(manifest["sections"]), 2)
                first = document_workspace.load_section(
                    document_id,
                    manifest["sections"][0],
                )
                second = document_workspace.load_section(
                    document_id,
                    manifest["sections"][1],
                )
                self.assertEqual(first["title"], "Opening")
                self.assertIn("Hello document world.", first["text"])
                self.assertNotIn("<script", first["source_html"])
                self.assertEqual(second["title"], "Next chapter")
                self.assertIn("Second section.", second["text"])

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
                document_workspace.clear_document_audio_paths(document_id, [section["id"]])
                self.assertIsNone(
                    document_workspace.load_section(document_id, section["id"])["audio_path"]
                )

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
