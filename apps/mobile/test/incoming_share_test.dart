import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lens_mobile/core/errors/api_exception.dart';
import 'package:lens_mobile/core/network/api_client.dart';
import 'package:lens_mobile/core/share/incoming_share_service.dart';
import 'package:lens_mobile/core/share/shared_content.dart';
import 'package:lens_mobile/main.dart';
import 'package:lens_mobile/models/capture.dart';
import 'package:lens_mobile/models/content_chunk.dart';
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

    // 16. URL boundary sentence punctuation trimming
    test('16. URL boundary sentence punctuation trimming (. , ; : ! ? " \' )', () {
      final periodShare = SharedContentParser.parse(
        rawText: 'Check this article: https://example.com/guide.',
      );
      expect(periodShare, isNotNull);
      expect(periodShare!.type, SharedContentType.url);
      expect(periodShare.url, 'https://example.com/guide');
      expect(periodShare.text, 'Check this article:');

      final commaShare = SharedContentParser.parse(
        rawText: 'https://example.com/item,',
      );
      expect(commaShare, isNotNull);
      expect(commaShare!.type, SharedContentType.url);
      expect(commaShare.url, 'https://example.com/item');
      expect(commaShare.text, isNull);

      final exclamationShare = SharedContentParser.parse(
        rawText: 'Breaking news https://example.com/news!',
      );
      expect(exclamationShare, isNotNull);
      expect(exclamationShare!.type, SharedContentType.url);
      expect(exclamationShare.url, 'https://example.com/news');
      expect(exclamationShare.text, 'Breaking news');

      final questionShare = SharedContentParser.parse(
        rawText: 'Have you seen https://example.com/faq?',
      );
      expect(questionShare, isNotNull);
      expect(questionShare!.type, SharedContentType.url);
      expect(questionShare.url, 'https://example.com/faq');
      expect(questionShare.text, 'Have you seen');
    });

    // Finding A Required Behaviors: Standalone URL vs Trailing Prose vs Balanced Parentheses
    test('Finding A: Distinct standalone URL, wrapped URL, trailing punctuation, and trailing prose', () {
      // 1. Standalone URL
      final standalone = SharedContentParser.parse(rawText: 'https://example.com');
      expect(standalone, isNotNull);
      expect(standalone!.type, SharedContentType.url);
      expect(standalone.url, 'https://example.com');
      expect(standalone.text, isNull);

      // 2. Wrapped in punctuation
      final wrapped = SharedContentParser.parse(rawText: '(https://example.com)');
      expect(wrapped, isNotNull);
      expect(wrapped!.type, SharedContentType.url);
      expect(wrapped.url, 'https://example.com');
      expect(wrapped.text, isNull);

      // 3. Followed by sentence punctuation (standalone)
      final withPeriod = SharedContentParser.parse(rawText: 'https://example.com.');
      expect(withPeriod, isNotNull);
      expect(withPeriod!.type, SharedContentType.url);
      expect(withPeriod.url, 'https://example.com');
      expect(withPeriod.text, isNull);

      // 4. Standalone URL followed by explanatory prose
      final urlWithProse = SharedContentParser.parse(rawText: 'https://example.com. read this');
      expect(urlWithProse, isNotNull);
      expect(urlWithProse!.type, SharedContentType.url);
      expect(urlWithProse.url, 'https://example.com');
      expect(urlWithProse.text, 'read this');
      expect(urlWithProse.title, 'read this');

      // 5. Prose before URL
      final proseBeforeUrl = SharedContentParser.parse(rawText: 'Read this: https://example.com/article');
      expect(proseBeforeUrl, isNotNull);
      expect(proseBeforeUrl!.type, SharedContentType.url);
      expect(proseBeforeUrl.url, 'https://example.com/article');
      expect(proseBeforeUrl.text, 'Read this:');
      expect(proseBeforeUrl.title, 'Read this:');

      // 6. Preserves balanced parentheses that are part of the URL
      final wikiBalanced = SharedContentParser.parse(rawText: 'https://en.wikipedia.org/wiki/LENS_(disambiguation)');
      expect(wikiBalanced, isNotNull);
      expect(wikiBalanced!.type, SharedContentType.url);
      expect(wikiBalanced.url, 'https://en.wikipedia.org/wiki/LENS_(disambiguation)');
      expect(wikiBalanced.text, isNull);

      // 7. Multiple URLs: Primary URL plus retained secondary URL/context
      final multiUrls = SharedContentParser.parse(rawText: 'See https://example.com and https://other.example');
      expect(multiUrls, isNotNull);
      expect(multiUrls!.type, SharedContentType.url);
      expect(multiUrls.url, 'https://example.com');
      expect(multiUrls.text, 'See and https://other.example');
      expect(multiUrls.title, 'See and https://other.example');

      // 8. Separator punctuation (colon or dash) between URL and prose
      final colonProse = SharedContentParser.parse(rawText: 'https://example.com: read this');
      expect(colonProse, isNotNull);
      expect(colonProse!.type, SharedContentType.url);
      expect(colonProse.url, 'https://example.com');
      expect(colonProse.text, 'read this');

      final dashProse = SharedContentParser.parse(rawText: 'https://example.com - read this');
      expect(dashProse, isNotNull);
      expect(dashProse!.type, SharedContentType.url);
      expect(dashProse.url, 'https://example.com');
      expect(dashProse.text, 'read this');

      // 9. URL with prose before and after
      final beforeAndAfter = SharedContentParser.parse(
        rawText: 'Check out https://example.com/guide. It has great info.',
      );
      expect(beforeAndAfter, isNotNull);
      expect(beforeAndAfter!.type, SharedContentType.url);
      expect(beforeAndAfter.url, 'https://example.com/guide');
      expect(beforeAndAfter.text, 'Check out. It has great info.');
    });

    // 17. Parentheses handling: wrapped URL vs balanced Wikipedia URLs
    test('17. Parentheses handling: wrapped URL vs balanced Wikipedia URLs', () {
      // Wrapped URL in parentheses
      final wrapped = SharedContentParser.parse(
        rawText: '(https://example.com/doc)',
      );
      expect(wrapped, isNotNull);
      expect(wrapped!.type, SharedContentType.url);
      expect(wrapped.url, 'https://example.com/doc');
      expect(wrapped.text, isNull);

      // Wikipedia balanced parentheses
      final wiki = SharedContentParser.parse(
        rawText: 'https://en.wikipedia.org/wiki/LENS_(disambiguation)',
      );
      expect(wiki, isNotNull);
      expect(wiki!.type, SharedContentType.url);
      expect(wiki.url, 'https://en.wikipedia.org/wiki/LENS_(disambiguation)');
      expect(wiki.text, isNull);

      // Wrapped Wikipedia URL with surrounding context
      final wrappedWiki = SharedContentParser.parse(
        rawText:
            'Read about disambiguation (https://en.wikipedia.org/wiki/LENS_(disambiguation)) for details',
      );
      expect(wrappedWiki, isNotNull);
      expect(wrappedWiki!.type, SharedContentType.url);
      expect(
        wrappedWiki.url,
        'https://en.wikipedia.org/wiki/LENS_(disambiguation)',
      );
      expect(wrappedWiki.text, 'Read about disambiguation for details');
      expect(wrappedWiki.title, 'Read about disambiguation for details');
    });

    // 18. Multiple URLs in single text: first extracted, remainder preserved in context
    test('18. Multiple URLs in single text extracts first URL and retains second URL in context', () {
      final multiUrl = SharedContentParser.parse(
        rawText:
            'Primary: https://primary.example.com and secondary: https://secondary.example.com for backup',
      );
      expect(multiUrl, isNotNull);
      expect(multiUrl!.type, SharedContentType.url);
      expect(multiUrl.url, 'https://primary.example.com');
      expect(
        multiUrl.text,
        'Primary: and secondary: https://secondary.example.com for backup',
      );
      expect(
        multiUrl.title,
        'Primary: and secondary: https://secondary.example.com for backup',
      );
    });

    // 19. Oversized URL candidate exceeds 2048 chars falls back safely to text note
    test('19. Oversized URL candidate exceeding 2048 chars is treated as text note', () {
      final hugeUrl = 'https://example.com/${'a' * 2050}';
      final content = SharedContentParser.parse(rawText: hugeUrl);

      expect(content, isNotNull);
      expect(content!.type, SharedContentType.text);
      expect(content.url, isNull);
      expect(content.text, isNotNull);
    });

    // 20. Deduplication window expiry allows identical share after window expires
    test('20. Deduplication window expiry allows identical share after debounce duration', () async {
      DateTime simulatedNow = DateTime(2026, 3, 1, 10, 0, 0);
      final fakePlatform = FakeIncomingSharePlatform();
      final service = IncomingShareService(
        platform: fakePlatform,
        debounceDuration: const Duration(milliseconds: 1500),
        clock: () => simulatedNow,
      );

      final received = <SharedContent>[];
      final sub = service.onIncomingShare.listen(received.add);

      // Share 1
      fakePlatform.emitShare({
        'text': 'https://re-share.example.com',
        'subject': 'Daily Read',
      });
      await pumpEventQueue();
      expect(received.length, 1);

      // Share 1 duplicated within 500ms -> suppressed
      simulatedNow = simulatedNow.add(const Duration(milliseconds: 500));
      fakePlatform.emitShare({
        'text': 'https://re-share.example.com',
        'subject': 'Daily Read',
      });
      await pumpEventQueue();
      expect(received.length, 1);

      // Advance clock past 1500ms window (1600ms total from first share)
      simulatedNow = simulatedNow.add(const Duration(milliseconds: 1100));
      fakePlatform.emitShare({
        'text': 'https://re-share.example.com',
        'subject': 'Daily Read',
      });
      await pumpEventQueue();
      expect(received.length, 2);

      await sub.cancel();
      service.dispose();
      fakePlatform.dispose();
    });

    // 21. Multi-line text representation (simulating ACTION_SEND_MULTIPLE newline joining)
    test('21. Multi-line text representation preserves all lines cleanly', () {
      final multiLine = SharedContentParser.parse(
        rawText:
            'Item 1: Note on architecture\n\nItem 2: Link to specs\n\nItem 3: Action items',
      );
      expect(multiLine, isNotNull);
      expect(multiLine!.type, SharedContentType.text);
      expect(
        multiLine.text,
        'Item 1: Note on architecture\n\nItem 2: Link to specs\n\nItem 3: Action items',
      );
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
      await tester.ensureVisible(find.text('Ingest Web Link'));
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

    // 16 (Lifecycle). URL context preservation in review screen and CaptureCreate payload
    testWidgets(
        '16. URL context preservation in review screen and CaptureCreate payload',
        (tester) async {
      final mockClient = MockApiClient();
      final shared = SharedContent(
        type: SharedContentType.url,
        url: 'https://context.example.com/article',
        title: 'Initial Title',
        text: 'Surrounding explanatory context from author',
        rawText:
            'Surrounding explanatory context from author https://context.example.com/article',
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

      // Verify the URL, Title, and Context / Notes fields are rendered
      expect(find.text('https://context.example.com/article'), findsOneWidget);
      expect(find.text('Initial Title'), findsOneWidget);
      expect(
        find.text('Surrounding explanatory context from author'),
        findsOneWidget,
      );

      // Edit context field
      final contextField = find.widgetWithText(
        TextFormField,
        'Surrounding explanatory context from author',
      );
      await tester.enterText(contextField, 'User edited notes and thoughts');

      // Submit
      await tester.ensureVisible(find.text('Ingest Web Link'));
      await tester.tap(find.text('Ingest Web Link'));
      await tester.pumpAndSettle();

      // Assert submitted payload preserves originalUrl, title, and edited context
      expect(mockClient.createCaptureCallCount, 1);
      final payload = mockClient.lastCreatePayload;
      expect(payload, isNotNull);
      expect(payload!.sourceType, SourceType.url);
      expect(payload.originalUrl, 'https://context.example.com/article');
      expect(payload.title, 'Initial Title');
      expect(payload.content, 'User edited notes and thoughts');
      expect(find.byType(CaptureDetailScreen), findsOneWidget);
    });
  });

  group('Stage 17.1: PR #9 Forensic Remediation Regressions', () {
    test('1. Deduplication collision prevention across discrete text and subject fields', () async {
      final fakePlatform = FakeIncomingSharePlatform();
      final now = DateTime(2026, 11, 6, 12, 0, 0);
      final service = IncomingShareService(
        platform: fakePlatform,
        debounceDuration: const Duration(milliseconds: 1500),
        clock: () => now,
      );

      final receivedShares = <SharedContent>[];
      final sub = service.onIncomingShare.listen((content) {
        receivedShares.add(content);
      });

      // Pair A: text: "alpha|beta", subject: "gamma"
      fakePlatform.emitShare({
        'text': 'alpha|beta',
        'subject': 'gamma',
      });

      // Pair B: text: "alpha", subject: "beta|gamma" (same delimiter string, but different fields)
      fakePlatform.emitShare({
        'text': 'alpha',
        'subject': 'beta|gamma',
      });

      await pumpEventQueue();

      expect(receivedShares.length, 2);
      expect(receivedShares[0].rawText, 'alpha|beta');
      expect(receivedShares[0].subject, 'gamma');
      expect(receivedShares[1].rawText, 'alpha');
      expect(receivedShares[1].subject, 'beta|gamma');

      await sub.cancel();
      service.dispose();
      fakePlatform.dispose();
    });

    test('2. Search past invalid candidate to first valid HTTP/HTTPS URL', () {
      // First candidate is invalid (missing host or malformed), second is valid
      final content = SharedContentParser.parse(
        rawText: 'See http:// and https://flutter.dev/docs for guide',
      );

      expect(content, isNotNull);
      expect(content!.type, SharedContentType.url);
      expect(content.url, 'https://flutter.dev/docs');
      expect(content.text, contains('See http:// and for guide'));

      // Also verify pure HTTP scheme
      final httpContent = SharedContentParser.parse(
        rawText: 'http://example.com/legacy-api',
      );
      expect(httpContent, isNotNull);
      expect(httpContent!.type, SharedContentType.url);
      expect(httpContent.url, 'http://example.com/legacy-api');
    });

    test('3. Preserve meaningful code and markdown punctuation in surrounding context', () {
      final content = SharedContentParser.parse(
        rawText: 'Call refresh() before opening https://example.com/docs',
      );

      expect(content, isNotNull);
      expect(content!.type, SharedContentType.url);
      expect(content.url, 'https://example.com/docs');
      expect(content.text, 'Call refresh() before opening');
      expect(content.title, 'Call refresh() before opening');
    });

    test('4. Bound URL context text to maxTextLength', () {
      final oversizedText = 'https://example.com/doc ${'X' * 1500000}';
      final content = SharedContentParser.parse(
        rawText: oversizedText,
      );

      expect(content, isNotNull);
      expect(content!.type, SharedContentType.url);
      expect(content.url, 'https://example.com/doc');
      expect(content.text, isNotNull);
      expect(content.text!.length, SharedContentParser.maxTextLength);
    });

    test('5. Remove matched single quotes around URL while preserving internal apostrophes', () {
      // Enclosed in matching single quotes without extra text
      final enclosed = SharedContentParser.parse(
        rawText: "'https://example.com/article'",
      );
      expect(enclosed, isNotNull);
      expect(enclosed!.type, SharedContentType.url);
      expect(enclosed.url, 'https://example.com/article');
      expect(enclosed.text, isNull);

      // Enclosed in matching single quotes with surrounding text
      final enclosedWithText = SharedContentParser.parse(
        rawText: "Check out 'https://example.com/article' today",
      );
      expect(enclosedWithText, isNotNull);
      expect(enclosedWithText!.type, SharedContentType.url);
      expect(enclosedWithText.url, 'https://example.com/article');
      expect(enclosedWithText.text, 'Check out today');

      // Internal apostrophe preserved
      final apostrophe = SharedContentParser.parse(
        rawText: "https://example.com/o'reilly",
      );
      expect(apostrophe, isNotNull);
      expect(apostrophe!.type, SharedContentType.url);
      expect(apostrophe.url, "https://example.com/o'reilly");
    });

    test('6. Linear candidate cleanup performance with 50,000 trailing parentheses', () {
      final raw = 'https://example.com/test${')' * 50000}';
      final stopwatch = Stopwatch()..start();
      final content = SharedContentParser.parse(rawText: raw);
      stopwatch.stop();

      expect(content, isNotNull);
      expect(content!.type, SharedContentType.url);
      expect(content.url, 'https://example.com/test');
      expect(stopwatch.elapsedMilliseconds, lessThan(1000));
    });

    testWidgets('7a. Preserve shared URL and surrounding prose when switching to Text Note tab', (tester) async {
      final withProse = SharedContent(
        type: SharedContentType.url,
        url: 'https://example.com/article',
        title: 'Initial Title',
        text: 'Important read',
        rawText: 'Important read https://example.com/article',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: ShareReviewScreen(
            sharedContent: withProse,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Switch to Text Note
      await tester.tap(find.text('Text Note'));
      await tester.pumpAndSettle();

      // Note content field should now contain both the prose and the URL
      expect(find.text('Important read\n\nhttps://example.com/article'), findsOneWidget);
    });

    testWidgets('7b. Standalone shared URL populates note content when switching to Text Note tab', (tester) async {
      final standalone = SharedContent(
        type: SharedContentType.url,
        url: 'https://example.com/standalone',
        rawText: 'https://example.com/standalone',
      );

      await tester.pumpWidget(
        MaterialApp(
          home: ShareReviewScreen(
            sharedContent: standalone,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Switch to Text Note
      await tester.tap(find.text('Text Note'));
      await tester.pumpAndSettle();

      // Note content field should contain the standalone URL
      expect(find.text('https://example.com/standalone'), findsOneWidget);
    });

    testWidgets('8. PopScope blocks back navigation while save is pending', (tester) async {
      final completer = Completer<Capture>();
      final mockClient = MockApiClient(
        onCreateCapture: (payload) => completer.future,
      );

      final shared = SharedContent(
        type: SharedContentType.url,
        url: 'https://popscope.example.com',
        rawText: 'https://popscope.example.com',
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

      // Initially canPop is true
      final popScopeBefore = tester.widget<PopScope>(find.byType(PopScope));
      expect(popScopeBefore.canPop, isTrue);

      // Tap Ingest Web Link to start async submission
      await tester.tap(find.text('Ingest Web Link'));
      await tester.pump();

      // While submitting, canPop must be false to block system Back
      final popScopeSubmitting = tester.widget<PopScope>(find.byType(PopScope));
      expect(popScopeSubmitting.canPop, isFalse);

      // Complete submission
      completer.complete(Capture(
        id: 'cap-complete-1',
        sourceType: SourceType.url,
        processingStatus: ProcessingStatus.completed,
        originalUrl: 'https://popscope.example.com',
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
      ));
      await tester.pumpAndSettle();

      expect(find.byType(CaptureDetailScreen), findsOneWidget);
    });

    testWidgets('9a. CaptureDetailScreen renders saved URL context alongside extracted chunks', (tester) async {
      final captureWithContext = Capture(
        id: 'cap-with-ctx',
        sourceType: SourceType.url,
        processingStatus: ProcessingStatus.completed,
        originalUrl: 'https://example.com/with-context',
        title: 'Context Article',
        content: 'User personal notes on this link',
        chunks: [
          ContentChunk(
            id: 'chk-1',
            chunkIndex: 0,
            content: 'Extracted article body from website',
            createdAt: DateTime.now(),
          ),
        ],
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: CaptureDetailScreen(
            captureId: captureWithContext.id,
            initialCapture: captureWithContext,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Expect to find Context / Notes section with user notes
      expect(find.text('Context / Notes'), findsOneWidget);
      expect(find.text('User personal notes on this link'), findsOneWidget);

      // Expect to find Extracted Chunks section
      expect(find.text('Extracted Chunks (1)'), findsOneWidget);
      expect(find.text('Extracted article body from website'), findsOneWidget);
    });

    testWidgets('9b. CaptureDetailScreen suppresses duplicate context when content matches chunks (backfill)', (tester) async {
      final captureWithBackfill = Capture(
        id: 'cap-backfilled',
        sourceType: SourceType.url,
        processingStatus: ProcessingStatus.completed,
        originalUrl: 'https://example.com/backfilled',
        title: 'Backfilled Article',
        content: 'Extracted article body from website',
        chunks: [
          ContentChunk(
            id: 'chk-1',
            chunkIndex: 0,
            content: 'Extracted article body from website',
            createdAt: DateTime.now(),
          ),
        ],
        createdAt: DateTime.now(),
        updatedAt: DateTime.now(),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: CaptureDetailScreen(
            captureId: captureWithBackfill.id,
            initialCapture: captureWithBackfill,
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Expect Context / Notes to NOT be rendered (avoids duplicate page text)
      expect(find.text('Context / Notes'), findsNothing);

      // Extracted Chunks section is rendered
      expect(find.text('Extracted Chunks (1)'), findsOneWidget);
      expect(find.text('Extracted article body from website'), findsOneWidget);
    });
  });
}
