import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Exception thrown when secure hardware keystore or keychain storage operations fail.
class AuthStorageException implements Exception {
  final String message;
  final Object? cause;

  const AuthStorageException(this.message, [this.cause]);

  @override
  String toString() =>
      'AuthStorageException: $message${cause != null ? ' (Cause: $cause)' : ''}';
}

/// Contract for persisting authentication tokens securely.
///
/// Ensures raw tokens are never written to unencrypted logs, SharedPreferences,
/// or diagnostic dumps, and isolates tokens by backend authority.
abstract class AuthTokenStorage {
  Future<void> saveToken(String token, {String? backendAuthority});
  Future<String?> getToken({String? backendAuthority});
  Future<void> clearToken({String? backendAuthority});
  Future<bool> hasToken({String? backendAuthority});
}

/// Production implementation backed by Android Keystore / iOS Keychain.
class SecureAuthTokenStorage implements AuthTokenStorage {
  static const String _keyToken = 'lens_access_token';
  final FlutterSecureStorage _storage;

  SecureAuthTokenStorage({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              // CRITICAL: resetOnError is set to false to prevent silent token wiping
              // during transient Android Keystore hardware lockouts or device reboots.
              // When an error occurs, AuthStorageException is propagated so the application
              // can enter a recoverable state instead of permanently discarding credentials.
              aOptions: AndroidOptions(
                resetOnError: false,
              ),
              iOptions: IOSOptions(
                accessibility: KeychainAccessibility.first_unlock,
              ),
            );

  static String formatKey(String? backendAuthority) {
    if (backendAuthority == null || backendAuthority.trim().isEmpty) {
      return _keyToken;
    }
    final clean = backendAuthority.trim().replaceAll(RegExp(r'[^a-zA-Z0-9_\-\.]'), '_');
    return '${_keyToken}_$clean';
  }

  @override
  Future<void> saveToken(String token, {String? backendAuthority}) async {
    final trimmed = token.trim();
    if (trimmed.isEmpty) {
      await clearToken(backendAuthority: backendAuthority);
      return;
    }
    try {
      final key = formatKey(backendAuthority);
      await _storage.write(key: key, value: trimmed);
    } catch (e) {
      throw AuthStorageException('Failed to write authentication token to secure storage', e);
    }
  }

  @override
  Future<String?> getToken({String? backendAuthority}) async {
    try {
      if (backendAuthority != null && backendAuthority.trim().isNotEmpty) {
        final key = formatKey(backendAuthority);
        final token = await _storage.read(key: key);
        if (token != null && token.trim().isNotEmpty) {
          return token.trim();
        }
      }
      final defaultToken = await _storage.read(key: _keyToken);
      if (defaultToken == null || defaultToken.trim().isEmpty) return null;
      return defaultToken.trim();
    } catch (e) {
      throw AuthStorageException('Failed to read authentication token from secure storage', e);
    }
  }

  @override
  Future<void> clearToken({String? backendAuthority}) async {
    try {
      if (backendAuthority != null && backendAuthority.trim().isNotEmpty) {
        final key = formatKey(backendAuthority);
        await _storage.delete(key: key);
      }
      await _storage.delete(key: _keyToken);
    } catch (e) {
      throw AuthStorageException('Failed to clear authentication token from secure storage', e);
    }
  }

  @override
  Future<bool> hasToken({String? backendAuthority}) async {
    final token = await getToken(backendAuthority: backendAuthority);
    return token != null && token.isNotEmpty;
  }
}

/// Fast in-memory storage implementation for automated widget and unit tests.
class InMemoryAuthTokenStorage implements AuthTokenStorage {
  final Map<String, String> _tokens = {};

  InMemoryAuthTokenStorage([String? initialToken]) {
    if (initialToken != null && initialToken.trim().isNotEmpty) {
      _tokens['lens_access_token'] = initialToken.trim();
    }
  }

  static String formatKey(String? backendAuthority) {
    if (backendAuthority == null || backendAuthority.trim().isEmpty) {
      return 'lens_access_token';
    }
    final clean = backendAuthority.trim().replaceAll(RegExp(r'[^a-zA-Z0-9_\-\.]'), '_');
    return 'lens_access_token_$clean';
  }

  @override
  Future<void> saveToken(String token, {String? backendAuthority}) async {
    final trimmed = token.trim();
    final key = formatKey(backendAuthority);
    if (trimmed.isEmpty) {
      _tokens.remove(key);
    } else {
      _tokens[key] = trimmed;
    }
  }

  @override
  Future<String?> getToken({String? backendAuthority}) async {
    if (backendAuthority != null && backendAuthority.trim().isNotEmpty) {
      final key = formatKey(backendAuthority);
      if (_tokens.containsKey(key)) {
        return _tokens[key];
      }
    }
    return _tokens['lens_access_token'];
  }

  @override
  Future<void> clearToken({String? backendAuthority}) async {
    if (backendAuthority != null && backendAuthority.trim().isNotEmpty) {
      final key = formatKey(backendAuthority);
      _tokens.remove(key);
    }
    _tokens.remove('lens_access_token');
  }

  @override
  Future<bool> hasToken({String? backendAuthority}) async {
    final token = await getToken(backendAuthority: backendAuthority);
    return token != null && token.isNotEmpty;
  }
}
