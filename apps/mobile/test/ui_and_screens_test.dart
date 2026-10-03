import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lens_mobile/core/network/api_client.dart';
import 'package:lens_mobile/core/theme/app_theme.dart';
import 'package:lens_mobile/main.dart';
import 'package:lens_mobile/models/capture.dart';
import 'package:lens_mobile/models/search_result.dart';
import 'package:lens_mobile/screens/capture_detail_screen.dart';
import 'package:lens_mobile/screens/captures_screen.dart';
import 'package:lens_mobile/screens/new_capture_screen.dart';
import 'package:lens_mobile/screens/search_screen.dart';
import 'package:lens_mobile/widgets/status_badge.dart';

// Lightweight fake client for deterministic UI testing
class FakeApiClient extends ApiClient {
  CaptureListResponse? listResponse;
  Capture? detailResponse;
  SearchResponse? searchResponse;
  Duration? searchDelay;
  int createCaptureCallCount = 0;
  Duration? createDelay;
  Capture? createResponse;
  int getCaptureCallCount = 0;

  FakeApiClient({
    this.listResponse,
    this.detailResponse,
    this.searchResponse,
    this.searchDelay,
    this.createDelay,
    this.createResponse,
  });

  @override
  Future<CaptureListResponse> listCaptures({int limit = 15, int offset = 0}) async {
    return listResponse ??
        const CaptureListResponse(
          items: [],
          total: 0,
          limit: 15,
          offset: 0,
        );
  }

  @override
  Future<Capture> getCapture(String id) async {
    getCaptureCallCount++;
    if (detailResponse != null) return detailResponse!;
    throw Exception('Capture not found');
  }

  @override
  Future<Capture> createCapture(CaptureCreate payload) async {
    createCaptureCallCount++;
    if (createDelay != null) {
      await Future.delayed(createDelay!);
    }
    return createResponse ??
        Capture(
          id: 'created-cap-1',
          sourceType: payload.sourceType,
          processingStatus: payload.sourceType == SourceType.url
              ? ProcessingStatus.pending
              : ProcessingStatus.completed,
          title: payload.title ?? 'Created Capture',
          originalUrl: payload.originalUrl,
          content: payload.content,
          createdAt: DateTime.now(),
          updatedAt: DateTime.now(),
        );
  }

  @override
  Future<SearchResponse> search({required String query, int limit = 20}) async {
    if (searchDelay != null) {
      await Future.delayed(searchDelay!);
    }
    return searchResponse ??
        SearchResponse(
          query: query,
          total: 0,
          limit: limit,
          degraded: false,
          results: [],
        );
  }
}

