import 'dart:convert';

/// Mobile-safe API exception model.
///
/// Normalizes HTTP status codes, network failures, timeouts, and validation errors.
/// Masks internal Python stack traces, database strings, and secret credentials.
class ApiException implements Exception {
  final int statusCode;
  final String message;
  final bool isNetworkError;
  final bool isTimeout;

  const ApiException({
    required this.statusCode,
    required this.message,
    this.isNetworkError = false,
    this.isTimeout = false,
  });

  bool get isUnauthorized => statusCode == 401;
  bool get isForbidden => statusCode == 403;
  bool get isNotFound => statusCode == 404;
  bool get isConflict => statusCode == 409;
  bool get isValidationError => statusCode == 422;
  bool get isTooManyRequests => statusCode == 429;
  bool get isServerError => statusCode >= 500;

  @override
  String toString() => message;

  /// Parse response body and status code into a safe ApiException
  factory ApiException.fromResponse(int status, String body) {
    String safeMessage = _extractSafeMessage(status, body);
    return ApiException(
      statusCode: status,
      message: safeMessage,
    );
  }

  factory ApiException.network({String? details}) {
    return ApiException(
      statusCode: 0,
      message: details != null && details.isNotEmpty
          ? 'Network error: $details'
          : 'Unable to reach LENS server. Check network connection and API address.',
      isNetworkError: true,
    );
  }

  factory ApiException.timeout() {
    return const ApiException(
      statusCode: 0,
      message: 'Connection timed out. The server took too long to respond.',
      isTimeout: true,
    );
  }

  factory ApiException.unexpectedFormat([String? detail]) {
    return ApiException(
      statusCode: 0,
      message: detail ?? 'Received invalid or unexpected data format from server.',
    );
  }

  static String _extractSafeMessage(int status, String body) {
    try {
      if (body.trim().isNotEmpty) {
        final decoded = jsonDecode(body);
        if (decoded is Map<String, dynamic>) {
          final detail = decoded['detail'];

          if (detail is String && detail.trim().isNotEmpty) {
            final trimmed = detail.trim();
            final lower = trimmed.toLowerCase();
            // Guard against leaked tracebacks, credentials, or internal connection strings
            final isSensitive = lower.contains('traceback') ||
                lower.contains('postgresql://') ||
                lower.contains('postgres://') ||
                lower.contains('redis://') ||
                lower.contains('password') ||
                lower.contains('secret') ||
                lower.contains('api_key') ||
                lower.contains('apikey') ||
                lower.contains('token') ||
                lower.contains('authorization') ||
                lower.contains('sqlalchemy');

            if (!isSensitive) {
              return trimmed;
            }
          } else if (detail is List && detail.isNotEmpty) {
            // Pydantic 422 validation structure
            final first = detail.first;
            if (first is Map<String, dynamic>) {
              final msg = first['msg'];
              final loc = first['loc'];
              final field = (loc is List && loc.isNotEmpty) ? loc.last : 'input';
              if (msg is String) {
                return 'Validation error on $field: $msg';
              }
            }
          }
        }
      }
    } catch (_) {
      // Body was not JSON
    }

    switch (status) {
      case 400:
        return 'Invalid request. Please check your input.';
      case 401:
        return 'Unauthorized. Access is unauthenticated.';
      case 403:
        return 'Forbidden. Access to this resource is denied.';
      case 404:
        return 'The requested resource was not found.';
      case 409:
        return 'A conflicting resource already exists.';
      case 422:
        return 'Validation failed. Please verify the submitted information.';
      case 429:
        return 'Too many requests. Please slow down and try again.';
      case 500:
        return 'A server error occurred. Please try again later.';
      case 502:
        return 'Bad gateway. The upstream service is unreachable.';
      case 503:
        return 'The LENS service is temporarily unavailable.';
      case 504:
        return 'Gateway timed out. The upstream server did not respond.';
      default:
        return 'Request failed with status $status.';
    }
  }
}
