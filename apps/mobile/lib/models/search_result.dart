/// Individual matching content chunk with relevance scoring.
class SearchResultChunk {
  final String chunkId;
  final int chunkIndex;
  final String contentExcerpt;
  final double score;
  final double? lexicalScore;
  final double? semanticScore;

  const SearchResultChunk({
    required this.chunkId,
    required this.chunkIndex,
    required this.contentExcerpt,
    required this.score,
    this.lexicalScore,
    this.semanticScore,
  });

  factory SearchResultChunk.fromJson(Map<String, dynamic> json) {
    return SearchResultChunk(
      chunkId: json['chunk_id']?.toString() ?? '',
      chunkIndex: (json['chunk_index'] as num?)?.toInt() ?? 0,
      contentExcerpt: json['content_excerpt']?.toString() ?? '',
      score: (json['score'] as num?)?.toDouble() ?? 0.0,
      lexicalScore: (json['lexical_score'] as num?)?.toDouble(),
      semanticScore: (json['semantic_score'] as num?)?.toDouble(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'chunk_id': chunkId,
      'chunk_index': chunkIndex,
      'content_excerpt': contentExcerpt,
      'score': score,
      if (lexicalScore != null) 'lexical_score': lexicalScore,
      if (semanticScore != null) 'semantic_score': semanticScore,
    };
  }
}

/// Grouped capture or GitHub activity search result containing matching chunks.
class SearchResultCapture {
  final String captureId;
  final String? title;
  final String? originalUrl;
  final String sourceType;
  final double bestScore;
  final double? bestLexicalScore;
  final double? bestSemanticScore;
  final List<SearchResultChunk> matchingChunks;
  final String? resultKind;
  final String? activityType;
  final String? repositoryName;
  final String? authorLogin;
  final String? state;
  final String? externalId;

  const SearchResultCapture({
    required this.captureId,
    this.title,
    this.originalUrl,
    required this.sourceType,
    required this.bestScore,
    this.bestLexicalScore,
    this.bestSemanticScore,
    this.matchingChunks = const [],
    this.resultKind,
    this.activityType,
    this.repositoryName,
    this.authorLogin,
    this.state,
    this.externalId,
  });

  bool get isGitHubActivity =>
      resultKind == 'github_activity' ||
      const ['pull_request', 'issue', 'commit', 'review', 'github'].contains(sourceType.toLowerCase());

  String get displayTitle {
    if (title != null && title!.trim().isNotEmpty) {
      return title!.trim();
    }
    if (originalUrl != null && originalUrl!.trim().isNotEmpty) {
      return originalUrl!.trim();
    }
    if (isGitHubActivity) {
      return 'GitHub Activity';
    }
    return 'Untitled Capture';
  }

  factory SearchResultCapture.fromJson(Map<String, dynamic> json) {
    final rawChunks = json['matching_chunks'] as List? ?? [];
    return SearchResultCapture(
      captureId: json['capture_id']?.toString() ?? '',
      title: json['title']?.toString(),
      originalUrl: json['original_url']?.toString(),
      sourceType: json['source_type']?.toString() ?? 'url',
      bestScore: (json['best_score'] as num?)?.toDouble() ?? 0.0,
      bestLexicalScore: (json['best_lexical_score'] as num?)?.toDouble(),
      bestSemanticScore: (json['best_semantic_score'] as num?)?.toDouble(),
      matchingChunks: rawChunks
          .whereType<Map<String, dynamic>>()
          .map((c) => SearchResultChunk.fromJson(c))
          .toList(),
      resultKind: json['result_kind']?.toString(),
      activityType: json['activity_type']?.toString(),
      repositoryName: json['repository_name']?.toString(),
      authorLogin: json['author_login']?.toString(),
      state: json['state']?.toString(),
      externalId: json['external_id']?.toString(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'capture_id': captureId,
      'title': title,
      'original_url': originalUrl,
      'source_type': sourceType,
      'best_score': bestScore,
      if (bestLexicalScore != null) 'best_lexical_score': bestLexicalScore,
      if (bestSemanticScore != null) 'best_semantic_score': bestSemanticScore,
      'matching_chunks': matchingChunks.map((c) => c.toJson()).toList(),
      if (resultKind != null) 'result_kind': resultKind,
      if (activityType != null) 'activity_type': activityType,
      if (repositoryName != null) 'repository_name': repositoryName,
      if (authorLogin != null) 'author_login': authorLogin,
      if (state != null) 'state': state,
      if (externalId != null) 'external_id': externalId,
    };
  }
}

/// Top-level search response from GET /search.
class SearchResponse {
  final String query;
  final int total;
  final int limit;
  final bool degraded;
  final String? sourceFilter;
  final List<SearchResultCapture> results;

  const SearchResponse({
    required this.query,
    required this.total,
    required this.limit,
    this.degraded = false,
    this.sourceFilter,
    required this.results,
  });

  factory SearchResponse.fromJson(Map<String, dynamic> json) {
    final rawResults = json['results'] as List? ?? [];
    return SearchResponse(
      query: json['query'] as String? ?? '',
      total: (json['total'] as num?)?.toInt() ?? 0,
      limit: (json['limit'] as num?)?.toInt() ?? 20,
      degraded: json['degraded'] as bool? ?? false,
      sourceFilter: json['source_filter'] as String?,
      results: rawResults
          .whereType<Map<String, dynamic>>()
          .map((r) => SearchResultCapture.fromJson(r))
          .toList(),
    );
  }
}
