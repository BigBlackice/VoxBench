import tempfile
import unittest
import zipfile
from pathlib import Path

from app_logic.epub_reader import EpubError, read_epub_document, read_epub_spine


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
    def test_reads_epub3_navigation_entries_and_anchors(self):
        package = """<package xmlns="http://www.idpf.org/2007/opf">
          <manifest>
            <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
            <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
          </manifest>
          <spine><itemref idref="one"/></spine>
        </package>"""
        navigation = """<html xmlns:epub="http://www.idpf.org/2007/ops"><body>
          <nav epub:type="toc"><ol>
            <li><a href="one.xhtml#opening">Opening</a><ol>
              <li><a href="one.xhtml#part-two">Part two</a></li>
            </ol></li>
          </ol></nav>
        </body></html>"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "book.epub"
            write_minimal_epub(
                source,
                package,
                {
                    "book/nav.xhtml": navigation,
                    "book/one.xhtml": "<h1 id='opening'>Opening</h1><p>First.</p><h1 id='part-two'>Part two</h1><p>Second.</p>",
                },
            )
            chapters, entries = read_epub_document(source)

        self.assertEqual([chapter.path for chapter in chapters], ["book/one.xhtml"])
        self.assertEqual(
            [(entry.title, entry.level, entry.path, entry.fragment) for entry in entries],
            [
                ("Opening", 0, "book/one.xhtml", "opening"),
                ("Part two", 1, "book/one.xhtml", "part-two"),
            ],
        )

    def test_reads_epub2_ncx_navigation(self):
        package = """<package xmlns="http://www.idpf.org/2007/opf">
          <manifest>
            <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
            <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
          </manifest>
          <spine toc="ncx"><itemref idref="one"/></spine>
        </package>"""
        ncx = """<ncx><navMap><navPoint><navLabel><text>Start</text></navLabel>
          <content src="one.xhtml#start"/><navPoint><navLabel><text>Inside</text></navLabel>
          <content src="one.xhtml#inside"/></navPoint></navPoint></navMap></ncx>"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "book.epub"
            write_minimal_epub(
                source,
                package,
                {"book/toc.ncx": ncx, "book/one.xhtml": "<p>Text</p>"},
            )
            _chapters, entries = read_epub_document(source)

        self.assertEqual(
            [(entry.title, entry.level, entry.fragment) for entry in entries],
            [("Start", 0, "start"), ("Inside", 1, "inside")],
        )

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
