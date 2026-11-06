import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lens_mobile/core/errors/api_exception.dart';
import 'package:lens_mobile/core/network/api_client.dart';
import 'package:lens_mobile/core/share/incoming_share_service.dart';
import 'package:lens_mobile/core/share/shared_content.dart';
import 'package:lens_mobile/main.dart';
import 'package:lens_mobile/models/capture.dart';
import 'package:lens_mobile/screens/capture_detail_screen.dart';
import 'package:lens_mobile/screens/captures_screen.dart';
import 'package:lens_mobile/screens/new_capture_screen.dart';
import 'package:lens_mobile/screens/share_review_screen.dart';

class FakeIncomingSharePlatform implements IncomingSharePlatform {
  Map<String, dynamic>? initialShare;
  final StreamController<Map<String, dynamic>> _controller =
      StreamController<Map<String, dynamic>>.broadcast();

  FakeIncomingSharePlatform({this.initialShare});

  @override
  Future<Map<String, dynamic>?> getInitialShare() async {
    final data = initialShare;
    initialShare = null;
    return data;
  }

  @override
  Stream<Map<String, dynamic>> get onShareReceived => _controller.stream;

  void emitShare(Map<String, dynamic> share) {
    _controller.add(share);
  }

  void dispose() {
    _controller.close();
  }
}

class MockApiClient extends Fake implements ApiClient {
  final Future<Capture> Function(CaptureCreate payload)? onCreateCapture;
  int createCaptureCallCount = 0;
  CaptureCreate? lastCreatePayload;

  MockApiClient({this.onCreateCapture});

  @override
  Future<Capture> createCapture(CaptureCreate payload) async {
    createCaptureCallCount++;
    lastCreatePayload = payload;
    if (onCreateCapture != null) {
      return onCreateCapture!(payload);
    }
    return Capture(
      id: 'cap-fake-123',
      sourceType: payload.sourceType,
      processingStatus: ProcessingStatus.completed,
      originalUrl: payload.originalUrl,
      title: payload.title,
      content: payload.content,
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
    );
  }

  @override
  void dispose() {}
}

