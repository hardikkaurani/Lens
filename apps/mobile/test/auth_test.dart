import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:lens_mobile/core/auth/auth_service.dart';
import 'package:lens_mobile/core/auth/auth_token_storage.dart';
import 'package:lens_mobile/core/errors/api_exception.dart';
import 'package:lens_mobile/core/network/api_client.dart';
import 'package:lens_mobile/core/share/incoming_share_service.dart';
import 'package:lens_mobile/main.dart';
import 'package:lens_mobile/models/capture.dart';
import 'package:lens_mobile/models/user.dart';
import 'package:lens_mobile/screens/login_screen.dart';
import 'package:lens_mobile/screens/register_screen.dart';
import 'package:lens_mobile/widgets/lens_logo.dart';

/// Test HTTP client for mocking responses and asserting on outgoing headers/bodies.
class MockHttpClient extends http.BaseClient {
  final Future<http.Response> Function(http.BaseRequest request) handler;
  final List<http.BaseRequest> recordedRequests = [];

  MockHttpClient(this.handler);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    recordedRequests.add(request);
    final response = await handler(request);
    return http.StreamedResponse(
      Stream.value(utf8.encode(response.body)),
      response.statusCode,
      headers: response.headers,
      request: request,
    );
  }
}

/// Fake platform for simulating Android Share Sheet intents.
class FakeSharePlatform implements IncomingSharePlatform {
  final _controller = StreamController<Map<String, dynamic>>.broadcast();
  Map<String, dynamic>? initialShare;

