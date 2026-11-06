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

/// Service managing incoming platform share intents with deduplication and parsing.
class IncomingShareService {
  final IncomingSharePlatform _platform;
  final StreamController<SharedContent> _shareController =
      StreamController<SharedContent>.broadcast();

  StreamSubscription<Map<String, dynamic>>? _platformSubscription;

  String? _lastShareHash;
  DateTime? _lastShareTime;

  IncomingShareService({IncomingSharePlatform? platform})
      : _platform = platform ?? MethodChannelIncomingSharePlatform() {
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

    // Deduplication check: ignore identical share payloads received within 1500ms
    final hash = '$text|$subject';
    final now = DateTime.now();
    if (_lastShareHash == hash &&
        _lastShareTime != null &&
        now.difference(_lastShareTime!).inMilliseconds < 1500) {
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

