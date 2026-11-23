import 'package:acma_mobile/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('APK oculta servidor y acceso flotante GPS a usuarios', (tester) async {
    // El runner Flutter no dispone de WebView nativo; el fallback debe
    // ser seguro y no revelar direcciones ni opciones internas.
    await tester.pumpWidget(const AplicacionAcma());
    expect(find.text('ACMA no está disponible'), findsOneWidget);
    expect(find.textContaining('Cambiar servidor'), findsNothing);
    expect(find.textContaining('Configurar servidor'), findsNothing);
    expect(find.textContaining('ACMA_BASE_URL'), findsNothing);
    expect(find.byTooltip('Cambiar servidor de ACMA'), findsNothing);
    expect(find.byTooltip('Activar o detener mi ubicación GPS'), findsNothing);
  });
}
