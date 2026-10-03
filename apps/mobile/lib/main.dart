import 'package:flutter/material.dart';
import 'core/config/api_config.dart';
import 'core/theme/app_theme.dart';
import 'screens/captures_screen.dart';
import 'screens/new_capture_screen.dart';
import 'screens/search_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final config = ApiConfig();
  await config.init();
  runApp(const LensApp());
}

/// Root application widget for LENS Mobile.
class LensApp extends StatelessWidget {
  const LensApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
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
