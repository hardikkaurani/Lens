import 'dart:async';
import 'package:flutter/foundation.dart';
import '../../models/user.dart';
import '../errors/api_exception.dart';
import 'auth_token_storage.dart';

enum AuthStatus {
  initial,
  restoring,
  authenticated,
  unauthenticated,
  restorationFailed,
}

/// Central state manager for mobile user authentication and session lifecycle.
class AuthService extends ChangeNotifier {
  final AuthTokenStorage _storage;
  User? _currentUser;
  AuthStatus _status = AuthStatus.initial;
  bool _isLoading = false;
  bool _isRestoring = false;
  int _sessionId = 0;
  String? _activeBackendAuthority;
  AuthStorageException? _storageCleanupError;
  String? _failedCleanupAuthority;

  AuthService({AuthTokenStorage? storage})
      : _storage = storage ?? SecureAuthTokenStorage();

  User? get currentUser => _currentUser;
  AuthStatus get status => _status;
  bool get isLoading => _isLoading;
  bool get isRestoring => _status == AuthStatus.restoring;
  bool get isRestorationFailed => _status == AuthStatus.restorationFailed;
  bool get isAuthenticated => _status == AuthStatus.authenticated && _currentUser != null;
  int get sessionId => _sessionId;
  String? get activeBackendAuthority => _activeBackendAuthority;

  /// Returns the most recent storage exception if secure token clearance failed during session expiry or restoration.
  AuthStorageException? get storageCleanupError => _storageCleanupError;

  /// Indicates if an attempt to delete an invalid/revoked token from storage failed.
  bool get hasStorageCleanupError => _storageCleanupError != null;

  /// Returns the authority of the token whose clearance failed, if any.
  String? get failedCleanupAuthority => _failedCleanupAuthority;

  AuthTokenStorage get storage => _storage;

  /// Explicitly clear the recorded storage cleanup error.
  void clearStorageCleanupError() {
    if (_storageCleanupError != null || _failedCleanupAuthority != null) {
      _storageCleanupError = null;
      _failedCleanupAuthority = null;
      notifyListeners();
    }
  }

  /// Retry clearing secure storage if previous clearance failed.
  Future<void> retryStorageCleanup({String? backendAuthority}) async {
    final targetAuthority = backendAuthority ?? _failedCleanupAuthority ?? _activeBackendAuthority;
    try {
      await _storage.clearToken(backendAuthority: targetAuthority);
      _storageCleanupError = null;
      _failedCleanupAuthority = null;
      if (_status == AuthStatus.restorationFailed && _currentUser == null) {
        _status = AuthStatus.unauthenticated;
      }
      notifyListeners();
    } catch (e) {
      _storageCleanupError = e is AuthStorageException
          ? e
          : AuthStorageException('Failed to clear token from secure storage', e);
      _failedCleanupAuthority = targetAuthority;
      notifyListeners();
      rethrow;
    }
  }

  /// Initialize and attempt to restore previous session from persisted secure storage.
  Future<void> restoreSession(
    Future<User> Function() fetchProfile, {
    String? backendAuthority,
  }) async {
    if (_isRestoring) return;
    final int requestSessionId = _sessionId;
    _isRestoring = true;
    _status = AuthStatus.restoring;
    _isLoading = true;
    notifyListeners();

    try {
      final hasToken = await _storage.hasToken(backendAuthority: backendAuthority);
      if (_sessionId != requestSessionId) return;

      if (!hasToken) {
        _status = AuthStatus.unauthenticated;
        _currentUser = null;
        _activeBackendAuthority = null;
        return;
      }

      final profile = await fetchProfile();
      if (_sessionId != requestSessionId) return;

      _currentUser = profile;
      _activeBackendAuthority = backendAuthority;
      _storageCleanupError = null;
      _status = AuthStatus.authenticated;
    } on AuthStorageException catch (e) {
      // Hardware keystore error or lock: PRESERVE tokens and transition to recoverable state
      if (_sessionId != requestSessionId) return;
      _storageCleanupError = e;
      _status = AuthStatus.restorationFailed;
    } catch (e) {
      if (_sessionId != requestSessionId) return;

      if (e is ApiException && e.isUnauthorized) {
        // Confirmed 401 Unauthorized: credentials/token invalid or revoked
        try {
          await _storage.clearToken(backendAuthority: backendAuthority);
          _storageCleanupError = null;
          _failedCleanupAuthority = null;
          _currentUser = null;
          _activeBackendAuthority = null;
          _status = AuthStatus.unauthenticated;
        } catch (storageError) {
          // Token deletion failed: token is still persisted in secure storage.
          // Explicitly expose cleanup failure and transition to restorationFailed
          // so credential cleanup is not falsely reported as complete.
          _storageCleanupError = storageError is AuthStorageException
              ? storageError
              : AuthStorageException('Failed to clear revoked token from secure storage', storageError);
          _failedCleanupAuthority = backendAuthority;
          _currentUser = null;
          _activeBackendAuthority = null;
          _status = AuthStatus.restorationFailed;
        }
      } else {
        // Network offline, timeout, 5xx server error, or connection failure:
        // PRESERVE the token and transition to recoverable restorationFailed state
        _status = AuthStatus.restorationFailed;
      }
    } finally {
      _isRestoring = false;
      if (_sessionId == requestSessionId) {
        _isLoading = false;
        notifyListeners();
      } else {
        if (_isLoading) {
          _isLoading = false;
          notifyListeners();
        }
      }
    }
  }

