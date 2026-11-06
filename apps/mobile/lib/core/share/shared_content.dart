import '../config/api_config.dart';
import '../../models/capture.dart';

/// Semantic classification of incoming shared content.
enum SharedContentType {
  url,
  text,
}

/// Structured representation of incoming shared content from the platform.
class SharedContent {
  final SharedContentType type;
  final String? url;
  final String? title;
  final String? text;
  final String rawText;
  final String? subject;

  const SharedContent({
    required this.type,
    this.url,
    this.title,
    this.text,
    required this.rawText,
    this.subject,
  });

  SourceType get sourceType =>
      type == SharedContentType.url ? SourceType.url : SourceType.text;

  @override
  String toString() =>
      'SharedContent(type: $type, url: $url, title: $title, textLen: ${text?.length})';
}

/// Safe parser and validator for incoming raw text payloads.
class SharedContentParser {
  static const int maxTextLength = 1000000;
  static const int maxUrlLength = 2048;
  static const int maxTitleLength = 512;

  // Pattern to find HTTP/HTTPS URLs in text
  static final RegExp _urlRegex = RegExp(
    r'https?://[^\s<>"]+',
    caseSensitive: false,
  );

  /// Parse raw shared text and optional subject into structured [SharedContent].
  ///
  /// Returns null if the payload is empty, whitespace-only, or invalid.
  static SharedContent? parse({
    String? rawText,
    String? subject,
  }) {
    if (rawText == null) return null;
    final trimmedRaw = rawText.trim();
    if (trimmedRaw.isEmpty) return null;

    final cleanSubject = subject?.trim().isNotEmpty == true
        ? _boundString(subject!.trim(), maxTitleLength)
        : null;

    // 1. Direct standalone URL: the entire text is a single valid HTTP/HTTPS URL
    final cleanStandalone = _cleanUrlCandidate(trimmedRaw);
    if (ApiConfig.isValidUrl(cleanStandalone) && cleanStandalone.length <= maxUrlLength) {
      final uri = Uri.tryParse(cleanStandalone);
      if (uri != null &&
          uri.hasScheme &&
          (uri.scheme == 'http' || uri.scheme == 'https') &&
          uri.host.isNotEmpty) {
        // If wrapped in punctuation like "(https://...)" or "https://...", ensure no other text exists
        final remaining = trimmedRaw
            .replaceFirst(cleanStandalone, '')
            .replaceAll(RegExp(r'[\s\(\)\[\]{}<>".,;:!?]+'), '');
        if (remaining.isEmpty) {
          return SharedContent(
            type: SharedContentType.url,
            url: cleanStandalone,
            title: cleanSubject,
            rawText: trimmedRaw,
            subject: cleanSubject,
          );
        }
      }
    }

    // 2. Text containing an embedded HTTP/HTTPS URL
    final match = _urlRegex.firstMatch(trimmedRaw);
    if (match != null) {
      final rawMatch = match.group(0)!;
      final cleanUrl = _cleanUrlCandidate(rawMatch);

      if (ApiConfig.isValidUrl(cleanUrl) && cleanUrl.length <= maxUrlLength) {
        final uri = Uri.tryParse(cleanUrl);
        if (uri != null &&
            uri.hasScheme &&
            (uri.scheme == 'http' || uri.scheme == 'https') &&
            uri.host.isNotEmpty) {
          // Extract text outside the URL to suggest as title and keep as note context
          var remainingRaw = trimmedRaw.replaceFirst(rawMatch, '');
          // If the URL was wrapped in quotes or parens (e.g. `(URL)` or `"URL"`), remove leftover wrappers
          remainingRaw = remainingRaw
              .replaceAll('()', '')
              .replaceAll('[]', '')
              .replaceAll('""', '')
              .replaceAll("''", '');

          // Normalize whitespace: collapse multiple spaces/newlines into a single space
          final remainingNormalized = remainingRaw
              .replaceAll(RegExp(r'[ \t\r\n]+'), ' ')
              .trim();

          // Check if there is meaningful text beyond bare punctuation
          final hasMeaningfulText = remainingNormalized
              .replaceAll(RegExp(r'[\s\(\)\[\]{}<>".,;:!?]+'), '')
              .isNotEmpty;

          final remainingText = hasMeaningfulText ? remainingNormalized : null;

          String? derivedTitle = cleanSubject;
          if (derivedTitle == null && remainingText != null) {
            derivedTitle = _boundString(remainingText, maxTitleLength);
          }

          return SharedContent(
            type: SharedContentType.url,
            url: cleanUrl,
            title: derivedTitle,
            text: remainingText,
            rawText: trimmedRaw,
            subject: cleanSubject,
          );
        }
      }
    }

    // 3. Plain text note
    final boundedText = _boundString(trimmedRaw, maxTextLength);
    return SharedContent(
      type: SharedContentType.text,
      title: cleanSubject,
      text: boundedText,
      rawText: trimmedRaw,
      subject: cleanSubject,
    );
  }

  /// Trims trailing sentence punctuation and unbalanced closing parenthesis/bracket from URL candidate.
  /// Preserves balanced parentheses like Wikipedia URLs (e.g. `https://en.wikipedia.org/wiki/LENS_(disambiguation)`).
  static String _cleanUrlCandidate(String candidate) {
    var cleaned = candidate.trim();
    bool changed = true;

    while (changed && cleaned.isNotEmpty) {
      changed = false;

      // 1. Strip trailing standard sentence punctuation
      final punctMatch = RegExp(r'[.,;:!?"”’]+$').firstMatch(cleaned);
      if (punctMatch != null) {
        cleaned = cleaned.substring(0, punctMatch.start);
        changed = true;
        continue;
      }

      // 2. Strip trailing closing parenthesis ONLY if unbalanced
      if (cleaned.endsWith(')')) {
        final openCount = '('.allMatches(cleaned).length;
        final closeCount = ')'.allMatches(cleaned).length;
        if (closeCount > openCount) {
          cleaned = cleaned.substring(0, cleaned.length - 1);
          changed = true;
          continue;
        }
      }

      // 3. Strip trailing closing bracket ONLY if unbalanced
      if (cleaned.endsWith(']')) {
        final openCount = '['.allMatches(cleaned).length;
        final closeCount = ']'.allMatches(cleaned).length;
        if (closeCount > openCount) {
          cleaned = cleaned.substring(0, cleaned.length - 1);
          changed = true;
          continue;
        }
      }
    }

    return cleaned;
  }

  static String _boundString(String input, int maxLength) {
    if (input.length <= maxLength) return input;
    return input.substring(0, maxLength);
  }
}

