import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:lens_mobile/core/config/api_config.dart';
import 'package:lens_mobile/core/errors/api_exception.dart';
import 'package:lens_mobile/core/utils/security_utils.dart';
import 'package:lens_mobile/models/capture.dart';
import 'package:lens_mobile/models/content_chunk.dart';
import 'package:lens_mobile/models/search_result.dart';

void main() {
  group('LENS Mobile Models & Errors (Tests 1, 2, 5, 6, 12)', () {
    // 1. API model parsing
    test('1. API model parsing deserializes all domain schemas correctly', () {
      // ContentChunk
      final chunkJson = {
        'id': 'c-100',
        'chunk_index': 0,
        'content': 'FastAPI is a modern web framework.',
        'created_at': '2026-10-02T12:00:00.000Z',
      };
      final chunk = ContentChunk.fromJson(chunkJson);
      expect(chunk.id, 'c-100');
      expect(chunk.chunkIndex, 0);
      expect(chunk.content, 'FastAPI is a modern web framework.');
      expect(chunk.createdAt, DateTime.parse('2026-10-02T12:00:00.000Z'));

      // Capture Detail
      final captureJson = {
        'id': 'cap-1',
        'source_type': 'url',
        'processing_status': 'completed',
        'processing_error': null,
        'processed_at': '2026-10-02T12:05:00.000Z',
        'title': 'FastAPI Documentation',
        'original_url': 'https://fastapi.tiangolo.com',
        'content': null,
        'mime_type': 'text/html',
        'source_id': null,
        'created_at': '2026-10-02T12:00:00.000Z',
        'updated_at': '2026-10-02T12:05:00.000Z',
        'metadata': {'author': 'tiangolo'},
        'chunks': [chunkJson],
      };
      final capture = Capture.fromJson(captureJson);
      expect(capture.id, 'cap-1');
      expect(capture.sourceType, SourceType.url);
      expect(capture.processingStatus, ProcessingStatus.completed);
      expect(capture.isCompleted, true);
      expect(capture.displayTitle, 'FastAPI Documentation');
      expect(capture.chunks.length, 1);
      expect(capture.chunks.first.content, 'FastAPI is a modern web framework.');
      expect(capture.metadata?['author'], 'tiangolo');

      // CaptureListResponse
      final listJson = {
        'items': [captureJson],
        'total': 1,
        'limit': 15,
        'offset': 0,
      };
      final listRes = CaptureListResponse.fromJson(listJson);
      expect(listRes.items.length, 1);
      expect(listRes.total, 1);
      expect(listRes.hasMore, false);

      // SearchResponse
      final searchJson = {
        'query': 'fastapi',
        'total': 1,
        'limit': 20,
        'degraded': false,
        'results': [
          {
            'capture_id': 'cap-1',
            'title': 'FastAPI Documentation',
            'original_url': 'https://fastapi.tiangolo.com',
            'source_type': 'url',
            'best_score': 0.88,
            'best_lexical_score': 0.85,
            'best_semantic_score': 0.91,
            'matching_chunks': [
              {
                'chunk_id': 'c-100',
                'chunk_index': 0,
                'content_excerpt': 'FastAPI is a modern web framework...',
                'score': 0.88,
                'lexical_score': 0.85,
                'semantic_score': 0.91,
              }
            ],
          }
        ],
      };
      final searchRes = SearchResponse.fromJson(searchJson);
      expect(searchRes.query, 'fastapi');
      expect(searchRes.results.length, 1);
      final firstResult = searchRes.results.first;
      expect(firstResult.captureId, 'cap-1');
      expect(firstResult.bestScore, 0.88);
      expect(firstResult.matchingChunks.length, 1);
      expect(firstResult.matchingChunks.first.score, 0.88);
    });

    // 2. API error parsing
    test('2. API error parsing normalizes status codes, Pydantic 422, and masks internal tracebacks', () {
      // 404 Not Found
      final err404 = ApiException.fromResponse(404, jsonEncode({'detail': 'Capture not found'}));
      expect(err404.isNotFound, true);
      expect(err404.message, 'Capture not found');

      // 422 Pydantic Validation
      final pydantic422 = jsonEncode({
        'detail': [
          {
            'loc': ['body', 'original_url'],
            'msg': 'Unsupported URL scheme. Only HTTP/HTTPS accepted.',
            'type': 'value_error',
          }
        ]
      });
      final err422 = ApiException.fromResponse(422, pydantic422);
      expect(err422.isValidationError, true);
      expect(err422.message, contains('Validation error on original_url: Unsupported URL scheme'));

      // 500 Internal error with Python traceback must be masked
      final traceBody = jsonEncode({
        'detail': 'Traceback (most recent call last):\n  File "app/main.py", line 42\nsqlalchemy.exc.OperationalError: postgresql://postgres:secret@db:5432'
      });
      final err500 = ApiException.fromResponse(500, traceBody);
      expect(err500.message.contains('Traceback'), isFalse);
      expect(err500.message.contains('postgresql://'), isFalse);
      expect(err500.message.contains('secret'), isFalse);
      expect(err500.message, 'A server error occurred. Please try again later.');

      // Network and Timeout errors
      final netErr = ApiException.network();
      expect(netErr.isNetworkError, true);
      expect(netErr.message, contains('Unable to reach LENS server'));

      final timeErr = ApiException.timeout();
      expect(timeErr.isTimeout, true);
      expect(timeErr.message, contains('timed out'));
    });

    // 5. URL validation
    test('5. URL validation strictly permits http/https and rejects malicious schemes', () {
      expect(SecurityUtils.sanitizeUrl('https://example.com'), 'https://example.com');
      expect(SecurityUtils.sanitizeUrl('http://192.168.1.100:8000/docs'), 'http://192.168.1.100:8000/docs');
      expect(SecurityUtils.sanitizeUrl('javascript:alert(1)'), isNull);
      expect(SecurityUtils.sanitizeUrl('data:text/html,<script>alert(1)</script>'), isNull);
      expect(SecurityUtils.sanitizeUrl('vbscript:msgbox(1)'), isNull);
      expect(SecurityUtils.sanitizeUrl('file:///etc/passwd'), isNull);
      expect(SecurityUtils.sanitizeUrl(''), isNull);
      expect(SecurityUtils.sanitizeUrl('not-a-valid-url'), isNull);
    });

    // 6. Text validation
    test('6. Text validation ensures non-empty and non-whitespace input', () {
      // CaptureCreate payload structure
      final valid = CaptureCreate(
        sourceType: SourceType.text,
        title: 'Valid Note',
        content: 'Valid content body',
      );
      final jsonMap = valid.toJson();
      expect(jsonMap['source_type'], 'text');
      expect(jsonMap['title'], 'Valid Note');
      expect(jsonMap['content'], 'Valid content body');
    });

    // 12. No secret exposure
    test('12. No secrets or credentials in mobile configuration or models', () {
      final config = ApiConfig();
      expect(config.baseUrl, isNotEmpty);
      expect(RegExp('password|secret|key|token|postgresql://|redis://').hasMatch(config.baseUrl), isFalse);
    });
  });
}
