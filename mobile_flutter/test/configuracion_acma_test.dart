import 'package:acma_mobile/configuracion_acma.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('APK usa por defecto el dominio real de ACMA', () {
    expect(ConfiguracionAcma.url?.host, 'groupacma.com');
    expect(ConfiguracionAcma.url?.scheme, 'https');
  });

  test('requiere URL https y no permite credenciales', () {
    expect(ConfiguracionAcma.validarUrl('https://acma.example.com'), isNotNull);
    expect(ConfiguracionAcma.validarUrl('http://acma.example.com'), isNull);
    expect(ConfiguracionAcma.validarUrl('https://user:pass@acma.example.com'), isNull);
    expect(ConfiguracionAcma.validarUrl('javascript:alert(1)'), isNull);
  });

  test('HTTP local solo para desarrollo explícito', () {
    expect(ConfiguracionAcma.validarUrl('http://10.0.2.2:8000', permitirHttp: true), isNotNull);
  });

  test('origen externo no tiene acceso interno', () {
    final base = Uri.parse('https://acma.example.com');
    expect(ConfiguracionAcma.mismoOrigen(base, Uri.parse('https://acma.example.com/folios')), isTrue);
    expect(ConfiguracionAcma.mismoOrigen(base, Uri.parse('https://otro.example.com')), isFalse);
  });
}
