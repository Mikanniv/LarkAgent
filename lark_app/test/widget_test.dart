import 'package:flutter_test/flutter_test.dart';
import 'package:lark_app/main.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  testWidgets('shows auth gate before loading user data', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const LarkApp());
    await tester.pump(const Duration(milliseconds: 1200));
    await tester.pumpAndSettle(const Duration(seconds: 6));

    expect(find.text('云雀'), findsOneWidget);
    expect(find.text('登录云雀'), findsOneWidget);
    expect(find.text('用户名'), findsOneWidget);
  });
}
