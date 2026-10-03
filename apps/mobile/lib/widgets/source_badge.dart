import 'package:flutter/material.dart';
import '../core/theme/app_theme.dart';
import '../models/capture.dart';

/// Visual badge denoting source type (Web URL or Quick Note).
class SourceBadge extends StatelessWidget {
  final SourceType sourceType;

  const SourceBadge({super.key, required this.sourceType});

  @override
  Widget build(BuildContext context) {
    final isUrl = sourceType == SourceType.url;
    final color = isUrl ? AppTheme.accent : AppTheme.primaryLight;
    final icon = isUrl ? Icons.link_rounded : Icons.edit_note_rounded;
    final label = isUrl ? 'Web Link' : 'Note';

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
          Text(
            label,
            style: TextStyle(
              color: color,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}
