import 'package:flutter/material.dart';
import '../core/network/api_client.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../core/utils/security_utils.dart';
import '../models/search_result.dart';
import '../widgets/error_view.dart';
import '../widgets/loading_view.dart';
import '../widgets/source_badge.dart';
import '../models/capture.dart';
import 'capture_detail_screen.dart';

/// Search screen executing hybrid lexical + semantic queries against LENS.
class SearchScreen extends StatefulWidget {
  final ApiClient? apiClient;

  const SearchScreen({super.key, this.apiClient});

  @override
  State<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends State<SearchScreen> {
  late final ApiClient _client;
  final TextEditingController _searchController = TextEditingController();

  bool _isLoading = false;
  String? _errorMessage;
  SearchResponse? _searchResponse;
  String _lastSearchedQuery = '';
  int _activeRequestId = 0;

  @override
  void initState() {
    super.initState();
    _client = widget.apiClient ?? ApiClient();
  }

  @override
  void dispose() {
    _searchController.dispose();
    if (widget.apiClient == null) {
      _client.dispose();
    }
    super.dispose();
  }

  Future<void> _performSearch() async {
    FocusScope.of(context).unfocus();

    final query = _searchController.text.trim();
    if (query.isEmpty) {
      setState(() {
        _searchResponse = null;
        _errorMessage = null;
        _lastSearchedQuery = '';
      });
      return;
    }

    if (query.length > 500) {
      setState(() {
        _errorMessage = 'Search query cannot exceed 500 characters.';
      });
      return;
    }

    final currentId = ++_activeRequestId;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
      _lastSearchedQuery = query;
    });

    try {
      final res = await _client.search(query: query, limit: 20);

      // Race-condition safety: discard response if a newer search was initiated
      if (currentId == _activeRequestId && mounted) {
        setState(() {
          _searchResponse = res;
          _isLoading = false;
        });
      }
    } catch (e) {
      if (currentId == _activeRequestId && mounted) {
        setState(() {
          _errorMessage = e.toString();
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Search Knowledge'),
      ),
      body: Column(
        children: [
          // Search Input Bar
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
            child: Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _searchController,
                    textInputAction: TextInputAction.search,
                    maxLength: 500,
                    onSubmitted: (_) => _performSearch(),
                    decoration: InputDecoration(
                      hintText: 'Search concepts, code, links...',
                      prefixIcon: const Icon(Icons.search_rounded, size: 20),
                      counterText: '',
                      suffixIcon: _searchController.text.isNotEmpty
                          ? IconButton(
                              icon: const Icon(Icons.clear_rounded, size: 18),
                              onPressed: () {
                                _searchController.clear();
                                setState(() {
                                  _searchResponse = null;
                                  _errorMessage = null;
                                  _lastSearchedQuery = '';
                                });
                              },
                            )
                          : null,
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                ),
                const SizedBox(width: 10),
                IconButton.filled(
                  onPressed: _searchController.text.trim().isEmpty ? null : _performSearch,
                  icon: const Icon(Icons.arrow_forward_rounded, size: 20),
                  style: IconButton.styleFrom(
                    backgroundColor: AppTheme.primary,
                    disabledBackgroundColor: AppTheme.surfaceElevated,
                    minimumSize: const Size(48, 48),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                  ),
                ),
              ],
            ),
          ),

          // Search Results Body
          Expanded(child: _buildResults()),
        ],
      ),
    );
  }

  Widget _buildResults() {
    if (_isLoading) {
      return const LoadingView(message: 'Searching knowledge base...');
    }

    if (_errorMessage != null) {
      return ErrorView(
        message: _errorMessage!,
        onRetry: _performSearch,
      );
    }

    if (_searchResponse == null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.manage_search_rounded, size: 54, color: AppTheme.textMuted.withValues(alpha: 0.5)),
              const SizedBox(height: 14),
              const Text(
                'Hybrid Knowledge Retrieval',
                style: TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Enter keywords or natural language concepts to search across all captures.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
              ),
            ],
          ),
        ),
      );
    }

    final results = _searchResponse!.results;

    if (results.isEmpty) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.search_off_rounded, size: 48, color: AppTheme.textMuted),
              const SizedBox(height: 14),
              Text(
                'No matches for "$_lastSearchedQuery"',
                style: const TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 16,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Try different keywords or check spelling.',
                style: TextStyle(color: AppTheme.textSecondary, fontSize: 13),
              ),
            ],
          ),
        ),
      );
    }

    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 80),
      children: [
        if (_searchResponse!.degraded) ...[
          Container(
            margin: const EdgeInsets.only(bottom: 12),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: const Color(0xFFF59E0B).withValues(alpha: 0.1),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(
                color: const Color(0xFFF59E0B).withValues(alpha: 0.3),
              ),
            ),
            child: const Row(
              children: [
                Icon(Icons.info_outline, size: 16, color: Color(0xFFF59E0B)),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Lexical-only fallback active: embedding service is unavailable.',
                    style: TextStyle(color: Color(0xFFF59E0B), fontSize: 12),
                  ),
                ),
              ],
            ),
          ),
        ],
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(
            'Found ${_searchResponse!.total} matching capture${_searchResponse!.total == 1 ? '' : 's'}',
            style: const TextStyle(
              color: AppTheme.textMuted,
              fontSize: 12,
              fontWeight: FontWeight.w500,
            ),
          ),
        ),
        ...results.map((result) => _SearchResultCard(
              result: result,
              onTap: () {
                Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => CaptureDetailScreen(
                      captureId: result.captureId,
                      apiClient: _client,
                    ),
                  ),
                );
              },
            )),
      ],
    );
  }
}

