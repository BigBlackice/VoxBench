import re


def split_text(text: str, max_chars: int) -> list[str]:
    """Split text at paragraph/sentence boundaries, then at words if necessary."""
    text = re.sub(r"[ \t]+", " ", text.strip())
    if not text:
        return []

    units = re.split(r"(?<=[.!?])\s+|\n+", text)
    chunks: list[str] = []
    current = ""

    for unit in filter(None, (part.strip() for part in units)):
        words = unit.split()
        pieces: list[str] = []
        piece = ""

        for word in words:
            if len(word) > max_chars:
                if piece:
                    pieces.append(piece)
                    piece = ""
                pieces.extend(word[i : i + max_chars] for i in range(0, len(word), max_chars))
            elif not piece or len(piece) + 1 + len(word) <= max_chars:
                piece = word if not piece else f"{piece} {word}"
            else:
                pieces.append(piece)
                piece = word

        if piece:
            pieces.append(piece)

        for part in pieces:
            candidate = part if not current else f"{current} {part}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = part

    if current:
        chunks.append(current)
    return chunks
