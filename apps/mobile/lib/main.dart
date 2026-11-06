import 'dart:async';
import 'package:flutter/material.dart';
import 'core/config/api_config.dart';
import 'core/network/api_client.dart';
import 'core/share/incoming_share_service.dart';
import 'core/share/shared_content.dart';
import 'core/theme/app_theme.dart';
import 'screens/captures_screen.dart';
import 'screens/new_capture_screen.dart';
import 'screens/search_screen.dart';
import 'screens/share_review_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final config = ApiConfig();
  await config.init();
  runApp(const LensApp());
}

/// Root application widget for LENS Mobile with incoming share handling.
class LensApp extends StatefulWidget {
  final IncomingShareService? shareService;
  final ApiClient? apiClient;

  const LensApp({
    super.key,
    this.shareService,
    this.apiClient,
  });

  @override
  State<LensApp> createState() => _LensAppState();
}

class _LensAppState extends State<LensApp> {
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();
  late final IncomingShareService _shareService;
  StreamSubscription<SharedContent>? _shareSub;
  bool _isReviewOpen = false;
  int _currentReviewId = 0;

  @override
  void initState() {
    super.initState();
    _shareService = widget.shareService ?? IncomingShareService();

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

  void _navigateToReview(SharedContent content) {
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
          apiClient: widget.apiClient,
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
    _shareSub?.cancel();
    if (widget.shareService == null) {
      _shareService.dispose();
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
      home: const MainNavigationShell(),
    );
  }
}

/// Primary navigation shell with 3 tabs: Captures, Search, New Capture.
class MainNavigationShell extends StatefulWidget {
  const MainNavigationShell({super.key});

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
      const CapturesScreen(),
      const SearchScreen(),
      NewCaptureScreen(
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
