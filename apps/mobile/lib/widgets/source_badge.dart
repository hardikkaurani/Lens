import 'package:flutter/material.dart';
import '../core/theme/app_theme.dart';
import '../models/capture.dart';

/// Visual badge denoting source or activity type (Web Link, Note, PDF, PR, Issue, Commit, Review).
class SourceBadge extends StatelessWidget {
  final SourceType sourceType;

  const SourceBadge({super.key, required this.sourceType});

  @override
  Widget build(BuildContext context) {
    Color color;
    IconData icon;
    String label;

    switch (sourceType) {
      case SourceType.url:
        color = AppTheme.accent;
        icon = Icons.link_rounded;
        label = 'Web Link';
        break;
      case SourceType.text:
        color = AppTheme.primaryLight;
        icon = Icons.edit_note_rounded;
        label = 'Note';
        break;
      case SourceType.pdf:
        color = const Color(0xFF10B981);
        icon = Icons.picture_as_pdf_rounded;
        label = 'PDF';
        break;
      case SourceType.pullRequest:
        color = const Color(0xFFA855F7);
        icon = Icons.call_split_rounded;
        label = 'Pull Request';
        break;
      case SourceType.issue:
        color = const Color(0xFF22C55E);
        icon = Icons.error_outline_rounded;
        label = 'Issue';
        break;
      case SourceType.commit:
        color = const Color(0xFF06B6D4);
        icon = Icons.commit_rounded;
        label = 'Commit';
        break;
      case SourceType.review:
        color = const Color(0xFFF59E0B);
        icon = Icons.rate_review_outlined;
        label = 'Review';
        break;
      case SourceType.github:
        color = const Color(0xFF94A3B8);
        icon = Icons.code_rounded;
        label = 'GitHub';
        break;
      case SourceType.image:
        color = const Color(0xFFEC4899);
        icon = Icons.image_rounded;
        label = 'Image';
        break;
      case SourceType.file:
        color = const Color(0xFF94A3B8);
        icon = Icons.insert_drive_file_rounded;
        label = 'File';
        break;
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: color.withValues(alpha: 0.25), width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 13, color: color),
          const SizedBox(width: 4),
          Flexible(
            child: Text(
              label,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                color: color,
                fontSize: 11,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
