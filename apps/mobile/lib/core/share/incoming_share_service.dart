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

  String? _lastShareHash;
  DateTime? _lastShareTime;

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

    // Deduplication check: suppress duplicate platform callbacks within debounce window (default 1500ms).
    // Note: This is an in-memory intent delivery debounce guard to absorb immediate OS duplicates
    // (e.g. during Activity recreation or Android intent double-delivery), NOT durable deduplication.
    // Identical content shared after the window expires is processed as a fresh capture.
    final hash = '$text|$subject';
    final now = _clock();
    if (_lastShareHash == hash &&
        _lastShareTime != null &&
        now.difference(_lastShareTime!) < debounceDuration) {
      return null;
    }

    final parsed = SharedContentParser.parse(
      rawText: text,
      subject: subject,
    );

    if (parsed != null) {
      _lastShareHash = hash;
      _lastShareTime = now;
    }

    return parsed;
  }

  void dispose() {
    _platformSubscription?.cancel();
    _shareController.close();
  }
}

