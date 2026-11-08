import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
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
      final storage = InMemoryAuthTokenStorage('bearer_token_xyz');
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
      final storage = InMemoryAuthTokenStorage('expired_token');
      final auth = AuthService(storage: storage);
      await auth.setSession(
        user: const User(id: 'u-1', email: 'test@lens.app', isActive: true),
        token: 'expired_token',
      );

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

      await expectLater(
        client.listCaptures(),
        throwsA(isA<ApiException>().having((e) => e.isUnauthorized, 'isUnauthorized', isTrue)),
      );

      // Verify token cleared and user logged out
      expect(auth.isAuthenticated, isFalse);
      expect(await storage.getToken(), isNull);
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
}
