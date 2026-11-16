import 'package:acma_mobile/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('sin URL no expone credenciales ni carga servicios externos', (tester) async {
    await tester.pumpWidget(const AplicacionAcma());
    expect(find.text('Configura la dirección de ACMA'), findsOneWidget);
    expect(find.textContaining('ACMA_BASE_URL'), findsWidgets);
  });
}
