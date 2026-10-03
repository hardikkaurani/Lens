import 'package:intl/intl.dart';

/// Formatting utilities for dates, scores, and status display.
class Formatters {
  static final DateFormat _dateFormat = DateFormat('MMM d, yyyy, h:mm a');

  static String formatDateTime(DateTime? dateTime) {
    if (dateTime == null) return '';
    return _dateFormat.format(dateTime.toLocal());
  }

  static String formatIso(String? isoString) {
    if (isoString == null || isoString.isEmpty) return '';
    try {
      final parsed = DateTime.parse(isoString);
      return formatDateTime(parsed);
    } catch (_) {
      return isoString;
    }
  }

  static String formatScore(double score) {
    if (score.isNaN || score.isInfinite) return '0.0%';
    final clamped = score.clamp(0.0, 1.0);
    return '${(clamped * 100).toStringAsFixed(1)}%';
  }

  /// Mobile processing status labels according to Stage 9 specifications:
  /// pending: "Waiting to process"
  /// processing: "Processing"
  /// completed: "Ready"
  /// failed: "Processing failed"
  static String formatStatusLabel(String status) {
    switch (status.toLowerCase()) {
      case 'pending':
        return 'Waiting to process';
      case 'processing':
        return 'Processing';
      case 'completed':
        return 'Ready';
      case 'failed':
        return 'Processing failed';
      default:
        return status;
    }
  }
}