  FakeSharePlatform({this.initialShare});

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

void main() {
  group('1. Secure Token Storage (AuthTokenStorage)', () {
    test('in-memory storage correctly saves, retrieves, and clears tokens', () async {
      final storage = InMemoryAuthTokenStorage();

      expect(await storage.hasToken(), isFalse);
      expect(await storage.getToken(), isNull);

      await storage.saveToken('jwt_test_token_12345');
      expect(await storage.hasToken(), isTrue);
      expect(await storage.getToken(), equals('jwt_test_token_12345'));

      await storage.clearToken();
      expect(await storage.hasToken(), isFalse);
      expect(await storage.getToken(), isNull);
    });

    test('trims whitespace and treats empty token as clear', () async {
      final storage = InMemoryAuthTokenStorage();

      await storage.saveToken('   token_with_whitespace   ');
      expect(await storage.getToken(), equals('token_with_whitespace'));

      await storage.saveToken('    ');
      expect(await storage.hasToken(), isFalse);
      expect(await storage.getToken(), isNull);
    });
  });

  group('2. Authentication Service Lifecycle (AuthService)', () {
    test('initializes as unauthenticated when storage is empty', () {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);

      expect(auth.isAuthenticated, isFalse);
      expect(auth.currentUser, isNull);
      expect(auth.status, equals(AuthStatus.initial));
    });

    test('setSession updates user, stores token, and notifies listeners', () async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);
      bool notified = false;
      auth.addListener(() => notified = true);

      const user = User(id: 'u-1', email: 'test@lens.app', isActive: true);
      await auth.setSession(user: user, token: 'mock_jwt_access_token');

      expect(notified, isTrue);
      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser, equals(user));
      expect(await storage.getToken(), equals('mock_jwt_access_token'));
    });

    test('handleSessionExpired clears token and user profile safely', () async {
      final storage = InMemoryAuthTokenStorage('existing_token');
      final auth = AuthService(storage: storage);
      const user = User(id: 'u-1', email: 'test@lens.app', isActive: true);
      await auth.setSession(user: user, token: 'existing_token');

      await auth.handleSessionExpired();

      expect(auth.isAuthenticated, isFalse);
      expect(auth.currentUser, isNull);
      expect(await storage.getToken(), isNull);
      expect(auth.status, equals(AuthStatus.unauthenticated));
    });

    test('restoreSession restores user profile when valid token exists', () async {
      final storage = InMemoryAuthTokenStorage('saved_token');
      final auth = AuthService(storage: storage);
      const user = User(id: 'u-42', email: 'restored@lens.app', isActive: true);

      await auth.restoreSession(() async => user);

      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.email, equals('restored@lens.app'));
    });

    test('restoreSession clears token if profile fetch fails with 401', () async {
      final storage = InMemoryAuthTokenStorage('expired_token');
      final auth = AuthService(storage: storage);

      await auth.restoreSession(() async {
        throw const ApiException(statusCode: 401, message: 'Unauthorized');
      });

      expect(auth.isAuthenticated, isFalse);
      expect(await storage.getToken(), isNull);
    });

    test('restoreSession preserves token and sets restorationFailed on network failure', () async {
      final storage = InMemoryAuthTokenStorage('saved_offline_token');
      final auth = AuthService(storage: storage);

      await auth.restoreSession(() async {
        throw ApiException.network(details: 'Connection refused');
      });

      expect(auth.isAuthenticated, isFalse);
      expect(auth.status, equals(AuthStatus.restorationFailed));
      expect(auth.isRestorationFailed, isTrue);
      // Critical security & resilience guarantee: token must NOT be cleared on network failure
      expect(await storage.getToken(), equals('saved_offline_token'));
    });

    test('restoreSession preserves token on timeout and allows retry', () async {
      final storage = InMemoryAuthTokenStorage('saved_timeout_token');
      final auth = AuthService(storage: storage);

      await auth.restoreSession(() async {
        throw ApiException.timeout();
      });

      expect(auth.status, equals(AuthStatus.restorationFailed));
      expect(await storage.getToken(), equals('saved_timeout_token'));

      // Retry restores successfully once connection is back
      const user = User(id: 'u-retry', email: 'retry@lens.app', isActive: true);
      await auth.retryRestoreSession(() async => user);

      expect(auth.isAuthenticated, isTrue);
      expect(auth.status, equals(AuthStatus.authenticated));
      expect(auth.currentUser?.email, equals('retry@lens.app'));
    });

    test('clearSessionAndLogin purges preserved token and resets to unauthenticated', () async {
      final storage = InMemoryAuthTokenStorage('saved_token');
      final auth = AuthService(storage: storage);

      await auth.restoreSession(() async {
        throw ApiException.network();
      });
      expect(auth.status, equals(AuthStatus.restorationFailed));

      await auth.clearSessionAndLogin();
      expect(auth.status, equals(AuthStatus.unauthenticated));
      expect(await storage.getToken(), isNull);
    });
  });

  group('3. ApiClient Bearer Token Injection & Expiry Handling', () {
    test('injects Authorization: Bearer token header on protected requests', () async {
      final storage = InMemoryAuthTokenStorage();
      final mockHttp = MockHttpClient((req) async {
        expect(req.headers['authorization'], equals('Bearer bearer_token_xyz'));
        return http.Response(
          jsonEncode({
            'captures': [],
            'total': 0,
            'limit': 15,
            'offset': 0,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final client = ApiClient(
        httpClient: mockHttp,
        tokenStorage: storage,
      );
      await storage.saveToken('bearer_token_xyz', backendAuthority: client.currentAuthority);

      final res = await client.listCaptures();
      expect(res.total, equals(0));
      expect(mockHttp.recordedRequests, hasLength(1));
    });

    test('omits Authorization header for health and unauthenticated endpoints', () async {
      final storage = InMemoryAuthTokenStorage('token_present');
      final mockHttp = MockHttpClient((req) async {
        expect(req.headers.containsKey('authorization'), isFalse);
        return http.Response(
          jsonEncode({'status': 'ok'}),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final client = ApiClient(
        httpClient: mockHttp,
        tokenStorage: storage,
      );

      final res = await client.checkHealth();
      expect(res['status'], equals('ok'));
    });

    test('triggers session expiration on 401 response and throws ApiException', () async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);

      final mockHttp = MockHttpClient((req) async {
        return http.Response(
          jsonEncode({'detail': 'Could not validate credentials'}),
          401,
          headers: {'content-type': 'application/json'},
        );
      });

      final client = ApiClient(
        httpClient: mockHttp,
        authService: auth,
      );
      await auth.setSession(
        user: const User(id: 'u-1', email: 'test@lens.app', isActive: true),
        token: 'expired_token',
        backendAuthority: client.currentAuthority,
      );

      await expectLater(
        client.listCaptures(),
        throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'isUnauthorized', isTrue)),
      );

      // Verify token cleared and user logged out
      expect(auth.isAuthenticated, isFalse);
      expect(await storage.getToken(backendAuthority: client.currentAuthority), isNull);
    });

    test('login sends credentials without bearer and returns access_token', () async {
      final mockHttp = MockHttpClient((req) async {
        expect(req.url.path, endsWith('/auth/login'));
        expect(req.headers.containsKey('authorization'), isFalse);
        return http.Response(
          jsonEncode({
            'access_token': 'newly_issued_jwt_token',
            'token_type': 'bearer',
            'expires_in': 604800,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      });

      final client = ApiClient(httpClient: mockHttp);
      final token = await client.login(email: 'user@lens.app', password: 'Password123!');
      expect(token, equals('newly_issued_jwt_token'));
    });

    test('protected endpoints fail fast with 401 when token is missing without HTTP request', () async {
      final mockHttp = MockHttpClient((req) async {
        fail('No HTTP request should be sent when access token is missing');
      });

      final emptyStorage = InMemoryAuthTokenStorage();
      final client = ApiClient(httpClient: mockHttp, tokenStorage: emptyStorage);

      // listCaptures fails fast
      await expectLater(
        client.listCaptures(),
        throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'isUnauthorized', isTrue)),
      );

      // getCapture fails fast
      await expectLater(
        client.getCapture('cap-123'),
        throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'isUnauthorized', isTrue)),
      );

      // createCapture fails fast
      await expectLater(
        client.createCapture(CaptureCreate(sourceType: SourceType.url, originalUrl: 'https://example.com')),
        throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'isUnauthorized', isTrue)),
      );

      // search fails fast
      await expectLater(
        client.search(query: 'test query'),
        throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'isUnauthorized', isTrue)),
      );

      // Zero HTTP requests made
      expect(mockHttp.recordedRequests, isEmpty);
    });

    test('public endpoints execute without requiring token in storage', () async {
      final mockHttp = MockHttpClient((req) async {
        if (req.url.path.endsWith('/health')) {
          return http.Response(jsonEncode({'status': 'ok'}), 200, headers: {'content-type': 'application/json'});
        }
        if (req.url.path.endsWith('/auth/register')) {
          return http.Response(jsonEncode({'id': 'u-reg', 'email': 'new@lens.app', 'is_active': true}), 200, headers: {'content-type': 'application/json'});
        }
        return http.Response('{}', 404);
      });

      final emptyStorage = InMemoryAuthTokenStorage();
      final client = ApiClient(httpClient: mockHttp, tokenStorage: emptyStorage);

      final health = await client.checkHealth();
      expect(health['status'], equals('ok'));

      final registered = await client.register(email: 'new@lens.app', password: 'Password123!');
      expect(registered.email, equals('new@lens.app'));
    });
  });

  group('4. Login & Registration Screen UX', () {
    testWidgets('LoginScreen renders official LENS branding and validated fields', (tester) async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);
      final client = ApiClient(
        httpClient: MockHttpClient((_) async => http.Response('{}', 200)),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(
            apiClient: client,
            authService: auth,
            onNavigateToRegister: () {},
          ),
        ),
      );

      // Verify official branding
      expect(find.byType(LensLogo), findsOneWidget);
      expect(find.text('Sign In'), findsWidgets);
      expect(find.text('Email Address'), findsOneWidget);
      expect(find.text('Password'), findsOneWidget);

      // Test validation on empty submit
      await tester.tap(find.widgetWithText(FilledButton, 'Sign In'));
      await tester.pumpAndSettle();

      expect(find.text('Email is required'), findsOneWidget);
      expect(find.text('Password is required'), findsOneWidget);
    });

    testWidgets('RegisterScreen validates 8+ char password and confirmation match', (tester) async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);
      final client = ApiClient(
        httpClient: MockHttpClient((_) async => http.Response('{}', 200)),
      );

      await tester.pumpWidget(
        MaterialApp(
          home: RegisterScreen(
            apiClient: client,
            authService: auth,
            onNavigateToLogin: () {},
          ),
        ),
      );

      expect(find.byType(LensLogo), findsOneWidget);
      expect(find.text('Create Account'), findsWidgets);

      // Enter short password
      await tester.enterText(find.widgetWithText(TextFormField, 'Email Address'), 'new@lens.app');
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Password (min. 8 characters)'),
        'short',
      );
      await tester.enterText(find.widgetWithText(TextFormField, 'Confirm Password'), 'short');

      await tester.tap(find.widgetWithText(FilledButton, 'Create Account'));
      await tester.pumpAndSettle();

      expect(find.text('Password must be at least 8 characters long'), findsOneWidget);

      // Enter mismatched confirmation
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Password (min. 8 characters)'),
        'ValidPassword123!',
      );
      await tester.enterText(find.widgetWithText(TextFormField, 'Confirm Password'), 'Mismatch123!');

      await tester.tap(find.widgetWithText(FilledButton, 'Create Account'));
      await tester.pumpAndSettle();

      expect(find.text('Passwords do not match'), findsOneWidget);
    });

    testWidgets('Successful login sets session and transitions view', (tester) async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);

      final mockHttp = MockHttpClient((req) async {
        if (req.url.path.endsWith('/auth/login')) {
          return http.Response(
            jsonEncode({'access_token': 'test_token', 'token_type': 'bearer'}),
            200,
          );
        }
        if (req.url.path.endsWith('/auth/me')) {
          return http.Response(
            jsonEncode({'id': 'u-99', 'email': 'success@lens.app', 'is_active': true}),
            200,
          );
        }
        return http.Response('{}', 404);
      });

      final client = ApiClient(httpClient: mockHttp, authService: auth);
      bool loginSuccessCalled = false;

      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(
            apiClient: client,
            authService: auth,
            onNavigateToRegister: () {},
            onLoginSuccess: () {
              loginSuccessCalled = true;
            },
          ),
        ),
      );

      await tester.enterText(find.widgetWithText(TextFormField, 'Email Address'), 'success@lens.app');
      await tester.enterText(find.widgetWithText(TextFormField, 'Password'), 'Password123!');

      await tester.tap(find.widgetWithText(FilledButton, 'Sign In'));
      await tester.pumpAndSettle();

      expect(loginSuccessCalled, isTrue);
      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.email, equals('success@lens.app'));
    });
  });

  group('5. Android Share Sheet Continuation Across Auth', () {
    testWidgets('preserves incoming share while unauthenticated and pushes review after login',
        (tester) async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage); // unauthenticated

      final mockHttp = MockHttpClient((req) async {
        if (req.url.path.endsWith('/auth/login')) {
          return http.Response(
            jsonEncode({'access_token': 'post_share_token', 'token_type': 'bearer'}),
            200,
          );
        }
        if (req.url.path.endsWith('/auth/me')) {
          return http.Response(
            jsonEncode({'id': 'u-1', 'email': 'shared@lens.app', 'is_active': true}),
            200,
          );
        }
        if (req.url.path.endsWith('/captures')) {
          return http.Response(
            jsonEncode({'captures': [], 'total': 0, 'limit': 15, 'offset': 0}),
            200,
          );
        }
        return http.Response('{}', 200);
      });

      final client = ApiClient(httpClient: mockHttp, authService: auth);
      final fakeShare = FakeSharePlatform(
        initialShare: {
          'text': 'https://article-shared-before-login.com/post',
          'subject': 'Important Research',
        },
      );
      final shareService = IncomingShareService(platform: fakeShare);

      await tester.pumpWidget(
        LensApp(
          shareService: shareService,
          apiClient: client,
          authService: auth,
        ),
      );
      await tester.pumpAndSettle();

      // Since user is unauthenticated, app must show LoginScreen first, NOT review screen
      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.text('Review Shared Content'), findsNothing);

      // Now authenticate by submitting login
      await tester.enterText(find.widgetWithText(TextFormField, 'Email Address'), 'shared@lens.app');
      await tester.enterText(find.widgetWithText(TextFormField, 'Password'), 'Secret123!');

      await tester.tap(find.widgetWithText(FilledButton, 'Sign In'));
      await tester.pumpAndSettle();

      // ReviewSharedContent must now automatically pop up with the saved pending share!
      expect(find.text('Review Shared Content'), findsOneWidget);
      expect(find.text('https://article-shared-before-login.com/post'), findsOneWidget);
      expect(find.text('Important Research'), findsOneWidget);

      shareService.dispose();
      fakeShare.dispose();
    });
  });

  group('6. Startup Auth Gate & Session Recovery UI', () {
    testWidgets('renders splash scaffold while session restoration is in progress', (tester) async {
      final storage = InMemoryAuthTokenStorage('valid_token');
      final auth = AuthService(storage: storage);

      // Slow/pending profile fetch
      final completer = Completer<User>();
      unawaited(auth.restoreSession(() => completer.future));

      final client = ApiClient(
        httpClient: MockHttpClient((_) async => http.Response('{}', 200)),
        authService: auth,
      );

      await tester.pumpWidget(
        LensApp(
          apiClient: client,
          authService: auth,
        ),
      );
      await tester.pump();

      // Should display splash screen while restoring
      expect(find.byKey(const Key('auth_splash_scaffold')), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.byType(LoginScreen), findsNothing);

      // Complete restoration
      completer.complete(const User(id: 'u-done', email: 'done@lens.app', isActive: true));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('auth_splash_scaffold')), findsNothing);
      expect(find.byType(MainNavigationShell), findsOneWidget);
    });

    testWidgets('renders restoration failed screen on network error and allows retry', (tester) async {
      final storage = InMemoryAuthTokenStorage('valid_token');
      final auth = AuthService(storage: storage);

      // Fail with network error
      await auth.restoreSession(() async => throw ApiException.network());

      final client = ApiClient(
        httpClient: MockHttpClient((_) async => http.Response('{}', 200)),
        authService: auth,
      );

      await tester.pumpWidget(
        LensApp(
          apiClient: client,
          authService: auth,
        ),
      );
      await tester.pumpAndSettle();

      // Shows restoration failed screen
      expect(find.byKey(const Key('auth_restoration_failed_scaffold')), findsOneWidget);
      expect(find.text('Unable to restore session'), findsOneWidget);
      expect(find.byKey(const Key('retry_restore_button')), findsOneWidget);
      expect(find.byKey(const Key('switch_to_login_button')), findsOneWidget);

      // Test "Sign In with Another Account" button transitions to LoginScreen
      await tester.tap(find.byKey(const Key('switch_to_login_button')));
      await tester.pumpAndSettle();

      expect(find.byType(LoginScreen), findsOneWidget);
      expect(await storage.getToken(), isNull);
    });

    testWidgets('preserves incoming share while in restorationFailed state and resumes post-login',
        (tester) async {
      final storage = InMemoryAuthTokenStorage('expired_or_offline_token');
      final auth = AuthService(storage: storage);

      // Fail with network error
      await auth.restoreSession(() async => throw ApiException.network());

      final mockHttp = MockHttpClient((req) async {
        if (req.url.path.endsWith('/auth/login')) {
          return http.Response(
            jsonEncode({'access_token': 'new_login_token', 'token_type': 'bearer'}),
            200,
          );
        }
        if (req.url.path.endsWith('/auth/me')) {
          return http.Response(
            jsonEncode({'id': 'u-post-offline', 'email': 'offline@lens.app', 'is_active': true}),
            200,
          );
        }
        if (req.url.path.endsWith('/captures')) {
          return http.Response(
            jsonEncode({'captures': [], 'total': 0, 'limit': 15, 'offset': 0}),
            200,
          );
        }
        return http.Response('{}', 200);
      });

      final client = ApiClient(httpClient: mockHttp, authService: auth);
      final fakeShare = FakeSharePlatform(
        initialShare: {
          'text': 'https://example.com/share-during-offline',
          'subject': 'Preserved Note',
        },
      );
      final shareService = IncomingShareService(platform: fakeShare);

      await tester.pumpWidget(
        LensApp(
          shareService: shareService,
          apiClient: client,
          authService: auth,
        ),
      );
      await tester.pumpAndSettle();

      // Shows restoration failed screen
      expect(find.byKey(const Key('auth_restoration_failed_scaffold')), findsOneWidget);

      // User chooses to sign in
      await tester.tap(find.byKey(const Key('switch_to_login_button')));
      await tester.pumpAndSettle();

      // Shows LoginScreen
      expect(find.byType(LoginScreen), findsOneWidget);

      // Log in
      await tester.enterText(find.widgetWithText(TextFormField, 'Email Address'), 'offline@lens.app');
      await tester.enterText(find.widgetWithText(TextFormField, 'Password'), 'Password123!');
      await tester.tap(find.widgetWithText(FilledButton, 'Sign In'));
      await tester.pumpAndSettle();

      // The share arrived during restoration failure must now be safely presented!
      expect(find.text('Review Shared Content'), findsOneWidget);
      expect(find.text('https://example.com/share-during-offline'), findsOneWidget);

      shareService.dispose();
      fakeShare.dispose();
    });
  });

  group('7. Hardening Regression Tests (Stage 19.3.1)', () {
    test('AuthStorageException on read sets restorationFailed and preserves session state', () async {
      final storage = FailingAuthTokenStorage()..failOnGet = true;
      final auth = AuthService(storage: storage);

      await auth.restoreSession(() async => const User(id: 'u-1', email: 'test@lens.app', isActive: true));

      expect(auth.status, equals(AuthStatus.restorationFailed));
      expect(auth.isAuthenticated, isFalse);
    });

    test('AuthStorageException on clear during logout propagates and preserves session', () async {
      final storage = FailingAuthTokenStorage()..failOnClear = true;
      final auth = AuthService(storage: storage);
      await auth.setSession(
        user: const User(id: 'u-1', email: 'test@lens.app', isActive: true),
        token: 'token123',
      );

      expect(() => auth.logout(), throwsA(isA<AuthStorageException>()));
      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.email, equals('test@lens.app'));
    });

    test('slow session restoration does not overwrite newer login', () async {
      final storage = InMemoryAuthTokenStorage('old_token');
      final auth = AuthService(storage: storage);

      final completer = Completer<User>();
      final restoreFuture = auth.restoreSession(() => completer.future);

      // User performs a new login while restoration is still in-flight
      const newUser = User(id: 'u-new', email: 'new@lens.app', isActive: true);
      await auth.setSession(user: newUser, token: 'new_token');

      // Now the old restoreSession completes with an older user
      completer.complete(const User(id: 'u-old', email: 'old@lens.app', isActive: true));
      await restoreFuture;

      // Newer session MUST be preserved!
      expect(auth.currentUser?.email, equals('new@lens.app'));
      expect(auth.isAuthenticated, isTrue);
    });

    test('stale 401 response from older session does not clear replacement session', () async {
      final storage = InMemoryAuthTokenStorage('token_a');
      final auth = AuthService(storage: storage);

      await auth.setSession(
        user: const User(id: 'u-a', email: 'user-a@lens.app', isActive: true),
        token: 'token_a',
      );
      final sessionAId = auth.sessionId;

      // User logs into Session B
      await auth.setSession(
        user: const User(id: 'u-b', email: 'user-b@lens.app', isActive: true),
        token: 'token_b',
      );

      // An in-flight request from Session A finally returns 401
      await auth.handleSessionExpired(sessionAId);

      // Session B must NOT be expired or cleared!
      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.email, equals('user-b@lens.app'));
      expect(await storage.getToken(), equals('token_b'));
    });

    test('ApiClient rejects plain HTTP for remote sensitive endpoints and accepts HTTPS or loopback', () async {
      final storage = InMemoryAuthTokenStorage();
      await storage.saveToken('token123', backendAuthority: 'remote.lens.app');
      await storage.saveToken('token123', backendAuthority: '127.0.0.1:8000');
      final mockHttp = MockHttpClient((req) async => http.Response('{"captures": [], "total": 0, "limit": 15, "offset": 0}', 200));

      // 1. Insecure remote HTTP -> Rejected
      final insecureClient = ApiClient(
        baseUrlOverride: 'http://remote.lens.app',
        httpClient: mockHttp,
        tokenStorage: storage,
      );

      expect(
        () => insecureClient.listCaptures(),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 400)),
      );

      expect(
        () => insecureClient.login(email: 'a@b.com', password: '123'),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 400)),
      );

      // 2. Secure HTTPS -> Allowed
      final secureClient = ApiClient(
        baseUrlOverride: 'https://remote.lens.app',
        httpClient: mockHttp,
        tokenStorage: storage,
      );

      final secureRes = await secureClient.listCaptures();
      expect(secureRes, isNotNull);

      // 3. Local loopback HTTP -> Allowed
      final loopbackClient = ApiClient(
        baseUrlOverride: 'http://127.0.0.1:8000',
        httpClient: mockHttp,
        tokenStorage: storage,
      );

      final loopbackRes = await loopbackClient.listCaptures();
      expect(loopbackRes, isNotNull);
    });

    test('tokens are isolated by backend authority preventing cross-backend token reuse', () async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);

      // Login to backend Alpha
      await auth.setSession(
        user: const User(id: 'u-1', email: 'user@alpha.app', isActive: true),
        token: 'token_alpha_secret',
        backendAuthority: 'alpha.lens.app',
      );

      String? recordedAuthHeader;
      final mockHttp = MockHttpClient((req) async {
        recordedAuthHeader = req.headers['authorization'];
        return http.Response('{"captures": [], "total": 0, "limit": 15, "offset": 0}', 200);
      });

      // Client connected to backend Alpha gets alpha token
      final clientAlpha = ApiClient(
        baseUrlOverride: 'https://alpha.lens.app',
        httpClient: mockHttp,
        authService: auth,
      );
      await clientAlpha.listCaptures();
      expect(recordedAuthHeader, equals('Bearer token_alpha_secret'));

      // Client connected to backend Beta MUST NOT get alpha token
      final clientBeta = ApiClient(
        baseUrlOverride: 'https://beta.lens.app',
        httpClient: mockHttp,
        authService: auth,
      );

      expect(
        () => clientBeta.listCaptures(),
        throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 401)),
      );
    });

    testWidgets('LoginScreen ignores repeated submit taps while request is in-flight', (tester) async {
      int loginCallCount = 0;
      final completer = Completer<String>();
      final mockHttp = MockHttpClient((req) async {
        if (req.url.path.endsWith('/auth/login')) {
          loginCallCount++;
          final token = await completer.future;
          return http.Response(jsonEncode({'access_token': token}), 200);
        }
        return http.Response(jsonEncode({'id': 'u-1', 'email': 'dup@lens.app', 'is_active': true}), 200);
      });

      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);
      final client = ApiClient(httpClient: mockHttp, authService: auth);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: LoginScreen(
              apiClient: client,
              authService: auth,
              onNavigateToRegister: () {},
            ),
          ),
        ),
      );

      await tester.enterText(find.widgetWithText(TextFormField, 'Email Address'), 'dup@lens.app');
      await tester.enterText(find.widgetWithText(TextFormField, 'Password'), 'Password123!');

      // Tap submit 3 times rapidly
      await tester.tap(find.byType(FilledButton));
      await tester.pump();
      await tester.tap(find.byType(FilledButton));
      await tester.pump();
      await tester.tap(find.byType(FilledButton));
      await tester.pump();

      expect(loginCallCount, equals(1));

      completer.complete('token_dup');
      await tester.pumpAndSettle();
    });

    testWidgets('RegisterScreen displays clear notice when auto-login fails after account creation', (tester) async {
      final mockHttp = MockHttpClient((req) async {
        if (req.url.path.endsWith('/auth/register')) {
          return http.Response(jsonEncode({'id': 'u-reg', 'email': 'new@lens.app', 'is_active': true}), 201);
        }
        if (req.url.path.endsWith('/auth/login')) {
          return http.Response(jsonEncode({'detail': 'Temporary login service failure'}), 500);
        }
        return http.Response('{}', 200);
      });

      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);
      final client = ApiClient(httpClient: mockHttp, authService: auth);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: RegisterScreen(
              apiClient: client,
              authService: auth,
              onNavigateToLogin: () {},
            ),
          ),
        ),
      );

      await tester.enterText(find.widgetWithText(TextFormField, 'Email Address'), 'new@lens.app');
      await tester.enterText(find.widgetWithText(TextFormField, 'Password (min. 8 characters)'), 'Password123!');
      await tester.enterText(find.widgetWithText(TextFormField, 'Confirm Password'), 'Password123!');

      await tester.tap(find.widgetWithText(FilledButton, 'Create Account'));
      await tester.pumpAndSettle();

      expect(find.textContaining('Account created successfully, but automatic sign-in failed'), findsOneWidget);
    });

    test('authority-scoped token reads never fall back to global token when authority is supplied', () async {
      final storage = InMemoryAuthTokenStorage();

      // Save a global token without authority
      await storage.saveToken('global_token_xyz');
      expect(await storage.getToken(), equals('global_token_xyz'));

      // Explicit authority read MUST NOT fall back to global token
      expect(await storage.getToken(backendAuthority: 'api.lens.app'), isNull);
      expect(await storage.hasToken(backendAuthority: 'api.lens.app'), isFalse);

      // Explicit authority read for localhost MUST NOT fall back
      expect(await storage.getToken(backendAuthority: '127.0.0.1:8000'), isNull);
      expect(await storage.hasToken(backendAuthority: '127.0.0.1:8000'), isFalse);
    });

    test('authority-specific token clearing does not wipe global or other authority tokens', () async {
      final storage = InMemoryAuthTokenStorage();

      await storage.saveToken('global_token');
      await storage.saveToken('token_alpha', backendAuthority: 'alpha.lens.app');
      await storage.saveToken('token_beta', backendAuthority: 'beta.lens.app');

      // Clear only alpha authority
      await storage.clearToken(backendAuthority: 'alpha.lens.app');

      expect(await storage.getToken(backendAuthority: 'alpha.lens.app'), isNull);
      expect(await storage.getToken(backendAuthority: 'beta.lens.app'), equals('token_beta'));
      expect(await storage.getToken(), equals('global_token'));

      // Clear global token
      await storage.clearToken();
      expect(await storage.getToken(), isNull);
      expect(await storage.getToken(backendAuthority: 'beta.lens.app'), equals('token_beta'));
    });

    test('SecureAuthTokenStorage authority-scoped token reads and clear isolate authority from global token', () async {
      final fakeBackend = FakeFlutterSecureStorage();
      final storage = SecureAuthTokenStorage(storage: fakeBackend);

      // Save a global token without authority
      await storage.saveToken('secure_global_token');
      expect(await storage.getToken(), equals('secure_global_token'));

      // Explicit authority read MUST NOT fall back to global token
      expect(await storage.getToken(backendAuthority: 'api.lens.app'), isNull);
      expect(await storage.hasToken(backendAuthority: 'api.lens.app'), isFalse);

      // Save authority-specific tokens
      await storage.saveToken('secure_alpha_token', backendAuthority: 'alpha.lens.app');
      await storage.saveToken('secure_beta_token', backendAuthority: 'beta.lens.app');

      // Clear only alpha authority
      await storage.clearToken(backendAuthority: 'alpha.lens.app');
      expect(await storage.getToken(backendAuthority: 'alpha.lens.app'), isNull);
      expect(await storage.getToken(backendAuthority: 'beta.lens.app'), equals('secure_beta_token'));
      expect(await storage.getToken(), equals('secure_global_token'));

      // Clear global token
      await storage.clearToken();
      expect(await storage.getToken(), isNull);
      expect(await storage.getToken(backendAuthority: 'beta.lens.app'), equals('secure_beta_token'));
    });

    test('authority key formatting is collision-resistant and handles distinct delimiters and ports', () async {
      final storage = InMemoryAuthTokenStorage();

      // Delimiter collision test: 'api:8000' vs 'api_8000' vs 'api/8000'
      final keyColon = InMemoryAuthTokenStorage.formatKey('api:8000');
      final keyUnderscore = InMemoryAuthTokenStorage.formatKey('api_8000');
      final keySlash = InMemoryAuthTokenStorage.formatKey('api/8000');

      expect(keyColon, isNot(equals(keyUnderscore)));
      expect(keyColon, isNot(equals(keySlash)));
      expect(keyUnderscore, isNot(equals(keySlash)));

      // Secure storage formatKey must also be collision-resistant
      expect(
        SecureAuthTokenStorage.formatKey('api:8000'),
        isNot(equals(SecureAuthTokenStorage.formatKey('api_8000'))),
      );

      // Verify independent token storage without overwrite
      await storage.saveToken('token_colon', backendAuthority: 'api:8000');
      await storage.saveToken('token_underscore', backendAuthority: 'api_8000');

      expect(await storage.getToken(backendAuthority: 'api:8000'), equals('token_colon'));
      expect(await storage.getToken(backendAuthority: 'api_8000'), equals('token_underscore'));

      await storage.clearToken(backendAuthority: 'api:8000');
      expect(await storage.getToken(backendAuthority: 'api:8000'), isNull);
      expect(await storage.getToken(backendAuthority: 'api_8000'), equals('token_underscore'));
    });

    test('session restoration does not leave isRestoring or isLoading stuck when login supersedes in-flight restoration', () async {
      final storage = InMemoryAuthTokenStorage();
      await storage.saveToken('initial_token');
      final auth = AuthService(storage: storage);

      final completer = Completer<User>();
      final restoreFuture = auth.restoreSession(() => completer.future);

      // Verify restoration is actively in-flight
      expect(auth.isRestoring, isTrue);
      expect(auth.isLoading, isTrue);
      expect(auth.status, equals(AuthStatus.restoring));

      // User initiates login while restoration is still in-flight
      await auth.setSession(
        user: const User(id: 'u-login', email: 'login@lens.app', isActive: true),
        token: 'token_login_new',
      );

      // Now complete the delayed background restoration
      completer.complete(const User(id: 'u-old', email: 'old@lens.app', isActive: true));
      await restoreFuture;

      // isRestoring and isLoading must NOT be stuck as true
      expect(auth.isRestoring, isFalse);
      expect(auth.isLoading, isFalse);
      expect(auth.status, equals(AuthStatus.authenticated));
      expect(auth.currentUser?.email, equals('login@lens.app'));

      // Subsequent session restoration must NOT be blocked by a stuck isRestoring flag
      bool secondRan = false;
      await auth.restoreSession(() async {
        secondRan = true;
        return const User(id: 'u-subsequent', email: 'sub@lens.app', isActive: true);
      });
      expect(secondRan, isTrue);
      expect(auth.isRestoring, isFalse);
      expect(auth.isLoading, isFalse);
    });

    test('session restoration does not leave isRestoring or isLoading stuck when logout supersedes in-flight restoration', () async {
      final storage = InMemoryAuthTokenStorage();
      await storage.saveToken('initial_token');
      final auth = AuthService(storage: storage);

      final completer = Completer<User>();
      final restoreFuture = auth.restoreSession(() => completer.future);

      expect(auth.isRestoring, isTrue);
      expect(auth.isLoading, isTrue);

      // Logout during in-flight restoration
      await auth.logout();

      completer.complete(const User(id: 'u-old', email: 'old@lens.app', isActive: true));
      await restoreFuture;

      expect(auth.isRestoring, isFalse);
      expect(auth.isLoading, isFalse);
      expect(auth.status, equals(AuthStatus.unauthenticated));
    });

    test('restoreSession sets restorationFailed and records storageCleanupError when token clearance fails on 401', () async {
      final storage = FailingAuthTokenStorage()
        ..token = 'invalid_jwt_token'
        ..failOnClear = true;
      final auth = AuthService(storage: storage);

      await auth.restoreSession(() async {
        throw const ApiException(
          statusCode: 401,
          message: 'Invalid credentials or token expired',
        );
      });

      // MUST NOT report unauthenticated when token remains persisted in storage
      expect(auth.status, equals(AuthStatus.restorationFailed));
      expect(auth.isAuthenticated, isFalse);
      expect(auth.currentUser, isNull);
      expect(auth.hasStorageCleanupError, isTrue);
      expect(auth.storageCleanupError, isNotNull);
      expect(auth.storageCleanupError.toString(), contains('Simulated keystore clear failure'));

      // Token is still in storage
      expect(storage.token, equals('invalid_jwt_token'));

      // Retry cleanup after keystore becomes healthy
      storage.failOnClear = false;
      await auth.retryStorageCleanup();
      expect(auth.hasStorageCleanupError, isFalse);
      expect(auth.storageCleanupError, isNull);
      expect(storage.token, isNull);
    });

    test('handleSessionExpired represents storage clearance failure while transitioning to unauthenticated', () async {
      final storage = FailingAuthTokenStorage()
        ..token = 'active_jwt_token'
        ..failOnClear = true;
      final auth = AuthService(storage: storage);

      // Initialize authenticated session
      await auth.setSession(
        user: const User(id: 'u-1', email: 'user@lens.app', isActive: true),
        token: 'active_jwt_token',
      );
      expect(auth.isAuthenticated, isTrue);

      // Trigger 401 session expiry while storage clearance fails
      await auth.handleSessionExpired();

      // UI safely transitions to unauthenticated so expired session cannot be used
      expect(auth.status, equals(AuthStatus.unauthenticated));
      expect(auth.isAuthenticated, isFalse);
      expect(auth.currentUser, isNull);

      // Persistence failure is explicitly exposed rather than falsely claiming credentials were removed
      expect(auth.hasStorageCleanupError, isTrue);
      expect(auth.storageCleanupError, isNotNull);
      expect(auth.storageCleanupError.toString(), contains('Simulated keystore clear failure'));

      // Direct propagation when requested
      expect(
        () => auth.handleSessionExpired(null, null, true),
        throwsA(isA<AuthStorageException>()),
      );

      // Retry cleanup after keystore recovers
      storage.failOnClear = false;
      await auth.retryStorageCleanup();
      expect(auth.hasStorageCleanupError, isFalse);
      expect(auth.storageCleanupError, isNull);
      expect(storage.token, isNull);
    });

    test('stale handleSessionExpired or restoreSession cannot invalidate newer active login session', () async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);

      // Session 1 is active
      await auth.setSession(
        user: const User(id: 'u-1', email: 'session1@lens.app', isActive: true),
        token: 'token_session_1',
      );
      final int session1Id = auth.sessionId;

      // Newer login establishes Session 2
      await auth.setSession(
        user: const User(id: 'u-2', email: 'session2@lens.app', isActive: true),
        token: 'token_session_2',
      );
      expect(auth.sessionId, isNot(equals(session1Id)));

      // Stale 401 arriving from Session 1 request must be discarded
      await auth.handleSessionExpired(session1Id);

      // Session 2 MUST remain active, authenticated, and intact
      expect(auth.status, equals(AuthStatus.authenticated));
      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.email, equals('session2@lens.app'));
      expect(auth.hasStorageCleanupError, isFalse);
    });

    test('handleSessionExpired with no explicit authority uses active authority and never wipes global token', () async {
      final storage = InMemoryAuthTokenStorage();
      await storage.saveToken('global_safe_token');

      final auth = AuthService(storage: storage);
      await auth.setSession(
        user: const User(id: 'u-auth-a', email: 'user@authority-a.lens', isActive: true),
        token: 'token_authority_a',
        backendAuthority: 'authority-a.lens.internal',
      );

      // Trigger session expiry without specifying an authority argument
      await auth.handleSessionExpired();

      expect(auth.status, equals(AuthStatus.unauthenticated));
      expect(auth.isAuthenticated, isFalse);

      // Scoped token for Authority A MUST be cleared
      expect(await storage.getToken(backendAuthority: 'authority-a.lens.internal'), isNull);

      // Global token MUST remain intact and untouched
      expect(await storage.getToken(), equals('global_safe_token'));
    });

    test('stale 401 from Authority A after logging into Authority B does not expire Authority B session or clear tokens', () async {
      final storage = InMemoryAuthTokenStorage();
      final auth = AuthService(storage: storage);

      // Log into Authority A
      await auth.setSession(
        user: const User(id: 'u-a', email: 'user@auth-a.lens', isActive: true),
        token: 'token_a',
        backendAuthority: 'auth-a.lens.internal',
      );
      final int sessionAId = auth.sessionId;

      // In-flight request to Authority A starts...
      // User then logs into Authority B
      await auth.setSession(
        user: const User(id: 'u-b', email: 'user@auth-b.lens', isActive: true),
        token: 'token_b',
        backendAuthority: 'auth-b.lens.internal',
      );
      expect(auth.sessionId, isNot(equals(sessionAId)));

      // Stale 401 arrives from Authority A with sessionAId
      await auth.handleSessionExpired(sessionAId, 'auth-a.lens.internal');

      // Session B MUST remain authenticated and untouched
      expect(auth.status, equals(AuthStatus.authenticated));
      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.email, equals('user@auth-b.lens'));
      expect(auth.activeBackendAuthority, equals('auth-b.lens.internal'));
      expect(await storage.getToken(backendAuthority: 'auth-b.lens.internal'), equals('token_b'));
    });

    test('clearSessionAndLogin cleanup failure preserves error, blocks authenticated API, supports retry, and subsequent login cannot inherit old token', () async {
      final storage = FailingAuthTokenStorage()
        ..failOnClear = true;
      final auth = AuthService(storage: storage);

      await auth.setSession(
        user: const User(id: 'u-1', email: 'user1@lens.app', isActive: true),
        token: 'persisted_token_1',
        backendAuthority: 'api.lens.app',
      );

      // Attempt clearSessionAndLogin while secure storage clear fails
      await expectLater(
        auth.clearSessionAndLogin(),
        throwsA(isA<AuthStorageException>()),
      );

      // UI state transitions safely to unauthenticated
      expect(auth.status, equals(AuthStatus.unauthenticated));
      expect(auth.isAuthenticated, isFalse);
      expect(auth.currentUser, isNull);

      // Cleanup failure is preserved and exposed
      expect(auth.hasStorageCleanupError, isTrue);
      expect(auth.storageCleanupError, isNotNull);
      expect(auth.failedCleanupAuthority, equals('api.lens.app'));

      // Application is kept safe from authenticated API use
      final apiClient = ApiClient(
        baseUrlOverride: 'https://api.lens.app',
        authService: auth,
      );
      await expectLater(
        apiClient.listCaptures(),
        throwsA(predicate((e) => e is ApiException && e.isUnauthorized)),
      );

      // Deterministic retry path
      storage.failOnClear = false;
      await auth.retryStorageCleanup();
      expect(auth.hasStorageCleanupError, isFalse);
      expect(auth.storageCleanupError, isNull);
      expect(auth.failedCleanupAuthority, isNull);
      expect(await storage.getToken(backendAuthority: 'api.lens.app'), isNull);

      // Subsequent login establishes clean session and cannot inherit old credentials
      await auth.setSession(
        user: const User(id: 'u-2', email: 'user2@lens.app', isActive: true),
        token: 'fresh_token_2',
        backendAuthority: 'api.lens.app',
      );
      expect(auth.status, equals(AuthStatus.authenticated));
      expect(auth.isAuthenticated, isTrue);
      expect(auth.currentUser?.email, equals('user2@lens.app'));
      expect(await storage.getToken(backendAuthority: 'api.lens.app'), equals('fresh_token_2'));
    });
  });
}

