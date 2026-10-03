import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';
import '../errors/api_exception.dart';
import '../../models/capture.dart';
import '../../models/search_result.dart';

/// Centralized typed API client for LENS Mobile.
///
/// Handles all HTTP communication with the FastAPI backend, enforces timeouts,
/// decodes responses into domain models, and normalizes errors safely.
class ApiClient {
  final ApiConfig _config;
  final http.Client _httpClient;
  static const Duration _defaultTimeout = Duration(seconds: 15);

  ApiClient({
    ApiConfig? config,
    http.Client? httpClient,
  })  : _config = config ?? ApiConfig(),
        _httpClient = httpClient ?? http.Client();

  String get _baseUrl => _config.baseUrl;

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
    final response = await _execute(() => _httpClient.get(uri, headers: _headers));
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Invalid health check response from server.');
    }
    return response;
  }

  /// Test connectivity to an arbitrary candidate URL without persisting it to [ApiConfig].
  ///
  /// Used by [ServerConfigDialog] to verify reachability before saving.
  Future<Map<String, dynamic>> checkHealthForUrl(
    String candidateUrl, {
    Duration timeout = const Duration(seconds: 5),
  }) async {
    final cleanBase = ApiConfig.normalizeUrl(candidateUrl);
    final uri = Uri.parse('$cleanBase/health');
    final response = await _execute(
      () => _httpClient.get(uri, headers: _headers),
      timeout: timeout,
    );
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Invalid health response from candidate URL.');
    }
    return response;
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
    final response = await _execute(() => _httpClient.get(uri, headers: _headers));
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected capture list JSON object.');
    }
    return CaptureListResponse.fromJson(response);
  }

  /// Retrieve single capture by ID (`GET /captures/{id}`)
  Future<Capture> getCapture(String id) async {
    final uri = _buildUri('/captures/$id');
    final response = await _execute(() => _httpClient.get(uri, headers: _headers));
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected capture detail JSON object.');
    }
    return Capture.fromJson(response);
  }

  /// Ingest a new URL or text capture (`POST /captures`)
  Future<Capture> createCapture(CaptureCreate payload) async {
    final uri = _buildUri('/captures');
    final body = jsonEncode(payload.toJson());
    final response = await _execute(
      () => _httpClient.post(uri, headers: _headers, body: body),
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
    final response = await _execute(() => _httpClient.get(uri, headers: _headers));
    if (response is! Map<String, dynamic>) {
      throw ApiException.unexpectedFormat('Expected search response JSON object.');
    }
    return SearchResponse.fromJson(response);
  }

  Map<String, String> get _headers => {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      };

  /// Common request executor with timeout and error normalization
  Future<dynamic> _execute(
    Future<http.Response> Function() requestFn, {
    Duration timeout = _defaultTimeout,
  }) async {
    try {
      final res = await requestFn().timeout(timeout);
      if (res.statusCode >= 200 && res.statusCode < 300) {
        if (res.body.trim().isEmpty) return <String, dynamic>{};
        return jsonDecode(res.body);
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
