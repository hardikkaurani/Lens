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
    if (ApiConfig.isValidUrl(trimmedRaw) && trimmedRaw.length <= maxUrlLength) {
      final uri = Uri.tryParse(trimmedRaw);
      if (uri != null && uri.hasScheme && (uri.scheme == 'http' || uri.scheme == 'https')) {
        return SharedContent(
          type: SharedContentType.url,
          url: trimmedRaw,
          title: cleanSubject,
          rawText: trimmedRaw,
          subject: cleanSubject,
        );
      }
    }

    // 2. Text containing an embedded HTTP/HTTPS URL
    final match = _urlRegex.firstMatch(trimmedRaw);
    if (match != null) {
      final candidateUrl = match.group(0)!;
      if (ApiConfig.isValidUrl(candidateUrl) && candidateUrl.length <= maxUrlLength) {
        final uri = Uri.tryParse(candidateUrl);
        if (uri != null && uri.hasScheme && (uri.scheme == 'http' || uri.scheme == 'https')) {
          // Extract text outside the URL to suggest as title or note context
          final remainingText = trimmedRaw.replaceFirst(candidateUrl, '').trim();
          String? derivedTitle = cleanSubject;
          if (derivedTitle == null && remainingText.isNotEmpty) {
            // Use remaining text as a suggested title (bounded to maxTitleLength)
            derivedTitle = _boundString(remainingText, maxTitleLength);
          }

          return SharedContent(
            type: SharedContentType.url,
            url: candidateUrl,
            title: derivedTitle,
            text: remainingText.isNotEmpty ? remainingText : null,
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

  static String _boundString(String input, int maxLength) {
    if (input.length <= maxLength) return input;
    return input.substring(0, maxLength);
  }
}

