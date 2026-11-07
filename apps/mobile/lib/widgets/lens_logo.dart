import 'package:flutter/material.dart';

/// Official LENS Logo Widget for Flutter Mobile
///
/// Displays the official monochromatic metallic chrome ribbon and detached dot symbol.
class LensLogo extends StatelessWidget {
  final double height;
  final bool showWordmark;
  final String? subtitle;
  final String versionText;
  final MainAxisAlignment alignment;

  const LensLogo({
    super.key,
    this.height = 24.0,
    this.showWordmark = false,
    this.subtitle,
    this.versionText = 'v1.0',
    this.alignment = MainAxisAlignment.start,
  });

  /// Standard aspect ratio of the official LENS symbol (2.38:1)
  static const double symbolAspectRatio = 2.38;

  @override
  Widget build(BuildContext context) {
    final symbolWidth = height * symbolAspectRatio;

    final Widget symbol = Semantics(
      label: showWordmark ? null : 'LENS Symbol',
      excludeSemantics: showWordmark,
      child: Image.asset(
        'assets/branding/lens_symbol.png',
        height: height,
        width: symbolWidth,
        fit: BoxFit.contain,
        filterQuality: FilterQuality.high,
        errorBuilder: (context, error, stackTrace) {
          // Fallback placeholder if asset loading encounters an issue
          return Container(
            height: height,
            width: symbolWidth,
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: const Color(0xFF1E293B),
              borderRadius: BorderRadius.circular(4),
            ),
            child: const Text(
              'LENS',
              style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.bold,
                color: Colors.white70,
              ),
            ),
          );
        },
      ),
    );

    if (!showWordmark) {
      return symbol;
    }

    return Row(
      mainAxisSize: MainAxisSize.min,
      mainAxisAlignment: alignment,
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        symbol,
        const SizedBox(width: 8),
        Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text(
                  'LENS',
                  style: TextStyle(
                    fontSize: 16,
                    fontWeight: FontWeight.w900,
                    letterSpacing: 1.2,
                    color: Colors.white,
                  ),
                ),
                if (versionText.isNotEmpty) ...[
                  const SizedBox(width: 6),
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1.5),
                    decoration: BoxDecoration(
                      color: const Color(0xFF1E293B),
                      borderRadius: BorderRadius.circular(4),
                      border: Border.all(color: const Color(0xFF334155)),
                    ),
                    child: Text(
                      versionText,
                      style: const TextStyle(
                        fontSize: 9,
                        fontWeight: FontWeight.bold,
                        color: Color(0xFF94A3B8),
                      ),
                    ),
                  ),
                ],
              ],
            ),
            if (subtitle != null) ...[
              const SizedBox(height: 1),
              Text(
                subtitle!.toUpperCase(),
                style: const TextStyle(
                  fontSize: 9,
                  fontWeight: FontWeight.w600,
                  letterSpacing: 1.5,
                  color: Color(0xFF64748B),
                ),
              ),
            ],
          ],
        ),
      ],
    );
  }
}
