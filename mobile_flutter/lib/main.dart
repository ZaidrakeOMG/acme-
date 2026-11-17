// ignore_for_file: deprecated_member_use
import 'dart:async';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';
import 'package:webview_flutter_android/webview_flutter_android.dart';

import 'configuracion_acma.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Color(0xFF24242C),
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: Color(0xFFF9F7FA),
    systemNavigationBarIconBrightness: Brightness.dark,
  ));
  runApp(const AplicacionAcma());
}

class AplicacionAcma extends StatelessWidget {
  const AplicacionAcma({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'ACMA',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xFF9F2444),
            surface: const Color(0xFFF9F7FA),
          ),
          useMaterial3: true,
          scaffoldBackgroundColor: const Color(0xFFF9F7FA),
          textTheme: const TextTheme(
            headlineSmall: TextStyle(fontWeight: FontWeight.w800, color: Color(0xFF28262D)),
            titleLarge: TextStyle(fontWeight: FontWeight.w800, color: Color(0xFF28262D)),
            bodyMedium: TextStyle(color: Color(0xFF4E6179), height: 1.45),
          ),
          filledButtonTheme: FilledButtonThemeData(
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xFF9F2444),
              foregroundColor: Colors.white,
              minimumSize: const Size(160, 48),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
          ),
        ),
        home: const VistaAcma(),
      );
}

/// Capa móvil de transición: React se dibuja sin recrearlo ni perder sus estilos.
/// No es todavía una migración nativa pantalla por pantalla.
class VistaAcma extends StatefulWidget {
  const VistaAcma({super.key});

  @override
  State<VistaAcma> createState() => _VistaAcmaState();
}

class _VistaAcmaState extends State<VistaAcma> {
  final Uri? _origen = ConfiguracionAcma.url;
  WebViewController? _controlador;
  int _progreso = 0;
  bool _fallo = false;
  String _detalle = 'No se pudo conectar con ACMA';

