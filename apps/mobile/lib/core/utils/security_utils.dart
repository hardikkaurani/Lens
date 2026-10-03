/// Security and input sanitization utilities for mobile.
class SecurityUtils {
  /// Validates and sanitizes a URL before launching or displaying it.
  /// Rejects `javascript:`, `data:`, `vbscript:`, and relative schemes.
  /// Strictly permits only `http` and `https` protocols.
  static String? sanitizeUrl(String? rawUrl) {
    if (rawUrl == null || rawUrl.trim().isEmpty) {
      return null;
    }

    final trimmed = rawUrl.trim();
    try {
      final uri = Uri.parse(trimmed);
      if (!uri.hasScheme || !uri.hasAuthority) {
        return null;
      }
      final scheme = uri.scheme.toLowerCase();
      if (scheme == 'http' || scheme == 'https') {
        return uri.toString();
      }
    } catch (_) {
      return null;
    }
    return null;
  }

  /// Truncates string safely at word boundaries where possible.
  static String truncate(String text, int maxLength) {
    if (text.length <= maxLength) return text;
    final slice = text.substring(0, maxLength);
    final lastSpace = slice.lastIndexOf(' ');
    if (lastSpace > maxLength * 0.7) {
      return '${slice.substring(0, lastSpace)}...';
    }
    return '$slice...';
  }
}