class _SearchResultCard extends StatelessWidget {
  final SearchResultCapture result;
  final VoidCallback onTap;

  const _SearchResultCard({required this.result, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final bestChunk = result.matchingChunks.isNotEmpty ? result.matchingChunks.first : null;
    final excerpt = bestChunk?.contentExcerpt ?? '';
    final safeUrl = SecurityUtils.sanitizeUrl(result.originalUrl);

    return Card(
      margin: const EdgeInsets.only(bottom: 12),
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
                  SourceBadge(
                    sourceType: SourceType.fromString(result.sourceType),
                  ),
                  _ScoreBadge(score: result.bestScore),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                result.displayTitle,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: AppTheme.textPrimary,
                  fontSize: 15,
                  fontWeight: FontWeight.w700,
                ),
              ),
              if (safeUrl != null) ...[
                const SizedBox(height: 4),
                Text(
                  safeUrl,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                    color: AppTheme.accent,
                    fontSize: 11,
                    fontFamily: 'monospace',
                  ),
                ),
              ],
              if (excerpt.isNotEmpty) ...[
                const SizedBox(height: 10),
                Container(
                  padding: const EdgeInsets.all(10),
                  decoration: BoxDecoration(
                    color: AppTheme.surfaceElevated,
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    excerpt,
                    maxLines: 3,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: AppTheme.textSecondary,
                      fontSize: 12.5,
                      height: 1.4,
                    ),
                  ),
                ),
              ],
              if (bestChunk != null &&
                  (bestChunk.lexicalScore != null || bestChunk.semanticScore != null)) ...[
                const SizedBox(height: 10),
                Wrap(
                  spacing: 8,
                  children: [
                    if (bestChunk.lexicalScore != null)
                      _ScoreChip(
                        label: 'Lexical',
                        score: bestChunk.lexicalScore!,
                        color: AppTheme.accent,
                      ),
                    if (bestChunk.semanticScore != null)
                      _ScoreChip(
                        label: 'Semantic',
                        score: bestChunk.semanticScore!,
                        color: AppTheme.primaryLight,
                      ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _ScoreBadge extends StatelessWidget {
  final double score;

  const _ScoreBadge({required this.score});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: AppTheme.primary.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(
          color: AppTheme.primary.withValues(alpha: 0.3),
        ),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.bolt_rounded, size: 12, color: AppTheme.primaryLight),
          const SizedBox(width: 3),
          Text(
            Formatters.formatScore(score),
            style: const TextStyle(
              color: AppTheme.primaryLight,
              fontSize: 11,
              fontWeight: FontWeight.w700,
              fontFamily: 'monospace',
            ),
          ),
        ],
      ),
    );
  }
}

class _ScoreChip extends StatelessWidget {
  final String label;
  final double score;
  final Color color;

  const _ScoreChip({
    required this.label,
    required this.score,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Text(
      '$label: ${Formatters.formatScore(score)}',
      style: TextStyle(
        color: color.withValues(alpha: 0.8),
        fontSize: 11,
        fontFamily: 'monospace',
      ),
    );
  }
}