void main() {
  group('LENS Mobile UI & Screens (Tests 3, 4, 7, 8, 9, 10, 11)', () {
    // 3. Capture list state
    testWidgets('3. Renders capture list with titles, badges, and dates', (tester) async {
      final capture = Capture(
        id: 'cap-1',
        sourceType: SourceType.url,
        processingStatus: ProcessingStatus.completed,
        title: 'FastAPI Documentation',
        originalUrl: 'https://fastapi.tiangolo.com',
        content: null,
        createdAt: DateTime.parse('2026-10-02T12:00:00Z'),
        updatedAt: DateTime.parse('2026-10-02T12:00:00Z'),
      );
      final fakeClient = FakeApiClient(
        listResponse: CaptureListResponse(
          items: [capture],
          total: 1,
          limit: 15,
          offset: 0,
        ),
      );

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: CapturesScreen(apiClient: fakeClient),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('FastAPI Documentation'), findsOneWidget);
      expect(find.text('Web Link'), findsOneWidget);
      expect(find.text('Ready'), findsOneWidget);
      expect(find.text('https://fastapi.tiangolo.com'), findsOneWidget);
    });

    // 4. Empty capture state
    testWidgets('4. Displays empty state when no captures exist', (tester) async {
      final fakeClient = FakeApiClient(
        listResponse: const CaptureListResponse(
          items: [],
          total: 0,
          limit: 15,
          offset: 0,
        ),
      );

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: CapturesScreen(apiClient: fakeClient),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('No Captures Yet'), findsOneWidget);
      expect(find.text('Save a web link or quick note to get started.'), findsOneWidget);
    });

    // 7. Search state
    testWidgets('7. Submits search and renders matching items with score breakdown', (tester) async {
      final fakeClient = FakeApiClient(
        searchResponse: const SearchResponse(
          query: 'fastapi',
          total: 1,
          limit: 20,
          degraded: false,
          results: [
            SearchResultCapture(
              captureId: 'cap-1',
              title: 'FastAPI Guide',
              originalUrl: 'https://fastapi.tiangolo.com/guide',
              sourceType: 'url',
              bestScore: 0.89,
              bestLexicalScore: 0.85,
              bestSemanticScore: 0.93,
              matchingChunks: [
                SearchResultChunk(
                  chunkId: 'chk-1',
                  chunkIndex: 0,
                  contentExcerpt: 'FastAPI is a modern, fast web framework...',
                  score: 0.89,
                  lexicalScore: 0.85,
                  semanticScore: 0.93,
                ),
              ],
            ),
          ],
        ),
      );

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: SearchScreen(apiClient: fakeClient),
        ),
      );
      await tester.pumpAndSettle();

      // Enter search query
      final input = find.byType(TextField);
      await tester.enterText(input, 'fastapi');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();

      expect(find.text('FastAPI Guide'), findsOneWidget);
      expect(find.text('FastAPI is a modern, fast web framework...'), findsOneWidget);
      expect(find.text('Found 1 matching capture'), findsOneWidget);
      expect(find.text('Lexical: 85.0%'), findsOneWidget);
      expect(find.text('Semantic: 93.0%'), findsOneWidget);
    });

    // 8. Processing status rendering
    testWidgets('8. Correctly renders labels and badges for all processing statuses', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: Column(
              children: [
                StatusBadge(status: ProcessingStatus.pending),
                StatusBadge(status: ProcessingStatus.processing),
                StatusBadge(status: ProcessingStatus.completed),
                StatusBadge(status: ProcessingStatus.failed),
              ],
            ),
          ),
        ),
      );

      expect(find.text('Waiting to process'), findsOneWidget);
      expect(find.text('Processing'), findsOneWidget);
      expect(find.text('Ready'), findsOneWidget);
      expect(find.text('Processing failed'), findsOneWidget);
    });

    // 9. Failed processing rendering
    testWidgets('9. Renders safe backend processing_error banner in capture detail', (tester) async {
      final failedCapture = Capture(
        id: 'cap-err-1',
        sourceType: SourceType.url,
        processingStatus: ProcessingStatus.failed,
        processingError: 'SSRF blocked: local loopback address not permitted.',
        title: 'Blocked URL',
        originalUrl: 'http://127.0.0.1:8000',
        content: null,
        createdAt: DateTime.parse('2026-10-02T12:00:00Z'),
        updatedAt: DateTime.parse('2026-10-02T12:00:00Z'),
      );
      final fakeClient = FakeApiClient(detailResponse: failedCapture);

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: CaptureDetailScreen(
            captureId: 'cap-err-1',
            initialCapture: failedCapture,
            apiClient: fakeClient,
          ),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Ingestion Failed'), findsOneWidget);
      expect(find.text('SSRF blocked: local loopback address not permitted.'), findsOneWidget);
      expect(find.text('Processing failed'), findsOneWidget);
    });

    // 10. Navigation
    testWidgets('10. Navigation shell correctly switches tabs between Captures, Search, and New', (tester) async {
      await tester.pumpWidget(const LensApp());
      await tester.pumpAndSettle();

      expect(find.text('LENS Captures'), findsOneWidget);

      // Tap Search tab
      await tester.tap(find.text('Search'));
      await tester.pumpAndSettle();
      expect(find.text('Search Knowledge'), findsOneWidget);

      // Tap New tab
      await tester.tap(find.text('New'));
      await tester.pumpAndSettle();
      expect(find.text('New Capture'), findsOneWidget);

      // Tap Captures tab
      await tester.tap(find.text('Captures'));
      await tester.pumpAndSettle();
      expect(find.text('LENS Captures'), findsOneWidget);
    });

    // 11. Stale search response handling
    testWidgets('11. Discards older out-of-order in-flight search responses', (tester) async {
      final fakeClient = FakeApiClient();

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: SearchScreen(apiClient: fakeClient),
        ),
      );
      await tester.pumpAndSettle();

      final input = find.byType(TextField);

      // First query with slower mock delay
      fakeClient.searchDelay = const Duration(milliseconds: 200);
      fakeClient.searchResponse = const SearchResponse(
        query: 'slow',
        total: 1,
        limit: 20,
        degraded: false,
        results: [
          SearchResultCapture(
            captureId: 'slow-id',
            title: 'Older Slow Response',
            sourceType: 'text',
            bestScore: 0.5,
          ),
        ],
      );
      await tester.enterText(input, 'slow');
      await tester.testTextInput.receiveAction(TextInputAction.search);

      // Second query immediately after with zero delay
      fakeClient.searchDelay = Duration.zero;
      fakeClient.searchResponse = const SearchResponse(
        query: 'fast',
        total: 1,
        limit: 20,
        degraded: false,
        results: [
          SearchResultCapture(
            captureId: 'fast-id',
            title: 'Newer Fast Response',
            sourceType: 'text',
            bestScore: 0.9,
          ),
        ],
      );
      await tester.enterText(input, 'fast');
      await tester.testTextInput.receiveAction(TextInputAction.search);

      // Pump through time to allow both promises to resolve
      await tester.pump(const Duration(milliseconds: 300));
      await tester.pumpAndSettle();

      // Only the newer fast response must be visible
      expect(find.text('Newer Fast Response'), findsOneWidget);
      expect(find.text('Older Slow Response'), findsNothing);
    });

    // 12. Double-submit protection in NewCaptureScreen
    testWidgets('12. Prevents double submission when tapping submit button rapidly', (tester) async {
      final fakeClient = FakeApiClient(createDelay: const Duration(milliseconds: 200));

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: NewCaptureScreen(apiClient: fakeClient),
        ),
      );
      await tester.pumpAndSettle();

      // Enter valid URL
      final urlField = find.byType(TextFormField).first;
      await tester.enterText(urlField, 'https://example.com/test');
      await tester.pumpAndSettle();

      final submitBtn = find.text('Ingest Web Link');
      // Tap submit button twice in rapid succession
      await tester.tap(submitBtn);
      await tester.tap(submitBtn);
      await tester.pump(const Duration(milliseconds: 50));

      // Wait for delayed creation to finish
      await tester.pump(const Duration(milliseconds: 250));
      await tester.pumpAndSettle();

      // createCapture must only have been invoked exactly ONCE
      expect(fakeClient.createCaptureCallCount, 1);
    });

    // 13. Pagination deduplication in CapturesScreen
    testWidgets('13. CapturesScreen deduplicates overlapping items when loading more', (tester) async {
      final initialItems = List.generate(
        15,
        (i) => Capture(
          id: 'cap-$i',
          sourceType: SourceType.text,
          processingStatus: ProcessingStatus.completed,
          title: 'Capture Item #$i',
          createdAt: DateTime.parse('2026-10-02T12:00:00Z'),
          updatedAt: DateTime.parse('2026-10-02T12:00:00Z'),
        ),
      );

      final fakeClient = FakeApiClient(
        listResponse: CaptureListResponse(
          items: initialItems,
          total: 16,
          limit: 15,
          offset: 0,
        ),
      );

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: CapturesScreen(apiClient: fakeClient),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Capture Item #0'), findsOneWidget);

      // Now prepare second page that includes cap-14 again (overlapping) and cap-15 (new)
      final newItem = Capture(
        id: 'cap-15',
        sourceType: SourceType.text,
        processingStatus: ProcessingStatus.completed,
        title: 'Capture Item #15',
        createdAt: DateTime.parse('2026-10-02T10:00:00Z'),
        updatedAt: DateTime.parse('2026-10-02T10:00:00Z'),
      );
      fakeClient.listResponse = CaptureListResponse(
        items: [initialItems.last, newItem], // cap-14 is repeated
        total: 16,
        limit: 15,
        offset: 15,
      );

      // Scroll down to trigger load more
      await tester.drag(find.byType(ListView), const Offset(0, -2000));
      await tester.pump();
      await tester.pumpAndSettle();

      // Overlapping cap-14 must still only be rendered ONCE and new item cap-15 must be present
      expect(find.text('Capture Item #14'), findsOneWidget);
      expect(find.text('Capture Item #15'), findsOneWidget);
    });

    // 14. Polling terminates immediately when capture is completed
    testWidgets('14. CaptureDetailScreen stops polling when capture completes', (tester) async {
      final initialCapture = Capture(
        id: 'cap-poll-1',
        sourceType: SourceType.url,
        processingStatus: ProcessingStatus.processing,
        title: 'Processing Item',
        createdAt: DateTime.parse('2026-10-02T12:00:00Z'),
        updatedAt: DateTime.parse('2026-10-02T12:00:00Z'),
      );

      final completedCapture = Capture(
        id: 'cap-poll-1',
        sourceType: SourceType.url,
        processingStatus: ProcessingStatus.completed,
        title: 'Completed Item',
        createdAt: DateTime.parse('2026-10-02T12:00:00Z'),
        updatedAt: DateTime.parse('2026-10-02T12:00:00Z'),
      );

      final fakeClient = FakeApiClient(detailResponse: completedCapture);

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: CaptureDetailScreen(
            captureId: 'cap-poll-1',
            initialCapture: initialCapture,
            apiClient: fakeClient,
          ),
        ),
      );
      await tester.pump();

      // Initial state is processing
      expect(find.text('Processing Webpage'), findsOneWidget);

      // Advance clock past 1 poll cycle (3 seconds)
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      // Should now show completed "Ready" status and no processing banner
      expect(find.text('Ready'), findsOneWidget);
      expect(find.text('Processing Webpage'), findsNothing);

      final callCountAfterComplete = fakeClient.getCaptureCallCount;
      // Advance clock further — polling must NOT continue
      await tester.pump(const Duration(seconds: 10));
      await tester.pumpAndSettle();

      expect(fakeClient.getCaptureCallCount, callCountAfterComplete);
    });

    // 15. Polling timer disposal on screen pop
    testWidgets('15. CaptureDetailScreen cancels polling timer cleanly on disposal', (tester) async {
      final pendingCapture = Capture(
        id: 'cap-poll-2',
        sourceType: SourceType.url,
        processingStatus: ProcessingStatus.pending,
        title: 'Pending Item',
        createdAt: DateTime.parse('2026-10-02T12:00:00Z'),
        updatedAt: DateTime.parse('2026-10-02T12:00:00Z'),
      );

      final fakeClient = FakeApiClient(detailResponse: pendingCapture);

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Scaffold(
            body: Builder(
              builder: (ctx) => ElevatedButton(
                onPressed: () {
                  Navigator.of(ctx).push(
                    MaterialPageRoute(
                      builder: (_) => CaptureDetailScreen(
                        captureId: 'cap-poll-2',
                        initialCapture: pendingCapture,
                        apiClient: fakeClient,
                      ),
                    ),
                  );
                },
                child: const Text('Open Detail'),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Open detail
      await tester.tap(find.text('Open Detail'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('Queued for Ingestion'), findsOneWidget);

      // Pop the screen back
      Navigator.of(tester.element(find.byType(CaptureDetailScreen))).pop();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));

      final countAtDispose = fakeClient.getCaptureCallCount;

      // Advance time by 15 seconds — no timer should trigger or call getCapture
      await tester.pump(const Duration(seconds: 15));
      await tester.pump();

      expect(fakeClient.getCaptureCallCount, countAtDispose);
    });

    // 16. Search query validation
    testWidgets('16. SearchScreen ignores empty or whitespace queries without network requests', (tester) async {
      final fakeClient = FakeApiClient();

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: SearchScreen(apiClient: fakeClient),
        ),
      );
      await tester.pumpAndSettle();

      final input = find.byType(TextField);
      await tester.enterText(input, '    ');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();

      // Search response remains null, placeholder still present
      expect(find.text('Hybrid Knowledge Retrieval'), findsOneWidget);
    });
  });
}
