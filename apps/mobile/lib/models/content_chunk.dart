/// Domain model for an extracted content chunk.
class ContentChunk {
  final String id;
  final int chunkIndex;
  final String content;
  final DateTime createdAt;

  const ContentChunk({
    required this.id,
    required this.chunkIndex,
    required this.content,
    required this.createdAt,
  });

  factory ContentChunk.fromJson(Map<String, dynamic> json) {
    final id = json['id']?.toString() ?? '';
    final createdAtStr = json['created_at']?.toString();
    return ContentChunk(
      id: id,
      chunkIndex: (json['chunk_index'] as num?)?.toInt() ?? 0,
      content: json['content']?.toString() ?? '',
      createdAt: createdAtStr != null ? (DateTime.tryParse(createdAtStr) ?? DateTime.now()) : DateTime.now(),
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'id': id,
      'chunk_index': chunkIndex,
      'content': content,
      'created_at': createdAt.toIso8601String(),
    };
  }
}
