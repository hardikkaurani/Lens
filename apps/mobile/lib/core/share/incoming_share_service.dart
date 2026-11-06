import 'dart:async';
import 'package:flutter/services.dart';
import 'shared_content.dart';

/// Platform boundary interface for testing and decoupling native channels.
abstract class IncomingSharePlatform {
  Future<Map<String, dynamic>?> getInitialShare();
  Stream<Map<String, dynamic>> get onShareReceived;
}

/// Default implementation utilizing Flutter's [MethodChannel] and [EventChannel].
class MethodChannelIncomingSharePlatform implements IncomingSharePlatform {
  static const MethodChannel _methodChannel =
      MethodChannel('com.lens.mobile/share_channel');
  static const EventChannel _eventChannel =
      EventChannel('com.lens.mobile/share_events');

  @override
  Future<Map<String, dynamic>?> getInitialShare() async {
    try {
      final result =
          await _methodChannel.invokeMethod<Map<dynamic, dynamic>>('getInitialShare');
      if (result == null) return null;
      return Map<String, dynamic>.from(result);
    } catch (_) {
      return null;
    }
  }

  @override
  Stream<Map<String, dynamic>> get onShareReceived {
    return _eventChannel
        .receiveBroadcastStream()
        .where((event) => event != null)
        .map((event) => Map<String, dynamic>.from(event as Map));
  }
}

/// In-memory record tracking the most recent platform share for debounce comparison.
class _LastShareRecord {
  final String text;
  final String? subject;
  final DateTime timestamp;

  const _LastShareRecord({
    required this.text,
    required this.subject,
    required this.timestamp,
  });

  bool matches(String otherText, String? otherSubject) {
    return text == otherText && subject == otherSubject;
  }
}

/// Service managing incoming platform share intents with platform callback debounce and parsing.
///
/// **Debounce Semantics:**
/// The in-memory 1500ms duplicate suppression window is strictly an OS intent-delivery
/// debounce guard. It absorbs immediate duplicate platform callbacks triggered by Android
/// Activity recreation, configuration changes (e.g. screen rotation), or double-intent
/// delivery on certain OEM Android skins.
///
/// It is **not** durable deduplication across application sessions or repeated user shares:
/// if a user intentionally shares the same content after the debounce window expires,
/// it will be processed normally as a distinct capture. Durable deduplication and
/// idempotency are managed upstream by backend capture pipelines.
class IncomingShareService {
  final IncomingSharePlatform _platform;
  final Duration debounceDuration;
  final DateTime Function() _clock;
  final StreamController<SharedContent> _shareController =
      StreamController<SharedContent>.broadcast();

  StreamSubscription<Map<String, dynamic>>? _platformSubscription;

  _LastShareRecord? _lastShareRecord;

  IncomingShareService({
    IncomingSharePlatform? platform,
    this.debounceDuration = const Duration(milliseconds: 1500),
    DateTime Function()? clock,
  })  : _platform = platform ?? MethodChannelIncomingSharePlatform(),
        _clock = clock ?? DateTime.now {
    _platformSubscription = _platform.onShareReceived.listen(_handleRawShare);
  }

  /// Stream of validated incoming shares (warm-start deliveries).
  Stream<SharedContent> get onIncomingShare => _shareController.stream;

  /// Retrieves and consumes initial share intent (cold-start delivery).
  Future<SharedContent?> getInitialShare() async {
    final raw = await _platform.getInitialShare();
    if (raw == null) return null;
    return _processRawShare(raw);
  }

  void _handleRawShare(Map<String, dynamic> raw) {
    final content = _processRawShare(raw);
    if (content != null) {
      _shareController.add(content);
    }
  }

  SharedContent? _processRawShare(Map<String, dynamic> raw) {
    final text = raw['text'] as String?;
    final subject = raw['subject'] as String?;

    if (text == null || text.trim().isEmpty) {
      return null;
    }

    // Deduplication check: compare text and subject as discrete fields rather than
    // a joined delimiter string, preventing delimiter collisions across different pairs.
    final now = _clock();
    if (_lastShareRecord != null &&
        _lastShareRecord!.matches(text, subject) &&
        now.difference(_lastShareRecord!.timestamp) < debounceDuration) {
      return null;
    }

    final parsed = SharedContentParser.parse(
      rawText: text,
      subject: subject,
    );

    if (parsed != null) {
      _lastShareRecord = _LastShareRecord(
        text: text,
        subject: subject,
        timestamp: now,
      );
    }

    return parsed;
  }

  void dispose() {
    _platformSubscription?.cancel();
    _shareController.close();
  }
}
