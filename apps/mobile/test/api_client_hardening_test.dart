import 'dart:convert';
import 'dart:io';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:lens_mobile/core/config/api_config.dart';
import 'package:lens_mobile/core/errors/api_exception.dart';
import 'package:lens_mobile/core/network/api_client.dart';
import 'package:lens_mobile/models/capture.dart';

void main() {
  group('ApiClient Hardening & Resilience Tests', () {
    // 1. Timeout handling
    test('1. Throws ApiException with isTimeout when server exceeds timeout window', () async {
      final mockHttp = MockClient((request) async {
        await Future.delayed(const Duration(milliseconds: 50));
        return http.Response('{"status":"ok"}', 200);
      });

      final client = ApiClient(httpClient: mockHttp);
      // Execute health check with 1ms timeout to induce TimeoutException deterministically
      expect(
        () => client.checkHealthForUrl(
          'http://127.0.0.1:8000',
          timeout: const Duration(milliseconds: 1),
        ),
        throwsA(isA<ApiException>().having((e) => e.isTimeout, 'isTimeout', isTrue)),
      );
    });

    // 2. Connection/network failure handling
    test('2. Maps SocketException and ClientException to ApiException.isNetworkError', () async {
      final mockHttp = MockClient((request) async {
        throw const SocketException('Connection refused');
      });

      final client = ApiClient(httpClient: mockHttp);
      expect(
        () => client.checkHealth(),
        throwsA(isA<ApiException>().having((e) => e.isNetworkError, 'isNetworkError', isTrue)),
      );
    });

    // 3. Malformed JSON handling
    test('3. Maps malformed JSON body to ApiException.unexpectedFormat', () async {
      final mockHttp = MockClient((request) async {
        return http.Response('<!DOCTYPE html><html><body>Error 502</body></html>', 200);
      });

      final client = ApiClient(httpClient: mockHttp);
      expect(
        () => client.checkHealth(),
        throwsA(isA<ApiException>().having(
          (e) => e.message,
          'message',
          contains('invalid or unexpected data format'),
        )),
      );
    });

    // 4. Unexpected response shape (e.g. JSON array instead of Map)
    test('4. Rejects non-dict JSON responses where object maps are expected', () async {
      final mockHttp = MockClient((request) async {
        return http.Response('["not", "a", "map"]', 200);
      });

      final client = ApiClient(httpClient: mockHttp);
      expect(
        () => client.checkHealth(),
        throwsA(isA<ApiException>().having(
          (e) => e.message,
          'message',
          contains('Invalid health check response'),
        )),
      );
    });

    // 5. HTTP status code normalization (401, 403, 404, 409, 422, 429)
    test('5. Correctly normalizes 4xx HTTP client errors with domain getters', () async {
      final testCases = [
        {'code': 401, 'getter': (ApiException e) => e.isUnauthorized, 'expected': 'Unauthorized'},
        {'code': 403, 'getter': (ApiException e) => e.isForbidden, 'expected': 'Forbidden'},
        {'code': 404, 'getter': (ApiException e) => e.isNotFound, 'expected': 'not found'},
        {'code': 409, 'getter': (ApiException e) => e.isConflict, 'expected': 'conflicting'},
        {'code': 422, 'getter': (ApiException e) => e.isValidationError, 'expected': 'Validation failed'},
        {'code': 429, 'getter': (ApiException e) => e.isTooManyRequests, 'expected': 'Too many requests'},
      ];

      for (final tc in testCases) {
        final status = tc['code'] as int;
        final getter = tc['getter'] as bool Function(ApiException);
        final expectedText = tc['expected'] as String;

        final mockHttp = MockClient((request) async {
          return http.Response('', status);
        });
        final client = ApiClient(httpClient: mockHttp);

        try {
          await client.getCapture('test-id');
          fail('Should have thrown for status $status');
        } on ApiException catch (e) {
          expect(e.statusCode, status);
          expect(getter(e), isTrue);
          expect(e.message.toLowerCase(), contains(expectedText.toLowerCase()));
        }
      }
    });

    // 6. HTTP 5xx errors and internal detail redaction
    test('6. Normalizes 5xx errors and redacts python stack traces, database uris, and credentials', () async {
      final leakedPayload = jsonEncode({
        'detail':
            'Traceback (most recent call last):\nFile "services/api/app/main.py"\npostgresql://lens_admin:super_secret_pw@db:5432/lens'
      });

      final mockHttp = MockClient((request) async {
        return http.Response(leakedPayload, 500);
      });

      final client = ApiClient(httpClient: mockHttp);
      try {
        await client.checkHealth();
        fail('Should have thrown ApiException');
      } on ApiException catch (e) {
        expect(e.isServerError, isTrue);
        expect(e.message.contains('Traceback'), isFalse);
        expect(e.message.contains('super_secret_pw'), isFalse);
        expect(e.message.contains('postgresql://'), isFalse);
        expect(e.message, 'A server error occurred. Please try again later.');
      }
    });

    // 7. checkHealthForUrl tests arbitrary candidates safely
    test('7. checkHealthForUrl queries candidate address without modifying global ApiConfig', () async {
      final config = ApiConfig();
      final originalBaseUrl = config.baseUrl;

      final mockHttp = MockClient((request) async {
        expect(request.url.toString(), 'http://192.168.1.50:8000/health');
        return http.Response('{"status":"ok","api":"ok","database":"ok","redis":"ok"}', 200);
      });

      final client = ApiClient(httpClient: mockHttp);
      final res = await client.checkHealthForUrl('http://192.168.1.50:8000');
      expect(res['status'], 'ok');
      expect(config.baseUrl, originalBaseUrl); // Unchanged
    });

    // 8. Search query bounds in ApiClient
    test('8. Search validates query bounds (rejects empty and >500 chars)', () async {
      final client = ApiClient();

      expect(
        () => client.search(query: '   '),
        throwsA(isA<ApiException>().having((e) => e.isValidationError, 'isValidationError', isTrue)),
      );

      final oversized = 'a' * 501;
      expect(
        () => client.search(query: oversized),
        throwsA(isA<ApiException>().having((e) => e.isValidationError, 'isValidationError', isTrue)),
      );
    });

    // 9. CreateCapture does not blindly retry
    test('9. CreateCapture sends single POST request and does not retry on 500', () async {
      int requestCount = 0;
      final mockHttp = MockClient((request) async {
        requestCount++;
        return http.Response('{"detail":"Database dead"}', 500);
      });

      final client = ApiClient(httpClient: mockHttp);
      final payload = CaptureCreate(
        sourceType: SourceType.url,
        originalUrl: 'https://example.com/test',
      );

      await expectLater(
        () => client.createCapture(payload),
        throwsA(isA<ApiException>()),
      );
      // Must NOT blindly retry write operations to avoid duplicate captures
      expect(requestCount, 1);
    });

    // 10. ApiConfig URL validation and dangerous scheme rejection
    test('10. ApiConfig strictly rejects dangerous schemes and credentials', () {
      expect(ApiConfig.isValidUrl('https://example.com'), isTrue);
      expect(ApiConfig.isValidUrl('http://10.0.2.2:8000'), isTrue);
      expect(ApiConfig.isValidUrl('http://localhost:8000/api'), isTrue);

      // Dangerous schemes
      expect(ApiConfig.isValidUrl('javascript:alert(1)'), isFalse);
      expect(ApiConfig.isValidUrl('data:text/html,<html>test</html>'), isFalse);
      expect(ApiConfig.isValidUrl('file:///etc/hosts'), isFalse);
      expect(ApiConfig.isValidUrl('content://media/external'), isFalse);
      expect(ApiConfig.isValidUrl('blob:https://example.com/uuid'), isFalse);
      expect(ApiConfig.isValidUrl('ftp://files.example.com'), isFalse);

      // Credentials in URL
      expect(ApiConfig.isValidUrl('http://admin:secret@10.0.2.2:8000'), isFalse);

      // Empty host
      expect(ApiConfig.isValidUrl('http:///path'), isFalse);
      expect(ApiConfig.isValidUrl(''), isFalse);
    });

    // 11. ApiConfig URL normalization
    test('11. ApiConfig normalizes trailing slashes and default schemes safely', () {
      expect(ApiConfig.normalizeUrl('http://10.0.2.2:8000///'), 'http://10.0.2.2:8000');
      expect(ApiConfig.normalizeUrl('https://api.lens.dev/v1/'), 'https://api.lens.dev/v1');
      expect(ApiConfig.normalizeUrl('127.0.0.1:8000'), 'http://127.0.0.1:8000');
    });
  });
}
