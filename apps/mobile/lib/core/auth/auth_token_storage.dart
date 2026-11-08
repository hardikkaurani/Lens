import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Contract for persisting authentication tokens securely.
///
/// Ensures raw tokens are never written to unencrypted logs, SharedPreferences,
/// or diagnostic dumps.
abstract class AuthTokenStorage {
  Future<void> saveToken(String token);
  Future<String?> getToken();
  Future<void> clearToken();
  Future<bool> hasToken();
}

/// Production implementation backed by Android Keystore / iOS Keychain.
class SecureAuthTokenStorage implements AuthTokenStorage {
  static const String _keyToken = 'lens_access_token';
  final FlutterSecureStorage _storage;

  SecureAuthTokenStorage({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(
                resetOnError: true,
              ),
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock,
              ),
            );

  @override
  Future<void> saveToken(String token) async {
    final trimmed = token.trim();
    if (trimmed.isEmpty) {
      await clearToken();
      return;
    }
    await _storage.write(key: _keyToken, value: trimmed);
  }

  @override
  Future<String?> getToken() async {
    try {
      final token = await _storage.read(key: _keyToken);
      if (token == null || token.trim().isEmpty) return null;
      return token.trim();
    } catch (_) {
      // In case of hardware key invalidation, gracefully treat as unauthenticated
      return null;
    }
  }

  @override
  Future<void> clearToken() async {
    try {
      await _storage.delete(key: _keyToken);
    } catch (_) {}
  }

  @override
  Future<bool> hasToken() async {
    final token = await getToken();
    return token != null && token.isNotEmpty;
  }
}

/// Fast in-memory storage implementation for automated widget and unit tests.
class InMemoryAuthTokenStorage implements AuthTokenStorage {
  String? _token;

  InMemoryAuthTokenStorage([String? initialToken]) : _token = initialToken;

  @override
  Future<void> saveToken(String token) async {
    final trimmed = token.trim();
    _token = trimmed.isEmpty ? null : trimmed;
  }

  @override
  Future<String?> getToken() async => _token;

  @override
  Future<void> clearToken() async {
    _token = null;
  }

  @override
  Future<bool> hasToken() async => _token != null && _token!.isNotEmpty;
}
