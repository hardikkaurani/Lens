import 'package:flutter/material.dart';
import '../core/theme/app_theme.dart';
import '../core/utils/formatters.dart';
import '../models/capture.dart';

/// Accessible processing status badge with distinct icons and semantic text labels.
class StatusBadge extends StatelessWidget {
  final ProcessingStatus status;
  final bool compact;

  const StatusBadge({
    super.key,
    required this.status,
    this.compact = false,
  });

  @override
  Widget build(BuildContext context) {
    Color bg;
    Color border;
    Color fg;
    IconData icon;
    bool animate = false;

    switch (status) {
      case ProcessingStatus.completed:
        bg = AppTheme.statusCompleted.withValues(alpha: 0.12);
        border = AppTheme.statusCompleted.withValues(alpha: 0.35);
        fg = AppTheme.statusCompleted;
        icon = Icons.check_circle_outline_rounded;
        break;
      case ProcessingStatus.processing:
        bg = AppTheme.statusProcessing.withValues(alpha: 0.12);
        border = AppTheme.statusProcessing.withValues(alpha: 0.35);
        fg = AppTheme.statusProcessing;
        icon = Icons.sync_rounded;
        animate = true;
        break;
      case ProcessingStatus.pending:
        bg = AppTheme.statusPending.withValues(alpha: 0.12);
        border = AppTheme.statusPending.withValues(alpha: 0.35);
        fg = AppTheme.statusPending;
        icon = Icons.hourglass_top_rounded;
        break;
      case ProcessingStatus.failed:
        bg = AppTheme.statusFailed.withValues(alpha: 0.12);
        border = AppTheme.statusFailed.withValues(alpha: 0.35);
        fg = AppTheme.statusFailed;
        icon = Icons.error_outline_rounded;
        break;
    }

    final label = Formatters.formatStatusLabel(status.name);

    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 8 : 10,
        vertical: compact ? 3 : 4,
      ),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: border, width: 1),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (animate)
            SizedBox(
              width: compact ? 12 : 14,
              height: compact ? 12 : 14,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                valueColor: AlwaysStoppedAnimation<Color>(fg),
              ),
            )
          else
            Icon(icon, size: compact ? 12 : 14, color: fg),
          const SizedBox(width: 5),
          Text(
            label,
            style: TextStyle(
              color: fg,
              fontSize: compact ? 11 : 12,
              fontWeight: FontWeight.w600,
              letterSpacing: -0.1,
            ),
          ),
        ],
      ),
    );
  }
}