  /// Clean retry path for restoring session after connection returns.
  Future<void> retryRestoreSession(
    Future<User> Function() fetchProfile, {
    String? backendAuthority,
  }) async {
    await restoreSession(fetchProfile, backendAuthority: backendAuthority);
  }

  /// Discard preserved token and transition explicitly to unauthenticated state.
  Future<void> clearSessionAndLogin({String? backendAuthority}) async {
    final targetAuthority = backendAuthority ?? _activeBackendAuthority;
    try {
      await _storage.clearToken(backendAuthority: targetAuthority);
      _storageCleanupError = null;
      _failedCleanupAuthority = null;
    } catch (e) {
      _storageCleanupError = e is AuthStorageException
          ? e
          : AuthStorageException('Failed to clear token from secure storage', e);
      _failedCleanupAuthority = targetAuthority;
      rethrow;
    } finally {
      _sessionId++;
      _currentUser = null;
      _activeBackendAuthority = null;
      _status = AuthStatus.unauthenticated;
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Store session token and update user profile on successful authentication.
  Future<void> setSession({
    required User user,
    required String token,
    String? backendAuthority,
  }) async {
    await _storage.saveToken(token, backendAuthority: backendAuthority);
    _sessionId++;
    _currentUser = user;
    _activeBackendAuthority = backendAuthority;
    _storageCleanupError = null;
    _failedCleanupAuthority = null;
    _status = AuthStatus.authenticated;
    _isLoading = false;
    notifyListeners();
  }

  /// Update user profile details.
  void updateUser(User user) {
    _currentUser = user;
    _status = AuthStatus.authenticated;
    notifyListeners();
  }

  /// Handle 401 Unauthorized from any protected API call.
  /// If [originatingSessionId] does not match current [_sessionId], the stale call is discarded.
  /// If [propagateStorageError] is true, secure storage deletion failures are rethrown.
  Future<void> handleSessionExpired([
    int? originatingSessionId,
    String? backendAuthority,
    bool propagateStorageError = false,
  ]) async {
    if (originatingSessionId != null && originatingSessionId != _sessionId) {
      // Discard stale 401 response from older session that was already replaced
      return;
    }
    if (_status == AuthStatus.unauthenticated && _currentUser == null && _storageCleanupError == null) return;

    // Use explicit authority or the authority of the session being expired.
    // Never fall back to clearing global token when an active authority-scoped session exists.
    final targetAuthority = backendAuthority ?? _activeBackendAuthority;

    _sessionId++;

    AuthStorageException? clearError;
    try {
      await _storage.clearToken(backendAuthority: targetAuthority);
      _storageCleanupError = null;
      _failedCleanupAuthority = null;
    } catch (e) {
      clearError = e is AuthStorageException
          ? e
          : AuthStorageException('Failed to clear expired token from secure storage', e);
      _storageCleanupError = clearError;
      _failedCleanupAuthority = targetAuthority;
    }

    _currentUser = null;
    _activeBackendAuthority = null;
    _status = AuthStatus.unauthenticated;
    _isLoading = false;
    notifyListeners();

    if (clearError != null && propagateStorageError) {
      throw clearError;
    }
  }

  /// Explicitly log out the user and clear secure token storage.
  /// Storage errors propagate to the caller so failures are not silently ignored.
  Future<void> logout({String? backendAuthority}) async {
    final targetAuthority = backendAuthority ?? _activeBackendAuthority;
    await _storage.clearToken(backendAuthority: targetAuthority);
    _sessionId++;
    _currentUser = null;
    _activeBackendAuthority = null;
    _storageCleanupError = null;
    _failedCleanupAuthority = null;
    _status = AuthStatus.unauthenticated;
    _isLoading = false;
    notifyListeners();
  }
}
