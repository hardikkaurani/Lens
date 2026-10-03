import 'content_chunk.dart';

/// Processing status values matching the backend FastAPI enum.
enum ProcessingStatus {
  pending,
  processing,
  completed,
  failed;

  static ProcessingStatus fromString(String? value) {
    switch (value?.toLowerCase()) {
      case 'processing':
        return ProcessingStatus.processing;
      case 'completed':
        return ProcessingStatus.completed;
      case 'failed':
        return ProcessingStatus.failed;
      case 'pending':
      default:
        return ProcessingStatus.pending;
    }
  }

  String toApiString() => name;
}

/// Source type values matching the backend FastAPI enum.
enum SourceType {
  url,
  text;

  static SourceType fromString(String? value) {
    switch (value?.toLowerCase()) {
      case 'text':
        return SourceType.text;
      case 'url':
      default:
        return SourceType.url;
    }
  }

  String toApiString() => name;
}

/// Core domain model for a captured information item.
class Capture {
  final String id;
  final SourceType sourceType;
  final ProcessingStatus processingStatus;
  final String? processingError;
  final DateTime? processedAt;
  final String? title;
  final String? originalUrl;
  final String? content;
  final String? mimeType;
  final String? sourceId;
  final DateTime createdAt;
  final DateTime updatedAt;
  final Map<String, dynamic>? metadata;
  final List<ContentChunk> chunks;

  const Capture({
    required this.id,
    required this.sourceType,
    required this.processingStatus,
    this.processingError,
    this.processedAt,
    this.title,
    this.originalUrl,
    this.content,
    this.mimeType,
    this.sourceId,
    required this.createdAt,
    required this.updatedAt,
    this.metadata,
    this.chunks = const [],
  });

  bool get isPending => processingStatus == ProcessingStatus.pending;
  bool get isProcessing => processingStatus == ProcessingStatus.processing;
  bool get isCompleted => processingStatus == ProcessingStatus.completed;
  bool get isFailed => processingStatus == ProcessingStatus.failed;

  String get displayTitle {
    if (title != null && title!.trim().isNotEmpty) {
      return title!.trim();
    }
    if (originalUrl != null && originalUrl!.trim().isNotEmpty) {
      return originalUrl!.trim();
    }
    return 'Untitled Note';
  }

  factory Capture.fromJson(Map<String, dynamic> json) {
    final rawChunks = json['chunks'];
    List<ContentChunk> chunkList = [];
    if (rawChunks is List) {
      chunkList = rawChunks
          .whereType<Map<String, dynamic>>()
          .map((c) => ContentChunk.fromJson(c))
          .toList()
        ..sort((a, b) => a.chunkIndex.compareTo(b.chunkIndex));
    }

    final id = json['id']?.toString() ?? '';
    final createdAtStr = json['created_at']?.toString();
    final updatedAtStr = json['updated_at']?.toString();
    final processedAtStr = json['processed_at']?.toString();

    return Capture(
      id: id,
      sourceType: SourceType.fromString(json['source_type']?.toString()),
      processingStatus: ProcessingStatus.fromString(json['processing_status']?.toString()),
      processingError: json['processing_error']?.toString(),
      processedAt: processedAtStr != null ? DateTime.tryParse(processedAtStr) : null,
      title: json['title']?.toString(),
      originalUrl: json['original_url']?.toString(),
      content: json['content']?.toString(),
      mimeType: json['mime_type']?.toString(),
      sourceId: json['source_id']?.toString(),
      createdAt: createdAtStr != null ? (DateTime.tryParse(createdAtStr) ?? DateTime.now()) : DateTime.now(),
      updatedAt: updatedAtStr != null ? (DateTime.tryParse(updatedAtStr) ?? DateTime.now()) : DateTime.now(),
      metadata: json['metadata'] is Map<String, dynamic> ? json['metadata'] as Map<String, dynamic> : null,
      chunks: chunkList,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'source_type': sourceType.toApiString(),
      'processing_status': processingStatus.toApiString(),
      'processing_error': processingError,
      'processed_at': processedAt?.toIso8601String(),
      'title': title,
      'original_url': originalUrl,
      'content': content,
      'mime_type': mimeType,
      'source_id': sourceId,
      'created_at': createdAt.toIso8601String(),
      'updated_at': updatedAt.toIso8601String(),
      if (metadata != null) 'metadata': metadata,
      if (chunks.isNotEmpty) 'chunks': chunks.map((c) => c.toJson()).toList(),
    };
  }
}

/// Request payload for creating a new Capture.
class CaptureCreate {
  final SourceType sourceType;
  final String? originalUrl;
  final String? title;
  final String? content;
  final Map<String, dynamic>? metadata;

  const CaptureCreate({
    required this.sourceType,
    this.originalUrl,
    this.title,
    this.content,
    this.metadata,
  });

  Map<String, dynamic> toJson() {
    final map = <String, dynamic>{
      'source_type': sourceType.toApiString(),
    };
    if (originalUrl != null && originalUrl!.trim().isNotEmpty) {
      map['original_url'] = originalUrl!.trim();
    }
    if (title != null && title!.trim().isNotEmpty) {
      map['title'] = title!.trim();
    }
    if (content != null && content!.trim().isNotEmpty) {
      map['content'] = content!.trim();
    }
    if (metadata != null && metadata!.isNotEmpty) {
      map['metadata'] = metadata;
    }
    return map;
  }
}

/// Paginated response from GET /captures.
class CaptureListResponse {
  final List<Capture> items;
  final int total;
  final int limit;
  final int offset;

  const CaptureListResponse({
    required this.items,
    required this.total,
    required this.limit,
    required this.offset,
  });

  bool get hasMore => offset + items.length < total;

  factory CaptureListResponse.fromJson(Map<String, dynamic> json) {
    final rawItems = json['items'] as List? ?? [];
    return CaptureListResponse(
      items: rawItems
          .whereType<Map<String, dynamic>>()
          .map((i) => Capture.fromJson(i))
          .toList(),
      total: (json['total'] as num?)?.toInt() ?? 0,
      limit: (json['limit'] as num?)?.toInt() ?? 15,
      offset: (json['offset'] as num?)?.toInt() ?? 0,
    );
  }
}