  @override
  void initState() {
    super.initState();
    final origen = _origen;
    if (origen == null) return;

    final controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFFF9F7FA))
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (valor) {
            if (mounted) setState(() => _progreso = valor);
          },
          onPageStarted: (_) {
            if (mounted) setState(() { _fallo = false; _progreso = 0; });
          },
          onPageFinished: (_) {
            if (mounted) setState(() => _progreso = 100);
          },
          onWebResourceError: (error) {
            if (error.isForMainFrame == true && mounted) {
              setState(() {
                _fallo = true;
                _detalle = error.description;
              });
            }
          },
          onNavigationRequest: _navegar,
        ),
      );
    _controlador = controller;

    // Adjunta el selector nativo de archivos para evidencias y documentos.
    if (controller.platform is AndroidWebViewController) {
      final android = controller.platform as AndroidWebViewController;
      // Cámara y GPS se piden solo para el sitio ACMA y por solicitud real.
      unawaited(android.setOnPlatformPermissionRequest((solicitud) {
        unawaited(() async {
          final urlActual = await controller.currentUrl();
          final paginaActual = Uri.tryParse(urlActual ?? '');
          final paginaPermitida = paginaActual != null && _origen != null &&
              ConfiguracionAcma.mismoOrigen(_origen, paginaActual);
          final soloCamara = solicitud.types.isNotEmpty &&
              solicitud.types.every((tipo) => tipo == WebViewPermissionResourceType.camera);
          if (!paginaPermitida || !soloCamara) {
            await solicitud.deny();
            return;
          }
          final permiso = await Permission.camera.request();
          if (permiso.isGranted) {
            await solicitud.grant();
          } else {
            await solicitud.deny();
          }
        }());
      }));
      unawaited(android.setGeolocationPermissionsPromptCallbacks(
        onShowPrompt: (solicitud) async {
          final origenSolicitud = Uri.tryParse(solicitud.origin);
          if (origenSolicitud == null || _origen == null ||
              !ConfiguracionAcma.mismoOrigen(_origen, origenSolicitud)) {
            return const GeolocationPermissionsResponse(allow: false, retain: false);
          }
          final permiso = await Permission.locationWhenInUse.request();
          return GeolocationPermissionsResponse(allow: permiso.isGranted, retain: false);
        },
      ));
      unawaited(android.setAllowFileAccess(true));
      unawaited(android.setAllowContentAccess(true));
      unawaited(android.setOnShowFileSelector((parametros) async {
        final elegidos = await FilePicker.pickFiles(
          type: FileType.any,
        );
        if (elegidos.isEmpty) return <String>[];
        final archivos = parametros.mode == FileSelectorMode.openMultiple
            ? elegidos
            : elegidos.take(1);
        return archivos.where((archivo) => archivo.path != null)
            .map((archivo) => Uri.file(archivo.path!).toString()).toList();
      }));
    }
    unawaited(controller.loadRequest(origen));
  }

  NavigationDecision _navegar(NavigationRequest solicitud) {
    final destino = Uri.tryParse(solicitud.url);
    if (destino == null) return NavigationDecision.prevent;
    if (destino.scheme == 'about' || destino.scheme == 'blob') {
      return NavigationDecision.navigate;
    }
    if (_origen != null && ConfiguracionAcma.mismoOrigen(_origen, destino)) {
      return NavigationDecision.navigate;
    }
    if (const {'https', 'http', 'mailto', 'tel', 'sms', 'geo'}.contains(destino.scheme)) {
      unawaited(launchUrl(destino, mode: LaunchMode.externalApplication));
    }
    return NavigationDecision.prevent;
  }

  Future<void> _recargar() async {
    if (mounted) setState(() => _fallo = false);
    await _controlador?.reload();
  }

  Future<void> _volver() async {
    final controlador = _controlador;
    if (controlador != null && await controlador.canGoBack()) {
      await controlador.goBack();
    } else if (Platform.isAndroid) {
      await SystemNavigator.pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_controlador == null) {
      return Scaffold(
        body: SafeArea(child: Center(child: Padding(
          padding: const EdgeInsets.all(28),
          child: _PantallaAvisoAcma(
            icono: Icons.settings_ethernet_rounded,
            titulo: 'Configura la dirección de ACMA',
            descripcion: 'Publica ACMA con HTTPS y configura ACMA_BASE_URL al compilar la aplicación.',
            detalle: '--dart-define=ACMA_BASE_URL=https://tu-acma.com',
          ),
        ))),
      );
    }

    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (salio, _) {
        if (!salio) unawaited(_volver());
      },
      child: Scaffold(
        body: SafeArea(
          child: Stack(children: [
            WebViewWidget(controller: _controlador!),
            if (_progreso < 100 && !_fallo)
              Positioned(top: 0, left: 0, right: 0,
                child: LinearProgressIndicator(
                  value: _progreso / 100,
                  minHeight: 3,
                  color: const Color(0xFF9F2444),
                  backgroundColor: const Color(0xFFF3DEE5),
                )),
            if (_fallo)
              Positioned.fill(child: ColoredBox(
                color: const Color(0xFFF9F7FA),
                child: Center(child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: _PantallaAvisoAcma(
                    icono: Icons.wifi_off_rounded,
                    titulo: 'ACMA no está disponible',
                    descripcion: 'Revisa tu conexión e intenta nuevamente.',
                    detalle: _detalle,
                    accion: FilledButton.icon(
                      onPressed: _recargar,
                      icon: const Icon(Icons.refresh_rounded),
                      label: const Text('Reintentar'),
                    ),
                  ),
                )),
              )),
          ]),
        ),
      ),
    );
  }
}

/// Estados nativos consistentes con el nuevo diseño web; sin emojis.
class _PantallaAvisoAcma extends StatelessWidget {
  const _PantallaAvisoAcma({
    required this.icono,
    required this.titulo,
    required this.descripcion,
    required this.detalle,
    this.accion,
  });

  final IconData icono;
  final String titulo;
  final String descripcion;
  final String detalle;
  final Widget? accion;

  @override
  Widget build(BuildContext context) => ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: Colors.white,
            border: Border.all(color: const Color(0xFFF0DEE4)),
            borderRadius: BorderRadius.circular(26),
            boxShadow: const [BoxShadow(
              blurRadius: 36, offset: Offset(0, 12),
              color: Color(0x14213B64),
            )],
          ),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 30, horizontal: 24),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Container(
                width: 60, height: 60,
                decoration: BoxDecoration(
                  color: const Color(0xFFFBE9EE),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Icon(icono, size: 29, color: const Color(0xFF9F2444)),
              ),
              const SizedBox(height: 16),
              const Text('ACMA', style: TextStyle(
                letterSpacing: 3, fontWeight: FontWeight.w900,
                fontSize: 16, color: Color(0xFF9F2444),
              )),
              const SizedBox(height: 15),
              Text(titulo, style: Theme.of(context).textTheme.titleLarge,
                  textAlign: TextAlign.center),
              const SizedBox(height: 10),
              Text(descripcion, textAlign: TextAlign.center),
              const SizedBox(height: 12),
              SelectableText(detalle, textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 12, color: Color(0xFF62748E))),
              if (accion != null) ...[
                const SizedBox(height: 24),
                accion!,
              ],
            ]),
          ),
        ),
      );
}
