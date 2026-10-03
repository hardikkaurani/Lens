"""Readable HTML extraction and text normalization using BeautifulSoup."""

import re
from typing import Optional

from bs4 import BeautifulSoup


class ExtractionError(Exception):
    """Base exception for HTML extraction failures."""


class InsufficientContentError(ExtractionError):
    """Raised when the extracted text body is empty or too short to be usable."""


# Noise elements to discard prior to extracting readable text
NOISE_TAGS = (
    "script",
    "style",
    "noscript",
    "iframe",
    "header",
    "footer",
    "nav",
    "aside",
    "svg",
    "form",
    "button",
)

MINIMUM_TEXT_LENGTH = 20


def normalize_text(text: str) -> str:
    """Normalize extracted text whitespace and structure without destroying content."""
    # Standardize line breaks
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Replace non-breaking and other exotic spaces with standard space
    text = text.replace("\xa0", " ").replace("\u200b", "")

    # Clean individual lines: collapse runs of spaces/tabs and strip line boundaries
    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        cleaned_line = re.sub(r"[ \t]+", " ", line).strip()
        cleaned_lines.append(cleaned_line)

    joined = "\n".join(cleaned_lines)

    # Collapse three or more consecutive line breaks into standard double paragraph breaks
    normalized = re.sub(r"\n{3,}", "\n\n", joined).strip()
    return normalized


def extract_and_normalize_html(
    html: str,
    min_length: int = MINIMUM_TEXT_LENGTH,
) -> tuple[Optional[str], str]:
    """Extract page title and readable body text from an HTML document.

    Returns:
        A tuple of (extracted_title, normalized_body_text).

    Raises:
        InsufficientContentError: If the resulting readable text is shorter than min_length.
    """
    if not html or not html.strip():
        raise InsufficientContentError("Empty HTML response received.")

    soup = BeautifulSoup(html, "html.parser")

    # Extract page title if available
    title: Optional[str] = None
    if soup.title and soup.title.string:
        clean_title = re.sub(r"[ \t\n]+", " ", soup.title.string).strip()
        if clean_title:
            title = clean_title[:512]

    # Decompose script, style, navigation, and noise tags
    for tag_name in NOISE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Extract text with newlines between block elements
    raw_text = soup.get_text(separator="\n")
    normalized_text = normalize_text(raw_text)

    if len(normalized_text) < min_length:
        raise InsufficientContentError(
            f"Extracted page contains insufficient readable text ({len(normalized_text)} characters)."
        )

    return title, normalized_text
