"""File and document validation utilities for secure binary upload handling."""

import os
from pathlib import PurePosixPath
import re
from typing import Optional


class FileValidationError(Exception):
    """Base exception for upload and file validation errors."""


class UnsupportedMediaTypeError(FileValidationError):
    """Raised when client supplies or uploads an unsupported MIME type."""


class FileTooLargeError(FileValidationError):
    """Raised when file exceeds maximum allowed byte limit."""


class EmptyFileError(FileValidationError):
    """Raised when uploaded file contains 0 bytes."""


class InvalidSignatureError(FileValidationError):
    """Raised when magic bytes do not match expected binary file signature."""


PDF_MAGIC_BYTES = b"%PDF-"
MAX_FILENAME_LENGTH = 255
SAFE_FILENAME_RE = re.compile(r"^[\w\-. ]+$")


def sanitize_filename(filename: Optional[str], default: str = "document.pdf") -> str:
    """Sanitize client-provided filename to prevent path traversal, drive injection, or control characters.

    - Strips directory components and drive letters.
    - Removes null bytes and control characters.
    - Limits length to 255 characters.
    - Defaults to 'document.pdf' if empty or all characters are stripped.
    """
    if not filename:
        return default

    # Normalize backslashes (Windows) to forward slashes, then extract basename
    clean = filename.replace("\\", "/")
    basename = PurePosixPath(clean).name

    # Remove null bytes, non-printable/control chars
    basename = "".join(ch for ch in basename if ch.isprintable() and ch not in ("\x00", "\r", "\n", "\t"))
    basename = basename.strip()

    # Prevent directory traversal relics
    while basename.startswith("../") or basename.startswith("..\\") or basename == "..":
        basename = basename.lstrip("./\\").strip()

    if not basename or basename == ".":
        return default

    # Truncate length while preserving extension if possible
    if len(basename) > MAX_FILENAME_LENGTH:
        name_part, dot, ext_part = basename.rpartition(".")
        if dot:
            max_name = MAX_FILENAME_LENGTH - len(ext_part) - 1
            basename = f"{name_part[:max_name]}.{ext_part}"
        else:
            basename = basename[:MAX_FILENAME_LENGTH]

    return basename


def validate_pdf_content_type(content_type: Optional[str]) -> str:
    """Validate client-reported MIME type against allowed PDF content types.

    Raises UnsupportedMediaTypeError if unsupported.
    """
    if not content_type:
        # Default if client didn't supply Content-Type
        return "application/pdf"

    normalized = content_type.lower().split(";")[0].strip()
    if normalized not in ("application/pdf", "application/x-pdf", "binary/octet-stream", "application/octet-stream"):
        raise UnsupportedMediaTypeError(
            f"Unsupported media type '{content_type}'. Only 'application/pdf' documents are supported."
        )

    return "application/pdf"


def validate_pdf_magic_bytes(header: bytes) -> None:
    """Verify that binary header begins with standard PDF signature (%PDF-).

    Raises InvalidSignatureError if bytes do not match.
    """
    if not header.startswith(PDF_MAGIC_BYTES):
        raise InvalidSignatureError(
            "Uploaded file does not match PDF signature. Expected '%PDF-' magic bytes at file header."
        )
