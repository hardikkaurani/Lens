import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../auth/auth_service.dart';
import '../auth/auth_token_storage.dart';
import '../config/api_config.dart';
import '../errors/api_exception.dart';
import '../../models/capture.dart';
import '../../models/search_result.dart';
import '../../models/user.dart';

/// Centralized typed API client for LENS Mobile.
///
/// Handles all HTTP communication with the FastAPI backend, enforces timeouts,
/// attaches secure Bearer authentication tokens, decodes responses into domain
/// models, and normalizes errors safely.
class ApiClient {
  final ApiConfig _config;
  final String? _baseUrlOverride;
  final http.Client _httpClient;
  final AuthTokenStorage? _tokenStorage;
  final AuthService? _authService;
  final void Function()? _onSessionExpired;
  static const Duration _defaultTimeout = Duration(seconds: 15);

  ApiClient({
    ApiConfig? config,
    String? baseUrlOverride,
    http.Client? httpClient,
    AuthTokenStorage? tokenStorage,
    AuthService? authService,
    void Function()? onSessionExpired,
  })  : _config = config ?? ApiConfig(),
        _baseUrlOverride = baseUrlOverride,
        _httpClient = httpClient ?? http.Client(),
        _tokenStorage = tokenStorage,
        _authService = authService,
        _onSessionExpired = onSessionExpired;

  String get _baseUrl => _baseUrlOverride ?? _config.baseUrl;

  String get currentAuthority => _currentAuthority;

  String get _currentAuthority {
    try {
      final uri = Uri.parse(ApiConfig.normalizeUrl(_baseUrl));
      return uri.authority;
    } catch (_) {
      return '';
    }
  }

  static bool isLoopbackHost(String host) {
    final clean = host.toLowerCase();
    return clean == 'localhost' ||
        clean == '127.0.0.1' ||
        clean == '::1' ||
        clean == '10.0.2.2'; // Android emulator host loopback alias
  }

  /// Assert transport security for sensitive credentials and Bearer authentication.
  /// Rejects plain HTTP for remote hosts to avoid credential exposure.
  void _assertSecureTransport(Uri uri, {required bool isSensitive}) {
    if (!isSensitive) return;
    if (uri.scheme == 'https') return;
    if (uri.scheme == 'http' && isLoopbackHost(uri.host)) {
      return; // Permitted for local development
    }
    throw const ApiException(
      statusCode: 400,
      message: 'Insecure transport rejected: sensitive credentials and tokens must use HTTPS.',
    );
  }

  /// Build request headers with optional Bearer authentication injection
  Future<Map<String, String>> _getHeaders(Uri uri, {bool requireAuth = true}) async {
    _assertSecureTransport(uri, isSensitive: requireAuth);
    final headers = <String, String>{
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    };
    if (requireAuth) {
      final authority = _currentAuthority;
      final token = await (_tokenStorage?.getToken(backendAuthority: authority) ??
          _authService?.storage.getToken(backendAuthority: authority));
      if (token == null || token.trim().isEmpty) {
        throw const ApiException(
          statusCode: 401,
          message: 'Authentication required. No access token available.',
        );
      }
      headers['Authorization'] = 'Bearer ${token.trim()}';
    }
    return headers;
  }

  /// Helper to safely construct full API URIs without path collisions or trailing/leading slash anomalies.
  Uri _buildUri(String path, [Map<String, String>? queryParameters]) {
    final cleanBase = ApiConfig.normalizeUrl(_baseUrl);
    final cleanPath = path.startsWith('/') ? path : '/$path';
    final fullUri = Uri.parse('$cleanBase$cleanPath');
    if (queryParameters != null && queryParameters.isNotEmpty) {
      return fullUri.replace(queryParameters: queryParameters);
    }
    return fullUri;
  }

