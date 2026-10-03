import 'dart:async';
import 'package:flutter/material.dart';
import '../core/errors/api_exception.dart';
import '../core/network/api_client.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../core/utils/security_utils.dart';
import '../models/capture.dart';
import '../widgets/error_view.dart';
import '../widgets/loading_view.dart';
import '../widgets/source_badge.dart';
import '../widgets/status_badge.dart';

/// Detailed inspection screen for a single Capture item.
///
/// Renders metadata, processing status, extracted chunks, and source JSON.
/// Performs bounded polling while capture is pending/processing, stopping immediately
/// upon completion, failure, or screen disposal.
class CaptureDetailScreen extends StatefulWidget {
  final String captureId;
  final Capture? initialCapture;
  final ApiClient? apiClient;

  const CaptureDetailScreen({
    super.key,
    required this.captureId,
    this.initialCapture,
    this.apiClient,
  });

  @override
  State<CaptureDetailScreen> createState() => _CaptureDetailScreenState();
}

class _CaptureDetailScreenState extends State<CaptureDetailScreen> {
  late final ApiClient _client;
  Capture? _capture;
  bool _isLoading = true;
  String? _errorMessage;
  bool _isNotFound = false;

  Timer? _pollTimer;
  int _pollAttempts = 0;
  bool _isFetching = false;
  static const int _maxPollAttempts = 10;
  static const Duration _pollInterval = Duration(seconds: 3);

