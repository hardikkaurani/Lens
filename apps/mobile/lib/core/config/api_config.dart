import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Centralized configuration for LENS API connectivity.
///
/// Supports:
/// - Environment override via `--dart-define=API_BASE_URL=http://<IP>:8000`
/// - Runtime in-app reconfiguration stored in SharedPreferences
/// - Preset options for Physical Phone LAN, Android Emulator, and adb reverse localhost
class ApiConfig extends ChangeNotifier {
  static const String _prefKey = 'lens_api_base_url';

  // Default fallback if neither env var nor saved pref exists
  static const String _envBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );

  static final ApiConfig _instance = ApiConfig._internal();
  factory ApiConfig() => _instance;
  ApiConfig._internal();

  String _baseUrl = _envBaseUrl;
  bool _isInitialized = false;

  String get baseUrl => _baseUrl;
  bool get isInitialized => _isInitialized;

  /// Load persisted base URL from SharedPreferences
  Future<void> init() async {
    if (_isInitialized) return;
    try {
      final prefs = await SharedPreferences.getInstance();
      final saved = prefs.getString(_prefKey);
      if (saved != null && isValidUrl(saved)) {
        _baseUrl = normalizeUrl(saved);
      } else if (isValidUrl(_envBaseUrl)) {
        _baseUrl = normalizeUrl(_envBaseUrl);
      }
    } catch (e) {
      debugPrint('ApiConfig: error loading preferences: $e');
    } finally {
      _isInitialized = true;
      notifyListeners();
    }
  }

  /// Update and persist the API base URL
  Future<void> setBaseUrl(String newUrl) async {
    final normalized = normalizeUrl(newUrl);
    if (normalized == _baseUrl) return;

    _baseUrl = normalized;
    notifyListeners();

    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_prefKey, _baseUrl);
    } catch (e) {
      debugPrint('ApiConfig: error saving base URL: $e');
    }
  }

  /// Reset to default environment URL
  Future<void> resetToDefault() async {
    await setBaseUrl(_envBaseUrl);
  }

  /// Validate whether [candidate] is an acceptable LENS API base URL.
  ///
  /// Rejects non-HTTP schemes, dangerous URIs (javascript:, file:, data:, content:),
  /// empty hosts, and embedded credentials.
  static bool isValidUrl(String candidate) {
    final trimmed = candidate.trim();
    if (trimmed.isEmpty) return false;

    final lower = trimmed.toLowerCase();
    if (lower.startsWith('javascript:') ||
        lower.startsWith('data:') ||
        lower.startsWith('file:') ||
        lower.startsWith('content:') ||
        lower.startsWith('blob:') ||
        lower.startsWith('vbscript:')) {
      return false;
    }

    String urlWithScheme = trimmed;
    if (!lower.startsWith('http://') && !lower.startsWith('https://')) {
      if (trimmed.contains('://')) {
        return false;
      }
      urlWithScheme = 'http://$trimmed';
    }

    final uri = Uri.tryParse(urlWithScheme);
    if (uri == null) return false;

    final scheme = uri.scheme.toLowerCase();
    if (scheme != 'http' && scheme != 'https') {
      return false;
    }

    if (uri.host.isEmpty) {
      return false;
    }

    if (uri.userInfo.isNotEmpty) {
      return false;
    }

    return true;
  }

  /// Normalize an API base URL into standard `http[s]://host[:port][/path]` without trailing slashes.
  ///
  /// Throws [ArgumentError] if the URL fails validation.
  static String normalizeUrl(String url) {
    final trimmed = url.trim();
    if (!isValidUrl(trimmed)) {
      throw ArgumentError('Invalid or unsupported API Base URL: $url');
    }

    var processed = trimmed;
    final lower = processed.toLowerCase();
    if (!lower.startsWith('http://') && !lower.startsWith('https://')) {
      processed = 'http://$processed';
    }

    final uri = Uri.parse(processed);
    var path = uri.path;
    while (path.endsWith('/')) {
      path = path.substring(0, path.length - 1);
    }

    final normalizedUri = Uri(
      scheme: uri.scheme.toLowerCase(),
      host: uri.host,
      port: uri.hasPort ? uri.port : null,
      path: path.isEmpty ? null : path,
    );

    return normalizedUri.toString();
  }
}
