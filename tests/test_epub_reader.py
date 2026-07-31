import tempfile
import unittest
import zipfile
from pathlib import Path

from webui.epub_reader import EpubError, read_epub_spine


CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="book/package.opf"
      media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""


def write_minimal_epub(path: Path, package: str, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("book/package.opf", package)
        for name, content in files.items():
            archive.writestr(name, content)


class EpubReaderTests(unittest.TestCase):
    def test_reads_spine_order_and_skips_navigation(self):
        package = """<package xmlns="http://www.idpf.org/2007/opf">
          <manifest>
            <item id="two" href="two.xhtml" media-type="application/xhtml+xml"/>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"
              properties="nav"/>
            <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
          </manifest>
          <spine>
            <itemref idref="one"/>
            <itemref idref="nav"/>
            <itemref idref="two"/>
          </spine>
        </package>"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "ordered.epub"
            write_minimal_epub(
                source,
                package,
                {
                    "book/one.xhtml": "<html><body>One</body></html>",
                    "book/nav.xhtml": "<html><body>Navigation</body></html>",
                    "book/two.xhtml": "<html><body>Two</body></html>",
                },
            )
            chapters = read_epub_spine(source)

        self.assertEqual([chapter.path for chapter in chapters], [
            "book/one.xhtml",
            "book/two.xhtml",
        ])

    def test_rejects_resource_path_outside_container(self):
        package = """<package xmlns="http://www.idpf.org/2007/opf">
          <manifest>
            <item id="bad" href="../../outside.xhtml"
              media-type="application/xhtml+xml"/>
          </manifest>
          <spine><itemref idref="bad"/></spine>
        </package>"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "unsafe.epub"
            write_minimal_epub(source, package, {})
            with self.assertRaisesRegex(EpubError, "outside the book"):
                read_epub_spine(source)

    def test_rejects_wrong_mimetype(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.epub"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("mimetype", "application/zip")
                archive.writestr("META-INF/container.xml", CONTAINER)
            with self.assertRaisesRegex(EpubError, "valid EPUB mimetype"):
                read_epub_spine(source)


if __name__ == "__main__":
    unittest.main()
