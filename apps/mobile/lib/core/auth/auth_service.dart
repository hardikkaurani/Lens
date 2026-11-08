import 'dart:async';
import 'package:flutter/foundation.dart';
import '../../models/user.dart';
import 'auth_token_storage.dart';

enum AuthStatus {
  initial,
  authenticated,
  unauthenticated,
}

/// Central state manager for mobile user authentication and session lifecycle.
class AuthService extends ChangeNotifier {
  final AuthTokenStorage _storage;
  User? _currentUser;
  AuthStatus _status = AuthStatus.initial;
  bool _isLoading = false;

  AuthService({AuthTokenStorage? storage})
      : _storage = storage ?? SecureAuthTokenStorage();

  User? get currentUser => _currentUser;
  AuthStatus get status => _status;
  bool get isLoading => _isLoading;
  bool get isAuthenticated => _status == AuthStatus.authenticated && _currentUser != null;

  AuthTokenStorage get storage => _storage;

  /// Initialize and attempt to restore previous session from persisted secure storage.
  Future<void> restoreSession(Future<User> Function() fetchProfile) async {
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
    } catch (_) {
      // Failed to restore (e.g. expired token 401 or network offline with no cache)
      // Clear token to return cleanly to unauthenticated login
      await _storage.clearToken();
      _currentUser = null;
      _status = AuthStatus.unauthenticated;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
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
