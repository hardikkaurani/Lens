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

  AuthService({AuthTokenStorage? storage})
      : _storage = storage ?? SecureAuthTokenStorage();

  User? get currentUser => _currentUser;
  AuthStatus get status => _status;
  bool get isLoading => _isLoading;
  bool get isRestoring => _status == AuthStatus.restoring;
  bool get isRestorationFailed => _status == AuthStatus.restorationFailed;
  bool get isAuthenticated => _status == AuthStatus.authenticated && _currentUser != null;

  AuthTokenStorage get storage => _storage;

  /// Initialize and attempt to restore previous session from persisted secure storage.
  Future<void> restoreSession(Future<User> Function() fetchProfile) async {
    if (_isRestoring) return;
    _isRestoring = true;
    _status = AuthStatus.restoring;
    _isLoading = true;
    notifyListeners();

    try {
      final hasToken = await _storage.hasToken();
      if (!hasToken) {
        _status = AuthStatus.unauthenticated;
        _currentUser = null;
        return;
      }

      final profile = await fetchProfile();
      _currentUser = profile;
      _status = AuthStatus.authenticated;
    } catch (e) {
      if (e is ApiException && e.isUnauthorized) {
        // Confirmed 401 Unauthorized: credentials/token invalid or revoked
        await _storage.clearToken();
        _currentUser = null;
        _status = AuthStatus.unauthenticated;
      } else {
        // Network offline, timeout, 5xx server error, or local storage glitch:
        // PRESERVE the token and transition to recoverable restorationFailed state
        _status = AuthStatus.restorationFailed;
      }
    } finally {
      _isLoading = false;
      _isRestoring = false;
      notifyListeners();
    }
  }

  /// Clean retry path for restoring session after connection returns.
  Future<void> retryRestoreSession(Future<User> Function() fetchProfile) async {
    await restoreSession(fetchProfile);
  }

  /// Discard preserved token and transition explicitly to unauthenticated state.
  Future<void> clearSessionAndLogin() async {
    await _storage.clearToken();
    _currentUser = null;
    _status = AuthStatus.unauthenticated;
    _isLoading = false;
    notifyListeners();
  }

  /// Store session token and update user profile on successful authentication.
  Future<void> setSession({required User user, required String token}) async {
    await _storage.saveToken(token);
    _currentUser = user;
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
  Future<void> handleSessionExpired() async {
    if (_status == AuthStatus.unauthenticated && _currentUser == null) return;
    await _storage.clearToken();
    _currentUser = null;
    _status = AuthStatus.unauthenticated;
    _isLoading = false;
    notifyListeners();
  }

  /// Explicitly log out the user and clear secure token storage.
  Future<void> logout() async {
    await handleSessionExpired();
  }
}