  @override
  void initState() {
    super.initState();
    _client = widget.apiClient ?? ApiClient();
    _capture = widget.initialCapture;
    if (_capture != null) {
      _isLoading = false;
      _checkStartPolling();
    } else {
      _fetchDetail();
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _pollTimer = null;
    if (widget.apiClient == null) {
      _client.dispose();
    }
    super.dispose();
  }

  Future<void> _fetchDetail({bool background = false}) async {
    if (_isFetching) return;
    _isFetching = true;

    if (!background) {
      setState(() {
        _isLoading = true;
        _errorMessage = null;
        _isNotFound = false;
      });
    }

    try {
      final fetched = await _client.getCapture(widget.captureId);
      if (mounted) {
        setState(() {
          _capture = fetched;
          _isLoading = false;
          _errorMessage = null;
          _isNotFound = false;
        });
        _checkStartPolling();
      }
    } catch (e) {
      if (mounted) {
        final is404 = e is ApiException
            ? e.isNotFound
            : (e.toString().contains('404') || e.toString().toLowerCase().contains('not found'));
        setState(() {
          _isLoading = false;
          if (is404) {
            _isNotFound = true;
            _pollTimer?.cancel();
            _pollTimer = null;
          } else if (!background || _capture == null) {
            _errorMessage = e.toString();
          }
        });
      }
    } finally {
      _isFetching = false;
    }
  }

  void _checkStartPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;

    final isPendingOrProcessing = _capture != null &&
        (_capture!.processingStatus == ProcessingStatus.pending ||
            _capture!.processingStatus == ProcessingStatus.processing);

    if (!mounted) return;

    if (isPendingOrProcessing && _pollAttempts < _maxPollAttempts) {
      _pollTimer = Timer.periodic(_pollInterval, (timer) {
        if (!mounted) {
          timer.cancel();
          _pollTimer = null;
          return;
        }
        if (_isFetching) return;
        _pollAttempts++;
        if (_pollAttempts >= _maxPollAttempts) {
          timer.cancel();
          _pollTimer = null;
        }
        _fetchDetail(background: true);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Capture Details'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh_rounded),
            tooltip: 'Refresh',
            onPressed: () {
              _pollAttempts = 0;
              _fetchDetail();
            },
          ),
        ],
      ),
      body: _buildContent(),
    );
  }

  Widget _buildContent() {
    if (_isLoading && _capture == null) {
      return const LoadingView(message: 'Loading capture details...');
    }

    if (_isNotFound) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.search_off_rounded, size: 54, color: AppTheme.textMuted),
              SizedBox(height: 16),
              Text(
                'Capture Not Found',
                style: TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 18,
                  fontWeight: FontWeight.w700,
                ),
              ),
              SizedBox(height: 8),
              Text(
                'The requested capture does not exist or may have been deleted.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
              ),
            ],
          ),
        ),
      );
    }

    if (_errorMessage != null && _capture == null) {
      return ErrorView(
        message: _errorMessage!,
        onRetry: () => _fetchDetail(),
      );
    }

    if (_capture == null) {
      return const SizedBox.shrink();
    }

    final capture = _capture!;
    final safeUrl = SecurityUtils.sanitizeUrl(capture.originalUrl);
    final chunks = capture.chunks;

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 32),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Header Card
          Card(
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
                          StatusBadge(status: capture.processingStatus),
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
                  const SizedBox(height: 14),
                  SelectableText(
                    capture.displayTitle,
                    style: const TextStyle(
                      color: AppTheme.textPrimary,
                      fontSize: 18,
                      fontWeight: FontWeight.w700,
                      letterSpacing: -0.3,
                    ),
                  ),
                  if (safeUrl != null) ...[
                    const SizedBox(height: 8),
                    SelectableText(
                      safeUrl,
                      style: const TextStyle(
                        color: AppTheme.accent,
                        fontSize: 12,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ],
                ],
              ),
            ),
          ),

          // Processing State Banners
          if (capture.isPending || capture.isProcessing) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: AppTheme.statusPending.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: AppTheme.statusPending.withValues(alpha: 0.3),
                ),
              ),
              child: Row(
                children: [
                  const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      valueColor: AlwaysStoppedAnimation<Color>(AppTheme.statusPending),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          capture.isPending ? 'Queued for Ingestion' : 'Processing Webpage',
                          style: const TextStyle(
                            color: AppTheme.textPrimary,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                        const SizedBox(height: 2),
                        const Text(
                          'Background worker is extracting, chunking, and embedding content.',
                          style: TextStyle(
                            color: AppTheme.textSecondary,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],

          if (capture.isFailed) ...[
            const SizedBox(height: 12),
            Container(
              padding: const EdgeInsets.all(14),
              decoration: BoxDecoration(
                color: AppTheme.statusFailed.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(
                  color: AppTheme.statusFailed.withValues(alpha: 0.3),
                ),
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(
                    Icons.error_outline_rounded,
                    size: 20,
                    color: AppTheme.statusFailed,
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Ingestion Failed',
                          style: TextStyle(
                            color: AppTheme.statusFailed,
                            fontSize: 13,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          capture.processingError ??
                              'The content could not be processed due to an upstream extraction error.',
                          style: const TextStyle(
                            color: AppTheme.textSecondary,
                            fontSize: 12,
                            height: 1.4,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ],

          const SizedBox(height: 20),

          // Chunks / Content Section
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                chunks.isNotEmpty
                    ? 'Extracted Chunks (${chunks.length})'
                    : 'Content',
                style: const TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
              if (capture.processedAt != null)
                Text(
                  'Processed: ${Formatters.formatDateTime(capture.processedAt)}',
                  style: const TextStyle(
                    color: AppTheme.textMuted,
                    fontSize: 11,
                    fontFamily: 'monospace',
                  ),
                ),
            ],
          ),
          const SizedBox(height: 10),

          if (chunks.isNotEmpty)
            ...chunks.map((chunk) => Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Card(
                    color: AppTheme.surfaceElevated,
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            mainAxisAlignment: MainAxisAlignment.spaceBetween,
                            children: [
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 6,
                                  vertical: 2,
                                ),
                                decoration: BoxDecoration(
                                  color: AppTheme.surface,
                                  borderRadius: BorderRadius.circular(4),
                                ),
                                child: Text(
                                  'Chunk #${chunk.chunkIndex + 1}',
                                  style: const TextStyle(
                                    color: AppTheme.primaryLight,
                                    fontSize: 11,
                                    fontWeight: FontWeight.w600,
                                    fontFamily: 'monospace',
                                  ),
                                ),
                              ),
                              Text(
                                '${chunk.content.length} characters',
                                style: const TextStyle(
                                  color: AppTheme.textMuted,
                                  fontSize: 11,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          SelectableText(
                            chunk.content,
                            style: const TextStyle(
                              color: AppTheme.textPrimary,
                              fontSize: 13,
                              height: 1.5,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ))
          else if (capture.content != null && capture.content!.isNotEmpty)
            Card(
              color: AppTheme.surfaceElevated,
              child: Padding(
                padding: const EdgeInsets.all(14),
                child: SelectableText(
                  capture.content!,
                  style: const TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 13.5,
                    height: 1.5,
                  ),
                ),
              ),
            )
          else
            Card(
              color: AppTheme.surfaceElevated,
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Center(
                  child: Text(
                    capture.isCompleted
                        ? 'No extracted textual chunks available for this capture.'
                        : 'Content will appear once worker chunking completes.',
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: AppTheme.textMuted,
                      fontSize: 12,
                    ),
                  ),
                ),
              ),
            ),

          if (capture.metadata != null && capture.metadata!.isNotEmpty) ...[
            const SizedBox(height: 20),
            const Text(
              'Source Metadata',
              style: TextStyle(
                color: AppTheme.textPrimary,
                fontSize: 14,
                fontWeight: FontWeight.w700,
              ),
            ),
            const SizedBox(height: 8),
            Card(
              color: AppTheme.surfaceElevated,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: SelectableText(
                  capture.metadata.toString(),
                  style: const TextStyle(
                    color: AppTheme.accent,
                    fontSize: 12,
                    fontFamily: 'monospace',
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}



