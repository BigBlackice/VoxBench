from pathlib import Path


def write_blank_pdf(path: Path, page_count: int = 1) -> None:
    """Write a minimal PDF containing the requested number of blank pages."""
    page_ids = list(range(3, 3 + page_count))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            f"<< /Type /Pages /Count {page_count} /Kids "
            f"[{' '.join(f'{page_id} 0 R' for page_id in page_ids)}] >>"
        ).encode(),
        *[
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] >>"
            for _ in page_ids
        ],
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(content))
        content.extend(f"{object_id} 0 obj\n".encode())
        content.extend(body + b"\nendobj\n")
    xref_offset = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.write_bytes(content)
