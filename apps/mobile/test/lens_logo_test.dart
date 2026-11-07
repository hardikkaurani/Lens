import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lens_mobile/widgets/lens_logo.dart';

void main() {
  group('LensLogo Widget Tests', () {
    testWidgets('renders official mark symbol with specified height', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: LensLogo(height: 32),
          ),
        ),
      );

      expect(find.byType(LensLogo), findsOneWidget);
      expect(find.byType(Image), findsOneWidget);
    });

    testWidgets('renders wordmark and version badge when showWordmark is true', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: LensLogo(
              height: 28,
              showWordmark: true,
              subtitle: 'Personal Knowledge',
            ),
          ),
        ),
      );

      expect(find.byType(LensLogo), findsOneWidget);
      expect(find.text('LENS'), findsOneWidget);
      expect(find.text('v1.0'), findsOneWidget);
      expect(find.text('PERSONAL KNOWLEDGE'), findsOneWidget);
    });

    testWidgets('supports custom version text and alignment', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: LensLogo(
              height: 24,
              showWordmark: true,
              versionText: 'v2.0',
              alignment: MainAxisAlignment.center,
            ),
          ),
        ),
      );

      expect(find.byType(LensLogo), findsOneWidget);
      expect(find.text('LENS'), findsOneWidget);
      expect(find.text('v2.0'), findsOneWidget);
    });
  });
}
