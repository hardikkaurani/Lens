/**
 * Security utilities for the LENS Web Workspace.
 */

/**
 * Validates and sanitizes a URL string before rendering it as an href.
 * Strictly permits only http: and https: protocols.
 * Rejects javascript:, data:, vbscript:, and relative or malformed URLs.
 */
export function sanitizeUrl(rawUrl: string | null | undefined): string | null {
  if (!rawUrl || typeof rawUrl !== "string") {
    return null;
  }

  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return null;
  }

  try {
    const parsed = new URL(trimmed);
    const protocol = parsed.protocol.toLowerCase();
    if (protocol === "http:" || protocol === "https:") {
      return parsed.toString();
    }
  } catch {
    // Malformed URL format
    return null;
  }

  return null;
}

/**
 * Truncate long text strings safely without breaking mid-word when possible.
 */
export function truncateExcerpt(text: string, maxLength = 240): string {
  if (!text || text.length <= maxLength) {
    return text || "";
  }
  const slice = text.slice(0, maxLength);
  const lastSpace = slice.lastIndexOf(" ");
  if (lastSpace > maxLength * 0.7) {
    return `${slice.slice(0, lastSpace)}...`;
  }
  return `${slice}...`;
}