  /// Check backend health status (`GET /health`)
  Future<Map<String, dynamic>> checkHealth() async {
    final uri = _buildUri('/health');
    final headers = await _getHeaders(uri, requireAuth: false);
    final response = await _execute(
      () => _httpClient.get(uri, headers: headers),
      notifyAuthOn401: false,
    );
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Invalid health check response from server.');
    }
    return response;
  }

  /// Test connectivity to an arbitrary candidate URL without persisting it to [ApiConfig].
  Future<Map<String, dynamic>> checkHealthForUrl(
    String candidateUrl, {
    Duration timeout = const Duration(seconds: 5),
  }) async {
    final cleanBase = ApiConfig.normalizeUrl(candidateUrl);
    final uri = Uri.parse('$cleanBase/health');
    final headers = await _getHeaders(uri, requireAuth: false);
    final response = await _execute(
      () => _httpClient.get(uri, headers: headers),
      timeout: timeout,
      notifyAuthOn401: false,
    );
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Invalid health response from candidate URL.');
    }
    return response;
  }

  /// Register a new account (`POST /auth/register`)
  Future<User> register({required String email, required String password}) async {
    final uri = _buildUri('/auth/register');
    _assertSecureTransport(uri, isSensitive: true);
    final headers = await _getHeaders(uri, requireAuth: false);
    final body = jsonEncode({'email': email.trim(), 'password': password});
    final response = await _execute(
      () => _httpClient.post(uri, headers: headers, body: body),
      notifyAuthOn401: false,
    );
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected user profile JSON object.');
    }
    return User.fromJson(response);
  }

  /// Authenticate with email and password (`POST /auth/login`)
  Future<String> login({required String email, required String password}) async {
    final uri = _buildUri('/auth/login');
    _assertSecureTransport(uri, isSensitive: true);
    final headers = await _getHeaders(uri, requireAuth: false);
    final body = jsonEncode({'email': email.trim(), 'password': password});
    final response = await _execute(
      () => _httpClient.post(uri, headers: headers, body: body),
      notifyAuthOn401: false,
    );
    if (response is! Map<String, dynamic> || response['access_token'] == null) {
      throw ApiException.unexpectedFormat('Invalid token response from server.');
    }
    return response['access_token'] as String;
  }

  /// Retrieve authenticated user profile (`GET /auth/me`)
  Future<User> getMe([String? tokenOverride]) async {
    final uri = _buildUri('/auth/me');
    if (tokenOverride != null && tokenOverride.isNotEmpty) {
      _assertSecureTransport(uri, isSensitive: true);
    }
    final headers = await _getHeaders(uri, requireAuth: tokenOverride == null);
    if (tokenOverride != null && tokenOverride.isNotEmpty) {
      headers['Authorization'] = 'Bearer $tokenOverride';
    }
    final response = await _execute(() => _httpClient.get(uri, headers: headers));
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected user profile JSON object.');
    }
    return User.fromJson(response);
  }

  /// List captures with pagination (`GET /captures?limit=&offset=`)
  Future<CaptureListResponse> listCaptures({int limit = 15, int offset = 0}) async {
    final uri = _buildUri(
      '/captures',
      {
        'limit': limit.toString(),
        'offset': offset.toString(),
      },
    );
    final headers = await _getHeaders(uri, requireAuth: true);
    final response = await _execute(() => _httpClient.get(uri, headers: headers));
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected capture list JSON object.');
    }
    return CaptureListResponse.fromJson(response);
  }

  /// Retrieve single capture by ID (`GET /captures/{id}`)
  Future<Capture> getCapture(String id) async {
    final uri = _buildUri('/captures/$id');
    final headers = await _getHeaders(uri, requireAuth: true);
    final response = await _execute(() => _httpClient.get(uri, headers: headers));
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected capture detail JSON object.');
    }
    return Capture.fromJson(response);
  }

  /// Ingest a new URL or text capture (`POST /captures`)
  Future<Capture> createCapture(CaptureCreate payload) async {
    final uri = _buildUri('/captures');
    final headers = await _getHeaders(uri, requireAuth: true);
    final body = jsonEncode(payload.toJson());
    final response = await _execute(
      () => _httpClient.post(uri, headers: headers, body: body),
    );
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected created capture JSON object.');
    }
    return Capture.fromJson(response);
  }

  /// Execute hybrid search (`GET /search?q=&limit=`)
  Future<SearchResponse> search({required String query, int limit = 20}) async {
    final trimmed = query.trim();
    if (trimmed.isEmpty) {
      throw const ApiException(
        statusCode: 422,
        message: 'Search query cannot be empty or whitespace-only.',
      );
    }
    if (trimmed.length > 500) {
      throw const ApiException(
        statusCode: 422,
        message: 'Search query cannot exceed 500 characters.',
      );
    }

    final uri = _buildUri(
      '/search',
      {
        'q': trimmed,
        'limit': limit.clamp(1, 50).toString(),
      },
    );
    final headers = await _getHeaders(uri, requireAuth: true);
    final response = await _execute(() => _httpClient.get(uri, headers: headers));
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected search response JSON object.');
    }
    return SearchResponse.fromJson(response);
  }

  /// Common request executor with timeout and error normalization
  Future<dynamic> _execute(
    Future<http.Response> Function() requestFn, {
    Duration timeout = _defaultTimeout,
    bool notifyAuthOn401 = true,
  }) async {
    try {
      final res = await requestFn().timeout(timeout);
      if (res.statusCode >= 200 && res.statusCode < 300) {
        if (res.body.trim().isEmpty) return <String, dynamic>{};
        return jsonDecode(res.body);
      }
      if (res.statusCode == 401 && notifyAuthOn401) {
        final currentSessionId = _authService?.sessionId;
        final authority = _currentAuthority;
        _onSessionExpired?.call();
        await _authService?.handleSessionExpired(currentSessionId, authority);
      }
      throw ApiException.fromResponse(res.statusCode, res.body);
    } on SocketException {
      throw ApiException.network();
    } on TimeoutException {
      throw ApiException.timeout();
    } on http.ClientException {
      throw ApiException.network();
    } on FormatException {
      throw ApiException.unexpectedFormat();
    } on TypeError {
      throw ApiException.unexpectedFormat('Data format mismatch from server.');
    } catch (e) {
      if (e is ApiException) rethrow;
      throw ApiException.network(details: 'Connection failed');
    }
  }

  void dispose() {
    _httpClient.close();
  }
}
