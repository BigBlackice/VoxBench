import posixpath
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree


EPUB_MIMETYPE = b"application/epub+zip"
CONTAINER_PATH = "META-INF/container.xml"
MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_BYTES = 250 * 1024 * 1024
MAX_XML_BYTES = 2 * 1024 * 1024
MAX_CONTENT_BYTES = 20 * 1024 * 1024
SUPPORTED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


class EpubError(ValueError):
    """Raised when an EPUB cannot be read safely."""


@dataclass(frozen=True)
class EpubChapter:
    path: str
    content: bytes


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _safe_member_path(value: str, *, base: str = "") -> str:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        raise EpubError("EPUB resources outside the book are not supported.")

    decoded = unquote(parsed.path)
    if not decoded or "\x00" in decoded or "\\" in decoded:
        raise EpubError("The EPUB contains an invalid resource path.")
    if PurePosixPath(decoded).is_absolute():
        raise EpubError("The EPUB contains an unsafe absolute resource path.")

    combined = posixpath.normpath(posixpath.join(base, decoded))
    if combined == ".." or combined.startswith("../"):
        raise EpubError("The EPUB contains a resource path outside the book.")
    return combined[2:] if combined.startswith("./") else combined


def _validated_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES:
        raise EpubError("The EPUB contains too many files.")

    members: dict[str, zipfile.ZipInfo] = {}
    total_size = 0
    for entry in entries:
        path = _safe_member_path(entry.filename)
        if entry.flag_bits & 0x1:
            raise EpubError("Encrypted EPUB files are not supported.")
        if entry.compress_type not in SUPPORTED_COMPRESSION:
            raise EpubError("The EPUB uses an unsupported compression method.")
        total_size += entry.file_size
        if total_size > MAX_ARCHIVE_BYTES:
            raise EpubError("The expanded EPUB is too large.")
        if path in members:
            raise EpubError("The EPUB contains duplicate file paths.")
        members[path] = entry
    return members


def _read_member(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    path: str,
    *,
    maximum_size: int,
) -> bytes:
    entry = members.get(path)
    if entry is None or entry.is_dir():
        raise EpubError(f"The EPUB is missing required file: {path}")
    if entry.file_size > maximum_size:
        raise EpubError(f"The EPUB file is too large to process: {path}")
    content = archive.read(entry)
    if len(content) > maximum_size:
        raise EpubError(f"The EPUB file is too large to process: {path}")
    return content


def _parse_xml(content: bytes, description: str) -> ElementTree.Element:
    if len(content) > MAX_XML_BYTES:
        raise EpubError(f"The EPUB {description} is too large.")
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise EpubError(f"The EPUB contains malformed {description}.") from error


def _package_path(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
) -> str:
    container = _parse_xml(
        _read_member(
            archive,
            members,
            CONTAINER_PATH,
            maximum_size=MAX_XML_BYTES,
        ),
        "container metadata",
    )
    for element in container.iter():
        if _local_name(element.tag) == "rootfile":
            path = element.get("full-path", "")
            if path:
                return _safe_member_path(path)
    raise EpubError("The EPUB does not identify a package document.")


def read_epub_spine(source: Path) -> list[EpubChapter]:
    """Return readable EPUB content documents in their declared spine order."""
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as error:
        raise EpubError("The uploaded file is not a valid EPUB archive.") from error

    with archive:
        members = _validated_members(archive)
        mimetype = _read_member(
            archive,
            members,
            "mimetype",
            maximum_size=len(EPUB_MIMETYPE),
        )
        if mimetype != EPUB_MIMETYPE:
            raise EpubError("The uploaded file does not have a valid EPUB mimetype.")

        package_path = _package_path(archive, members)
        package = _parse_xml(
            _read_member(
                archive,
                members,
                package_path,
                maximum_size=MAX_XML_BYTES,
            ),
            "package document",
        )
        package_directory = posixpath.dirname(package_path)

        manifest: dict[str, tuple[str, str, set[str]]] = {}
        spine: list[str] = []
        for element in package.iter():
            name = _local_name(element.tag)
            if name == "item":
                item_id = element.get("id", "")
                href = element.get("href", "")
                if item_id and href:
                    manifest[item_id] = (
                        _safe_member_path(href, base=package_directory),
                        element.get("media-type", "").lower(),
                        set(element.get("properties", "").split()),
                    )
            elif name == "itemref":
                idref = element.get("idref", "")
                if idref:
                    spine.append(idref)

        chapters = []
        seen: set[str] = set()
        for idref in spine:
            item = manifest.get(idref)
            if item is None:
                continue
            path, media_type, properties = item
            if path in seen or "nav" in properties:
                continue
            if media_type not in {
                "application/xhtml+xml",
                "text/html",
            }:
                continue
            seen.add(path)
            chapters.append(
                EpubChapter(
                    path=path,
                    content=_read_member(
                        archive,
                        members,
                        path,
                        maximum_size=MAX_CONTENT_BYTES,
                    ),
                )
            )
        return chapters