class FakeFlutterSecureStorage extends Fake implements FlutterSecureStorage {
  final Map<String, String> _map = {};

  @override
  Future<void> write({
    required String key,
    required String? value,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (value == null) {
      _map.remove(key);
    } else {
      _map[key] = value;
    }
  }

  @override
  Future<String?> read({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    return _map[key];
  }

  @override
  Future<void> delete({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    _map.remove(key);
  }

  @override
  Future<bool> containsKey({
    required String key,
    AppleOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    AppleOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    return _map.containsKey(key);
  }
}

class FailingAuthTokenStorage implements AuthTokenStorage {
  bool failOnSave = false;
  bool failOnGet = false;
  bool failOnClear = false;
  String? token;
  final Map<String, String> tokens = {};

  @override
  Future<void> saveToken(String token, {String? backendAuthority}) async {
    if (failOnSave) {
      throw const AuthStorageException('Simulated keystore save failure');
    }
    this.token = token;
    final key = InMemoryAuthTokenStorage.formatKey(backendAuthority);
    tokens[key] = token;
  }

  @override
  Future<String?> getToken({String? backendAuthority}) async {
    if (failOnGet) {
      throw const AuthStorageException('Simulated keystore read failure');
    }
    if (backendAuthority != null && backendAuthority.isNotEmpty) {
      final key = InMemoryAuthTokenStorage.formatKey(backendAuthority);
      return tokens[key];
    }
    return token ?? tokens[InMemoryAuthTokenStorage.formatKey(null)];
  }

  @override
  Future<void> clearToken({String? backendAuthority}) async {
    if (failOnClear) {
      throw const AuthStorageException('Simulated keystore clear failure');
    }
    token = null;
    if (backendAuthority != null && backendAuthority.isNotEmpty) {
      final key = InMemoryAuthTokenStorage.formatKey(backendAuthority);
      tokens.remove(key);
    } else {
      tokens.clear();
    }
  }

  @override
  Future<bool> hasToken({String? backendAuthority}) async {
    final t = await getToken(backendAuthority: backendAuthority);
    return t != null && t.isNotEmpty;
  }
}
