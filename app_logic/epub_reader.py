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


@dataclass(frozen=True)
class EpubNavigation:
    title: str
    level: int
    path: str
    fragment: str | None


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


def _navigation_target(value: str, base: str) -> tuple[str, str | None]:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        raise EpubError("EPUB navigation outside the book is not supported.")
    if not parsed.path:
        return "", unquote(parsed.fragment) or None
    return _safe_member_path(parsed.path, base=base), unquote(parsed.fragment) or None


def _navigation_entries(
    root: ElementTree.Element,
    base: str,
) -> list[EpubNavigation]:
    nav = next(
        (
            element
            for element in root.iter()
            if _local_name(element.tag) == "nav"
            and any("toc" in value.casefold() for value in element.attrib.values())
        ),
        None,
    )
    if nav is None:
        return []
    listing = next((item for item in nav.iter() if _local_name(item.tag) == "ol"), None)
    if listing is None:
        return []

    entries: list[EpubNavigation] = []

    def visit(container: ElementTree.Element, level: int) -> None:
        for item in list(container):
            if _local_name(item.tag) != "li":
                continue
            link = next((child for child in list(item) if _local_name(child.tag) == "a"), None)
            if link is not None and link.get("href", ""):
                path, fragment = _navigation_target(link.get("href", ""), base)
                title = " ".join("".join(link.itertext()).split())
                if path and title:
                    entries.append(EpubNavigation(title, level, path, fragment))
            for child in list(item):
                if _local_name(child.tag) == "ol":
                    visit(child, level + 1)

    visit(listing, 0)
    return entries


def _ncx_entries(root: ElementTree.Element, base: str) -> list[EpubNavigation]:
    navigation = next((item for item in root.iter() if _local_name(item.tag) == "navMap"), None)
    if navigation is None:
        return []
    entries: list[EpubNavigation] = []

    def visit(point: ElementTree.Element, level: int) -> None:
        label = next((item for item in point.iter() if _local_name(item.tag) == "navLabel"), None)
        content = next((item for item in point.iter() if _local_name(item.tag) == "content"), None)
        title = " ".join("".join(label.itertext()).split()) if label is not None else ""
        if content is not None and content.get("src", "") and title:
            path, fragment = _navigation_target(content.get("src", ""), base)
            if path:
                entries.append(EpubNavigation(title, level, path, fragment))
        for child in list(point):
            if _local_name(child.tag) == "navPoint":
                visit(child, level + 1)

    for point in list(navigation):
        if _local_name(point.tag) == "navPoint":
            visit(point, 0)
    return entries


def read_epub_document(source: Path) -> tuple[list[EpubChapter], list[EpubNavigation]]:
    """Return EPUB spine content and its EPUB 3 or EPUB 2 navigation entries."""
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
        spine_toc = ""
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
            elif name == "spine":
                spine_toc = element.get("toc", "")

        nav_path = next(
            (path for path, _media_type, properties in manifest.values() if "nav" in properties),
            "",
        )
        ncx_path = ""
        if spine_toc and spine_toc in manifest:
            ncx_path = manifest[spine_toc][0]
        if not ncx_path:
            ncx_path = next(
                (
                    path
                    for path, media_type, _properties in manifest.values()
                    if media_type == "application/x-dtbncx+xml"
                ),
                "",
            )
        navigation: list[EpubNavigation] = []
        try:
            if nav_path:
                navigation = _navigation_entries(
                    _parse_xml(
                        _read_member(archive, members, nav_path, maximum_size=MAX_CONTENT_BYTES),
                        "navigation document",
                    ),
                    posixpath.dirname(nav_path),
                )
            elif ncx_path:
                navigation = _ncx_entries(
                    _parse_xml(
                        _read_member(archive, members, ncx_path, maximum_size=MAX_XML_BYTES),
                        "NCX table of contents",
                    ),
                    posixpath.dirname(ncx_path),
                )
        except EpubError:
            navigation = []

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
        spine_paths = {chapter.path for chapter in chapters}
        return chapters, [entry for entry in navigation if entry.path in spine_paths]


def read_epub_spine(source: Path) -> list[EpubChapter]:
    """Return readable EPUB content documents in their declared spine order."""
    return read_epub_document(source)[0]