void main() {
  group('Stage 17: Incoming Share Parsing & Validation', () {
    // 1. Valid shared HTTP URL
    test('1. Valid shared HTTP and HTTPS URLs parsed as url type', () {
      final content = SharedContentParser.parse(
        rawText: 'https://docs.flutter.dev/get-started',
        subject: 'Flutter Docs',
      );

      expect(content, isNotNull);
      expect(content!.type, SharedContentType.url);
      expect(content.url, 'https://docs.flutter.dev/get-started');
      expect(content.title, 'Flutter Docs');
      expect(content.sourceType, SourceType.url);
    });

    // 2. Valid shared plain text
    test('2. Valid shared plain text parsed as text note', () {
      final content = SharedContentParser.parse(
        rawText: 'Meeting notes: review PR #42 tomorrow morning.',
        subject: 'Team Sync',
      );

      expect(content, isNotNull);
      expect(content!.type, SharedContentType.text);
      expect(content.text, 'Meeting notes: review PR #42 tomorrow morning.');
      expect(content.title, 'Team Sync');
      expect(content.sourceType, SourceType.text);
    });

    // 3. Text containing a URL
    test('3. Text containing embedded URL extracts URL and preserves context', () {
      final content = SharedContentParser.parse(
        rawText:
            'Check this awesome architecture guide: https://lens.example.com/arch for details',
      );

      expect(content, isNotNull);
      expect(content!.type, SharedContentType.url);
      expect(content.url, 'https://lens.example.com/arch');
      expect(content.title, 'Check this awesome architecture guide: for details');
      expect(content.sourceType, SourceType.url);
    });

    // 4. Empty and whitespace-only payload
    test('4. Empty and whitespace-only payloads return null', () {
      expect(SharedContentParser.parse(rawText: ''), isNull);
      expect(SharedContentParser.parse(rawText: '   \n\t  '), isNull);
      expect(SharedContentParser.parse(rawText: null), isNull);
    });

    // 5. Unsupported URI scheme
    test('5. Unsupported URI schemes are not recognized as URLs', () {
      final jsContent = SharedContentParser.parse(
        rawText: 'javascript:alert(document.cookie)',
      );
      expect(jsContent, isNotNull);
      expect(jsContent!.type, SharedContentType.text);

      final fileContent = SharedContentParser.parse(
        rawText: 'file:///etc/passwd',
      );
      expect(fileContent, isNotNull);
      expect(fileContent!.type, SharedContentType.text);

      final dataContent = SharedContentParser.parse(
        rawText: 'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
      );
      expect(dataContent, isNotNull);
      expect(dataContent!.type, SharedContentType.text);
    });

    // 6. Malformed URL
    test('6. Malformed URL strings are safely treated without crashing', () {
      final malformed = SharedContentParser.parse(rawText: 'https://');
      expect(malformed, isNotNull);
      // "https://" fails isValidUrl host check so it falls back safely to text note
      expect(malformed!.type, SharedContentType.text);
    });

    // 7. Oversized payload
    test('7. Oversized payload text and title are bounded to safe limits', () {
      final hugeText = 'A' * 1000500;
      final hugeSubject = 'B' * 600;

      final content = SharedContentParser.parse(
        rawText: hugeText,
        subject: hugeSubject,
      );

      expect(content, isNotNull);
      expect(content!.text!.length, SharedContentParser.maxTextLength);
      expect(content.title!.length, SharedContentParser.maxTitleLength);
    });

    // 8. Duplicate incoming share event
    test('8. Duplicate incoming share events within deduplication window are suppressed', () async {
      final fakePlatform = FakeIncomingSharePlatform();
      final service = IncomingShareService(platform: fakePlatform);

      final received = <SharedContent>[];
      final sub = service.onIncomingShare.listen(received.add);

      // Emit first share
      fakePlatform.emitShare({
        'text': 'https://duplicate.example.com',
        'subject': 'Duplicate Test',
      });
      await pumpEventQueue();

      expect(received.length, 1);

      // Emit identical share immediately
      fakePlatform.emitShare({
        'text': 'https://duplicate.example.com',
        'subject': 'Duplicate Test',
      });
      await pumpEventQueue();

      // Suppressed
      expect(received.length, 1);

      // Emit different share
      fakePlatform.emitShare({
        'text': 'https://different.example.com',
        'subject': 'Distinct Test',
      });
      await pumpEventQueue();

      expect(received.length, 2);

      await sub.cancel();
      service.dispose();
      fakePlatform.dispose();
    });
  });

  group('Stage 17: Incoming Share Review Experience & App Lifecycle', () {
    // 9. Cold-start share delivery
    testWidgets('9. Cold-start share delivery presents review screen over main shell',
        (tester) async {
      final fakePlatform = FakeIncomingSharePlatform(
        initialShare: {
          'text': 'https://coldstart.example.com',
          'subject': 'Cold Start Article',
        },
      );
      final service = IncomingShareService(platform: fakePlatform);
      final mockClient = MockApiClient();

      await tester.pumpWidget(
        LensApp(
          shareService: service,
          apiClient: mockClient,
        ),
      );
      await tester.pumpAndSettle();

      // Review screen should be open
      expect(find.text('Review Shared Content'), findsOneWidget);
      expect(find.text('Detected Web Link from Android Share Sheet'), findsOneWidget);
      expect(find.text('https://coldstart.example.com'), findsOneWidget);
      expect(find.text('Cold Start Article'), findsOneWidget);

      service.dispose();
      fakePlatform.dispose();
    });

    // 10. Warm-start share delivery
    testWidgets('10. Warm-start share delivery pushes review screen while app is running',
        (tester) async {
      final fakePlatform = FakeIncomingSharePlatform();
      final service = IncomingShareService(platform: fakePlatform);
      final mockClient = MockApiClient();

      await tester.pumpWidget(
        LensApp(
          shareService: service,
          apiClient: mockClient,
        ),
      );
      await tester.pumpAndSettle();

      // Initially on main navigation shell (Captures screen)
      expect(find.text('Review Shared Content'), findsNothing);
      expect(find.byType(CapturesScreen), findsOneWidget);

      // Deliver warm-start share
      fakePlatform.emitShare({
        'text': 'Meeting notes: discussed Q4 roadmap',
        'subject': 'Q4 Planning',
      });
      await tester.pumpAndSettle();

      // Review screen opens
      expect(find.text('Review Shared Content'), findsOneWidget);
      expect(find.text('Detected Text Note from Android Share Sheet'), findsOneWidget);
      expect(find.text('Meeting notes: discussed Q4 roadmap'), findsOneWidget);
      expect(find.text('Q4 Planning'), findsOneWidget);

      service.dispose();
      fakePlatform.dispose();
    });

    // 11. User cancellation
    testWidgets('11. User cancellation safely dismisses review without creating capture',
        (tester) async {
      bool cancelled = false;
      final mockClient = MockApiClient();

      final shared = SharedContent(
        type: SharedContentType.url,
        url: 'https://cancel.example.com',
        title: 'Cancel Me',
        rawText: 'https://cancel.example.com',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: ShareReviewScreen(
            sharedContent: shared,
            apiClient: mockClient,
            onCancel: () => cancelled = true,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Review Shared Content'), findsOneWidget);

      // Tap Cancel button
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(cancelled, isTrue);
      expect(mockClient.createCaptureCallCount, 0);
    });

    // 12. Successful API submission
    testWidgets('12. Successful API submission creates capture and navigates to detail',
        (tester) async {
      final mockClient = MockApiClient();

      final shared = SharedContent(
        type: SharedContentType.url,
        url: 'https://save.example.com',
        title: 'Initial Title',
        rawText: 'https://save.example.com',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: ShareReviewScreen(
            sharedContent: shared,
            apiClient: mockClient,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Edit title
      final titleField = find.widgetWithText(TextFormField, 'Initial Title');
      await tester.enterText(titleField, 'Edited Custom Title');

      // Tap Save
      await tester.tap(find.text('Ingest Web Link'));
      await tester.pumpAndSettle();

      expect(mockClient.createCaptureCallCount, 1);
      expect(mockClient.lastCreatePayload?.sourceType, SourceType.url);
      expect(mockClient.lastCreatePayload?.originalUrl, 'https://save.example.com');
      expect(mockClient.lastCreatePayload?.title, 'Edited Custom Title');

      // Replaces review screen with CaptureDetailScreen
      expect(find.byType(CaptureDetailScreen), findsOneWidget);
    });

    // 13. API failure and retry behavior
    testWidgets('13. API failure displays error banner and allows retry with preserved edits',
        (tester) async {
      int attempts = 0;
      final mockClient = MockApiClient(
        onCreateCapture: (payload) async {
          attempts++;
          if (attempts == 1) {
            throw ApiException(
              message: 'Connection timeout connecting to LENS backend.',
              statusCode: 504,
              isTimeout: true,
            );
          }
          return Capture(
            id: 'cap-retry-ok',
            sourceType: payload.sourceType,
            processingStatus: ProcessingStatus.completed,
            originalUrl: payload.originalUrl,
            title: payload.title,
            createdAt: DateTime.now(),
            updatedAt: DateTime.now(),
          );
        },
      );

      final shared = SharedContent(
        type: SharedContentType.url,
        url: 'https://retry.example.com',
        title: 'Original Title',
        rawText: 'https://retry.example.com',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: ShareReviewScreen(
            sharedContent: shared,
            apiClient: mockClient,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Modify title
      final titleField = find.widgetWithText(TextFormField, 'Original Title');
      await tester.enterText(titleField, 'Edited Title Before Retry');

      // Attempt 1: Fails
      await tester.tap(find.text('Ingest Web Link'));
      await tester.pumpAndSettle();

      expect(attempts, 1);
      expect(
        find.textContaining('Connection timeout connecting to LENS backend.'),
        findsOneWidget,
      );

      // Verify edited title was preserved
      expect(find.text('Edited Title Before Retry'), findsOneWidget);

      // Attempt 2: Succeeds on retry
      await tester.tap(find.text('Ingest Web Link'));
      await tester.pumpAndSettle();

      expect(attempts, 2);
      expect(find.byType(CaptureDetailScreen), findsOneWidget);
    });

    // 14. Rapid repeated Save taps
    testWidgets('14. Rapid repeated Save taps send exactly one API request',
        (tester) async {
      final completer = Completer<Capture>();
      final mockClient = MockApiClient(
        onCreateCapture: (payload) => completer.future,
      );

      final shared = SharedContent(
        type: SharedContentType.url,
        url: 'https://debounce.example.com',
        title: 'Debounce Title',
        rawText: 'https://debounce.example.com',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: ShareReviewScreen(
            sharedContent: shared,
            apiClient: mockClient,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Rapidly tap Save button 4 times
      await tester.tap(find.text('Ingest Web Link'));
      await tester.tap(find.text('Ingest Web Link'));
      await tester.tap(find.text('Ingest Web Link'));
      await tester.tap(find.text('Ingest Web Link'));

      expect(mockClient.createCaptureCallCount, 1);

      // Resolve API request
      completer.complete(
        Capture(
          id: 'cap-debounce-done',
          sourceType: SourceType.url,
          processingStatus: ProcessingStatus.completed,
          originalUrl: 'https://debounce.example.com',
          createdAt: DateTime.now(),
          updatedAt: DateTime.now(),
        ),
      );
      await tester.pumpAndSettle();

      expect(mockClient.createCaptureCallCount, 1);
      expect(find.byType(CaptureDetailScreen), findsOneWidget);
    });

    // 15. Existing capture creation regression
    testWidgets('15. Existing capture creation screen functions independently without regression',
        (tester) async {
      final mockClient = MockApiClient();

      await tester.pumpWidget(
        MaterialApp(
          home: NewCaptureScreen(
            apiClient: mockClient,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('New Capture'), findsOneWidget);
      expect(find.text('Web Link'), findsOneWidget);
      expect(find.text('Text Note'), findsOneWidget);

      // Ingest URL directly
      final urlField = find.byType(TextFormField).first;
      await tester.enterText(urlField, 'https://direct-capture.example.com');
      await tester.tap(find.text('Ingest Web Link'));
      await tester.pumpAndSettle();

      expect(mockClient.createCaptureCallCount, 1);
      expect(
        mockClient.lastCreatePayload?.originalUrl,
        'https://direct-capture.example.com',
      );
      expect(find.byType(CaptureDetailScreen), findsOneWidget);
    });
  });
}
