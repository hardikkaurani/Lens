import 'package:flutter/material.dart';
import '../core/network/api_client.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../core/utils/security_utils.dart';
import '../models/capture.dart';
import '../widgets/error_view.dart';
import '../widgets/loading_view.dart';
import '../widgets/server_config_dialog.dart';
import '../widgets/source_badge.dart';
import '../widgets/status_badge.dart';
import 'capture_detail_screen.dart';

/// Main screen displaying the paginated list of captured information.
class CapturesScreen extends StatefulWidget {
  final ApiClient? apiClient;

  const CapturesScreen({super.key, this.apiClient});

  @override
  State<CapturesScreen> createState() => _CapturesScreenState();
}

class _CapturesScreenState extends State<CapturesScreen> {
  late final ApiClient _client;
  final ScrollController _scrollController = ScrollController();

  List<Capture> _captures = [];
  bool _isLoading = true;
  bool _isLoadingMore = false;
  String? _errorMessage;
  int _total = 0;
  int _offset = 0;
  int _activeRequestId = 0;
  static const int _limit = 15;

  @override
  void initState() {
    super.initState();
    _client = widget.apiClient ?? ApiClient();
    _loadInitial();
    _scrollController.addListener(_onScroll);
  }

  @override
  void dispose() {
    _scrollController.dispose();
    if (widget.apiClient == null) {
      _client.dispose();
    }
    super.dispose();
  }

  void _onScroll() {
    if (_scrollController.position.pixels >=
            _scrollController.position.maxScrollExtent - 200 &&
        !_isLoading &&
        !_isLoadingMore &&
        _captures.length < _total) {
      _loadMore();
    }
  }

  Future<void> _loadInitial() async {
    final requestId = ++_activeRequestId;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _offset = 0;
    });

    try {
      final res = await _client.listCaptures(limit: _limit, offset: 0);
      if (mounted && requestId == _activeRequestId) {
        setState(() {
          _captures = res.items;
          _total = res.total;
          _offset = res.items.length;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (mounted && requestId == _activeRequestId) {
        setState(() {
          _errorMessage = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  Future<void> _loadMore() async {
    if (_isLoading || _isLoadingMore || _captures.length >= _total) return;

    final requestId = _activeRequestId;
    setState(() => _isLoadingMore = true);

    try {
      final res = await _client.listCaptures(limit: _limit, offset: _offset);
      if (mounted && requestId == _activeRequestId) {
        setState(() {
          final existingIds = _captures.map((c) => c.id).toSet();
          final newItems = res.items.where((c) => !existingIds.contains(c.id)).toList();
          _captures.addAll(newItems);
          _offset += res.items.length;
          _total = res.total;
          _isLoadingMore = false;
        });
      }
    } catch (_) {
      if (mounted && requestId == _activeRequestId) {
        setState(() => _isLoadingMore = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Row(
          children: [
            Icon(Icons.lens_blur_rounded, color: AppTheme.primaryLight, size: 22),
            SizedBox(width: 8),
            Text('LENS Captures'),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_ethernet_rounded),
            tooltip: 'Server Settings',
            onPressed: () => ServerConfigDialog.show(
              context,
              onSaved: _loadInitial,
            ),
          ),
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh',
            onPressed: _loadInitial,
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (_isLoading) {
      return const LoadingView(message: 'Loading captures...');
    }

    if (_errorMessage != null) {
      return ErrorView(
        message: _errorMessage!,
        onRetry: _loadInitial,
      );
    }

    if (_captures.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 64,
                height: 64,
                decoration: BoxDecoration(
                  color: AppTheme.primary.withValues(alpha: 0.1),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Icon(
                  Icons.inbox_rounded,
                  size: 32,
                  color: AppTheme.primaryLight,
                ),
              ),
              const SizedBox(height: 16),
              const Text(
                'No Captures Yet',
                style: TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 17,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 8),
              const Text(
                'Save a web link or quick note to get started.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: _loadInitial,
      color: AppTheme.primary,
      backgroundColor: AppTheme.surfaceElevated,
      child: ListView.separated(
        controller: _scrollController,
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 80),
        itemCount: _captures.length + (_isLoadingMore ? 1 : 0),
        separatorBuilder: (context, index) => const SizedBox(height: 12),
        itemBuilder: (context, index) {
          if (index == _captures.length) {
            return const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Center(
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            );
          }

          final capture = _captures[index];
          return _CaptureCard(
            capture: capture,
            onTap: () async {
              await Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => CaptureDetailScreen(
                    captureId: capture.id,
                    initialCapture: capture,
                    apiClient: _client,
                  ),
                ),
              );
              // Refresh on return in case processing state progressed
              if (mounted) {
                _loadInitial();
              }
            },
          );
        },
      ),
    );
  }
}

class _CaptureCard extends StatelessWidget {
  final Capture capture;
  final VoidCallback onTap;

  const _CaptureCard({required this.capture, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final preview = SecurityUtils.truncate(capture.content ?? '', 160);
    final safeUrl = SecurityUtils.sanitizeUrl(capture.originalUrl);

    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Row(
                    children: [
                      SourceBadge(sourceType: capture.sourceType),
                      const SizedBox(width: 8),
                      StatusBadge(status: capture.processingStatus, compact: true),
                    ],
                  ),
                  Text(
                    Formatters.formatDateTime(capture.createdAt),
                    style: const TextStyle(
                      color: AppTheme.textMuted,
                      fontSize: 11,
                      fontFamily: 'monospace',
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                capture.displayTitle,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                  letterSpacing: -0.2,
                ),
              ),
              if (safeUrl != null) ...[
                const SizedBox(height: 6),
                Row(
                  children: [
                    const Icon(Icons.link, size: 14, color: AppTheme.accent),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        safeUrl,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                          color: AppTheme.accent,
                          fontSize: 12,
                          fontFamily: 'monospace',
                        ),
                      ),
                    ),
                  ],
                ),
              ],
              if (preview.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(
                  preview,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppTheme.textSecondary,
                    fontSize: 12.5,
                    height: 1.4,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
