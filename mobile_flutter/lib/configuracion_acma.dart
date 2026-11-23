import 'package:flutter/foundation.dart';

/// La URL apunta al servidor ACMA completo (React compilado + FastAPI).
/// Nunca se guardan aquí claves de Supabase ni contraseñas.
class ConfiguracionAcma {
  static const String _base = String.fromEnvironment('ACMA_BASE_URL', defaultValue: 'https://groupacma.com');
  static const bool _permitirHttpLocal =
      bool.fromEnvironment('ACMA_ALLOW_HTTP', defaultValue: false);

  static Uri? get url => validarUrl(
        _base,
        permitirHttp: !kReleaseMode && _permitirHttpLocal,
      );

  static Uri? validarUrl(String texto, {bool permitirHttp = false}) {
    final url = Uri.tryParse(texto.trim());
    if (url == null || !url.hasAuthority || url.host.isEmpty || url.userInfo.isNotEmpty) {
      return null;
    }
    if (url.scheme != 'https' && !(permitirHttp && url.scheme == 'http')) {
      return null;
    }
    if (url.hasQuery || url.hasFragment) return null;
    return url;
  }

  static bool mismoOrigen(Uri base, Uri destino) =>
      destino.scheme == base.scheme &&
      destino.host.toLowerCase() == base.host.toLowerCase() &&
      destino.port == base.port;
}
