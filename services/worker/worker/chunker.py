"""Deterministic text chunking for LENS content indexing."""

from typing import Optional

DEFAULT_CHUNK_SIZE = 1000  # Target character window per chunk (~200-250 tokens)
DEFAULT_CHUNK_OVERLAP = 150  # Modest overlap to maintain contextual continuity across chunk boundaries


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Deterministically partition text into sequential, bounded chunks with modest overlap.

    Splits preferentially at structural boundaries:
    1. Double newline (paragraph break)
    2. Single newline (line break)
    3. Sentence terminators ('. ', '! ', '? ')
    4. Word whitespace (' ')
    5. Fallback to hard character limit

    Guarantees:
    - Purely deterministic (same input produces identical chunks).
    - Sequential and ordered.
    - Zero empty chunks.
    - No external network or AI dependencies.
    """
    cleaned = text.strip()
    if not cleaned:
        return []

    if len(cleaned) <= chunk_size:
        return [cleaned]

    chunks: list[str] = []
    start = 0
    text_len = len(cleaned)

    while start < text_len:
        end = start + chunk_size
        if end >= text_len:
            tail = cleaned[start:].strip()
            if tail:
                chunks.append(tail)
            break

        # Priority 1: Paragraph break in overlap window
        best_cut = cleaned.rfind("\n\n", start + chunk_overlap, end)

        # Priority 2: Line break in overlap window
        if best_cut == -1:
            best_cut = cleaned.rfind("\n", start + chunk_overlap, end)

        # Priority 3: Sentence ending punctuation in overlap window
        if best_cut == -1:
            for punct in (". ", "! ", "? "):
                idx = cleaned.rfind(punct, start + chunk_overlap, end)
                if idx != -1:
                    best_cut = max(best_cut, idx + len(punct))

        # Priority 4: Word boundary in overlap window
        if best_cut == -1:
            best_cut = cleaned.rfind(" ", start + chunk_overlap, end)

        # Priority 5: Hard slice if no clean delimiter found
        if best_cut == -1 or best_cut <= start:
            best_cut = end

        chunk_slice = cleaned[start:best_cut].strip()
        if chunk_slice:
            chunks.append(chunk_slice)

        # Advance starting point preserving overlap
        start = max(start + 1, best_cut - chunk_overlap)

        # Consume any leading whitespace for subsequent chunk
        while start < text_len and cleaned[start].isspace():
            start += 1

    return [c for c in chunks if c]
