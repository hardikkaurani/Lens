import 'dart:async';
import 'package:flutter/material.dart';
import 'core/auth/auth_service.dart';
import 'core/config/api_config.dart';
import 'core/network/api_client.dart';
import 'core/share/incoming_share_service.dart';
import 'core/share/shared_content.dart';
import 'core/theme/app_theme.dart';
import 'screens/captures_screen.dart';
import 'screens/login_screen.dart';
import 'screens/new_capture_screen.dart';
import 'screens/register_screen.dart';
import 'screens/search_screen.dart';
import 'screens/share_review_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final config = ApiConfig();
  await config.init();

  final authService = AuthService();
  final apiClient = ApiClient(config: config, authService: authService);

  // Restore previous session from secure storage in background
  unawaited(authService.restoreSession(() => apiClient.getMe()));

  runApp(LensApp(
    apiClient: apiClient,
    authService: authService,
  ));
}

/// Root application widget for LENS Mobile with incoming share handling and authentication gate.
class LensApp extends StatefulWidget {
  final IncomingShareService? shareService;
  final ApiClient? apiClient;
  final AuthService? authService;

  const LensApp({
    super.key,
    this.shareService,
    this.apiClient,
    this.authService,
  });

  @override
  State<LensApp> createState() => _LensAppState();
}

class _LensAppState extends State<LensApp> {
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();
  late final IncomingShareService _shareService;
  late final ApiClient _apiClient;
  StreamSubscription<SharedContent>? _shareSub;
  bool _isReviewOpen = false;
  int _currentReviewId = 0;
  SharedContent? _pendingShare;
  bool _showRegister = false;

  @override
  void initState() {
    super.initState();
    _shareService = widget.shareService ?? IncomingShareService();
    _apiClient = widget.apiClient ?? ApiClient(authService: widget.authService);

    if (widget.authService != null) {
      widget.authService!.addListener(_handleAuthStateChanged);
    }

    // Listen for warm-start incoming shares
    _shareSub = _shareService.onIncomingShare.listen(_navigateToReview);

    // Process cold-start incoming share after the initial frame
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      final initial = await _shareService.getInitialShare();
      if (initial != null && mounted) {
        _navigateToReview(initial);
      }
    });
  }

  void _handleAuthStateChanged() {
    if (!mounted) return;
    if (widget.authService != null && widget.authService!.isAuthenticated) {
      if (_pendingShare != null) {
        final share = _pendingShare!;
        _pendingShare = null;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) {
            _openReviewScreen(share);
          }
        });
      }
    }
  }

  void _navigateToReview(SharedContent content) {
    if (!mounted) return;

    // If authService is present and user is unauthenticated, preserve share for post-login continuation
    if (widget.authService != null && !widget.authService!.isAuthenticated) {
      _pendingShare = content;
      return;
    }

    _openReviewScreen(content);
  }

  void _openReviewScreen(SharedContent content) {
    if (!mounted) return;

    if (_isReviewOpen) {
      _navigatorKey.currentState?.pop();
    }

    _isReviewOpen = true;
    final int reviewId = ++_currentReviewId;
    _navigatorKey.currentState
        ?.push(
      MaterialPageRoute(
        builder: (ctx) => ShareReviewScreen(
          sharedContent: content,
          apiClient: _apiClient,
          onCancel: () {
            if (_currentReviewId == reviewId) {
              _isReviewOpen = false;
            }
          },
          onSaved: (created) {
            if (_currentReviewId == reviewId) {
              _isReviewOpen = false;
            }
          },
        ),
      ),
    )
        .then((_) {
      if (_currentReviewId == reviewId) {
        _isReviewOpen = false;
      }
    });
  }

  @override
  void dispose() {
    if (widget.authService != null) {
      widget.authService!.removeListener(_handleAuthStateChanged);
    }
    _shareSub?.cancel();
    if (widget.shareService == null) {
      _shareService.dispose();
    }
    if (widget.apiClient == null) {
      _apiClient.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: _navigatorKey,
      title: 'LENS',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      home: _buildHome(),
    );
  }

  Widget _buildHome() {
    if (widget.authService == null) {
      return MainNavigationShell(
        apiClient: _apiClient,
        authService: widget.authService,
      );
    }

    return ListenableBuilder(
      listenable: widget.authService!,
      builder: (context, _) {
        if (!widget.authService!.isAuthenticated) {
          if (_showRegister) {
            return RegisterScreen(
              apiClient: _apiClient,
              authService: widget.authService!,
              onNavigateToLogin: () {
                setState(() => _showRegister = false);
              },
              onRegisterSuccess: () {
                setState(() => _showRegister = false);
              },
            );
          }
          return LoginScreen(
            apiClient: _apiClient,
            authService: widget.authService!,
            onNavigateToRegister: () {
              setState(() => _showRegister = true);
            },
          );
        }

        return MainNavigationShell(
          apiClient: _apiClient,
          authService: widget.authService,
        );
      },
    );
  }
}

/// Primary navigation shell with 3 tabs: Captures, Search, New Capture.
class MainNavigationShell extends StatefulWidget {
  final ApiClient? apiClient;
  final AuthService? authService;

  const MainNavigationShell({
    super.key,
    this.apiClient,
    this.authService,
  });

  @override
  State<MainNavigationShell> createState() => _MainNavigationShellState();
}

class _MainNavigationShellState extends State<MainNavigationShell> {
  int _currentIndex = 0;

  void _onTabSelected(int index) {
    setState(() => _currentIndex = index);
  }

  @override
  Widget build(BuildContext context) {
    final screens = [
      CapturesScreen(
        apiClient: widget.apiClient,
        authService: widget.authService,
      ),
      SearchScreen(
        apiClient: widget.apiClient,
      ),
      NewCaptureScreen(
        apiClient: widget.apiClient,
        onCaptureCreated: () {
          // Switch back to captures tab after creation
          setState(() => _currentIndex = 0);
        },
      ),
    ];

    return Scaffold(
      body: IndexedStack(
        index: _currentIndex,
        children: screens,
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _currentIndex,
        onDestinationSelected: _onTabSelected,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.inbox_outlined),
            selectedIcon: Icon(Icons.inbox_rounded),
            label: 'Captures',
          ),
          NavigationDestination(
            icon: Icon(Icons.search_rounded),
            selectedIcon: Icon(Icons.manage_search_rounded),
            label: 'Search',
          ),
          NavigationDestination(
            icon: Icon(Icons.add_circle_outline_rounded),
            selectedIcon: Icon(Icons.add_circle_rounded),
            label: 'New',
          ),
        ],
      ),
    );
  }
}
