"""PDF text extraction module for LENS background processing."""

import io
import logging
from typing import Optional

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from worker.extractor import InsufficientContentError, normalize_text

logger = logging.getLogger(__name__)

DEFAULT_MAX_PDF_PAGES = 500
DEFAULT_MAX_EXTRACTED_CHARS = 2_000_000


class PDFExtractionError(Exception):
    """Base exception for PDF text extraction failures."""


class EncryptedPDFError(PDFExtractionError):
    """Raised when PDF file is encrypted or password-protected."""


class MalformedPDFError(PDFExtractionError):
    """Raised when PDF file structure is corrupted or unreadable."""


class PDFPageLimitExceededError(PDFExtractionError):
    """Raised when document page count exceeds safety threshold."""


class CorruptObjectError(PDFExtractionError):
    """Raised when stored object fails integrity verification."""


def extract_text_from_pdf(
    data: bytes,
    max_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_chars: int = DEFAULT_MAX_EXTRACTED_CHARS,
) -> tuple[Optional[str], str]:
    """Extract ordered, readable text and optional metadata title from raw PDF bytes.

    - Detects and rejects encrypted/password-protected PDFs.
    - Handles empty or multi-page documents safely.
    - Preserves page order.
    - Enforces page count and character safety bounds against memory exhaustion.
    - Normalizes whitespace via normalize_text.
    - Rejects scanned / image-only PDFs with InsufficientContentError.

    Returns:
        tuple of (Optional[metadata_title], normalized_text)
    """
    if not data:
        raise MalformedPDFError("PDF data stream is empty (0 bytes).")

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except PdfReadError as e:
        logger.warning("pypdf read error parsing document: %s", e)
        raise MalformedPDFError(f"Corrupted or invalid PDF format: {e}") from e
    except Exception as e:
        logger.warning("Unexpected error initializing PdfReader: %s", e)
        raise MalformedPDFError(f"Failed to read PDF document: {e}") from e

    # 1. Check for encryption / password protection
    if reader.is_encrypted:
        raise EncryptedPDFError("Encrypted or password-protected PDF files are not supported.")

    # 2. Check page count
    total_pages = len(reader.pages)
    if total_pages == 0:
        raise MalformedPDFError("PDF document contains no pages.")

    if total_pages > max_pages:
        raise PDFPageLimitExceededError(
            f"PDF document exceeds maximum permitted page limit of {max_pages} pages (found {total_pages})."
        )

    # 3. Extract optional document metadata title
    doc_title: Optional[str] = None
    try:
        if reader.metadata and reader.metadata.title:
            raw_title = reader.metadata.title.strip()
            # Ensure title is printable and not excessively long
            clean_title = "".join(c for c in raw_title if c.isprintable())[:512].strip()
            if clean_title:
                doc_title = clean_title
    except Exception as e:
        logger.debug("Could not extract metadata title from PDF: %s", e)

    # 4. Extract text from each page preserving order
    extracted_pages: list[str] = []
    total_chars = 0

    for page_idx, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
        except Exception as e:
            logger.warning("Error extracting text from page %d: %s", page_idx + 1, e)
            page_text = ""

        clean_page = page_text.strip()
        if clean_page:
            extracted_pages.append(clean_page)
            total_chars += len(clean_page)

        if total_chars > max_chars:
            logger.warning("PDF extraction reached maximum character bound (%d chars)", max_chars)
            break

    # 5. Normalize extracted text
    combined_raw = "\n\n".join(extracted_pages)
    normalized = normalize_text(combined_raw)

    # 6. Reject documents with no readable text (e.g., scanned / image-only PDFs)
    if len(normalized.strip()) < 10:
        raise InsufficientContentError(
            "Extracted PDF contains no readable text. Scanned or image-only PDFs are not supported."
        )

    return doc_title, normalized
