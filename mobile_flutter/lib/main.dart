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

class _VistaAcmaState extends State<VistaAcma> with WidgetsBindingObserver {
  Uri? _origen = ConfiguracionAcma.url;
  WebViewController? _controlador;
  int _progreso = 0;
  bool _fallo = false;
  String _detalle = 'No se pudo conectar con ACMA';
  // En Android se solicitan al abrir la APK, antes de mostrar la WebView.
  // Nunca supone autorización: el SO puede denegar ambos permisos.
  bool? _permisosAndroidOk;
  bool _revisandoPermisos = false;
  String? _errorPermisosAndroid;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    final destino = _origen;
    if (destino != null) _abrirServidor(destino);
    if (Platform.isAndroid) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) unawaited(_comprobarPermisosAndroid(solicitar: true));
      });
    }
  }

  Future<void> _comprobarPermisosAndroid({bool solicitar = false}) async {
    if (!Platform.isAndroid || !mounted || _revisandoPermisos) return;
    setState(() {
      _revisandoPermisos = true;
      _errorPermisosAndroid = null;
    });
    try {
      var notificaciones = await Permission.notification.status;
      if (solicitar && !notificaciones.isGranted) {
        notificaciones = await Permission.notification.request();
      }
      var ubicacion = await Permission.locationWhenInUse.status;
      if (solicitar && !ubicacion.isGranted) {
        ubicacion = await Permission.locationWhenInUse.request();
      }
      if (!mounted) return;
      setState(() {
        _permisosAndroidOk = notificaciones.isGranted && ubicacion.isGranted;
        if (_permisosAndroidOk != true) {
          _errorPermisosAndroid =
              'ACMA necesita el permiso de notificaciones y de ubicación. '
              'Autorízalos desde Android o abre Ajustes para concederlos.';
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _permisosAndroidOk = false;
        _errorPermisosAndroid =
            'No fue posible comprobar los permisos. Revísalos desde '
            'Ajustes de Android y vuelve a intentarlo.';
      });
    } finally {
      if (mounted) setState(() => _revisandoPermisos = false);
    }
  }

  /// Estado Android verificado por el sistema, no por el navegador WebView.
  /// Permite recuperar el login si una versión anterior no expuso el canal JS.
  Future<void> _publicarNotificacionesEnWeb() async {
    final controlador = _controlador;
    final base = _origen;
    if (controlador == null || base == null || !Platform.isAndroid) return;
    try {
      final uri = Uri.tryParse(await controlador.currentUrl() ?? '');
      if (uri == null || !ConfiguracionAcma.mismoOrigen(base, uri)) return;
      final estado = await Permission.notification.status;
      await controlador.runJavaScript(
        'window.__acmaNotificacionesAutorizadas = ${estado.isGranted};'
        'window.__acmaAppVersion = "0.1.6";',
      );
    } catch (_) {
      // La pantalla continúa operativa: el canal nativo es la primera opción.
    }
  }


  void _abrirServidor(Uri origen) {
    if (!mounted) return;
    final controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(const Color(0xFFF9F7FA))
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (valor) {
            // Evitar reconstruir toda la WebView por cada 1% de carga.
            if (mounted && (valor == 100 || valor >= _progreso + 15)) {
              setState(() => _progreso = valor);
            }
          },
          onPageStarted: (_) {
            if (mounted) setState(() { _fallo = false; _progreso = 0; });
          },
          onPageFinished: (_) {
            if (mounted && _progreso != 100) setState(() => _progreso = 100);
            unawaited(_publicarNotificacionesEnWeb());
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
    // JavaScriptChannel para el permiso NATIVO de notificaciones Android.
    // El navegador WebView normalmente no expone Notification.requestPermission.
    // Nunca responder a sitios o marcos ajenos al dominio HTTPS de ACMA.
    final puentePermisos = controller.addJavaScriptChannel(
      'AcmaPermisos',
      onMessageReceived: (mensaje) {
        unawaited(() async {
          final actual = Uri.tryParse(await controller.currentUrl() ?? '');
          if (actual == null ||
              !ConfiguracionAcma.mismoOrigen(origen, actual)) {
            return;
          }
          if (mensaje.message == 'abrir_ajustes') {
            await openAppSettings();
            return;
          }
          if (mensaje.message != 'solicitar_notificaciones') return;
          bool autorizado = false;
          try {
            final estado = await Permission.notification.request();
            autorizado = estado.isGranted;
          } catch (_) {
            // El usuario puede reintentar desde ajustes del dispositivo.
          }
          final resultado = autorizado ? 'true' : 'false';
          try {
            await controller.runJavaScript(
              "window.dispatchEvent(new CustomEvent('acma:permiso-notificaciones', "
              "{detail:{autorizado:$resultado}}));",
            );
          } catch (_) {
            // La WebView pudo cambiar de página mientras abría los ajustes.
          }
        }());
      },
    );
    // Adjunta el selector nativo de archivos para evidencias y documentos.
    if (controller.platform is AndroidWebViewController) {
      final android = controller.platform as AndroidWebViewController;
      // Cámara y GPS se piden solo para el sitio ACMA y por solicitud real.
      unawaited(android.setOnPlatformPermissionRequest((solicitud) {
        unawaited(() async {
          final urlActual = await controller.currentUrl();
          final paginaActual = Uri.tryParse(urlActual ?? '');
          final paginaPermitida = paginaActual != null && _origen != null &&
              ConfiguracionAcma.mismoOrigen(_origen!, paginaActual);
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
              !ConfiguracionAcma.mismoOrigen(_origen!, origenSolicitud)) {
            return const GeolocationPermissionsResponse(allow: false, retain: false);
          }
          var permiso = await Permission.locationWhenInUse.status;
          if (!permiso.isGranted) {
            permiso = await Permission.locationWhenInUse.request();
          }
          // El origen HTTPS ya autorizado no debe preguntar otra vez en
          // cada lectura de GPS de la misma WebView.
          return GeolocationPermissionsResponse(
              allow: permiso.isGranted, retain: permiso.isGranted);
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
    setState(() {
      _origen = origen;
      _controlador = controller;
      _fallo = false;
      _progreso = 0;
    });
    // El puente tiene que estar listo ANTES de cargar la página de login.
    unawaited(puentePermisos.then((_) => controller.loadRequest(origen)));
  }


  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    if (state != AppLifecycleState.resumed) return;
    if (Platform.isAndroid) {
      unawaited(_comprobarPermisosAndroid());
    }
    final controlador = _controlador;
    if (controlador == null) return;
    // No recargamos la WebView: se perderían formularios sin guardar.
    // React reintenta restaurar la cookie segura cuando la app vuelve al primer plano.
    unawaited(controlador.runJavaScript(
      "window.dispatchEvent(new Event('acma:resume'));",
    ).catchError((_) {}));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  NavigationDecision _navegar(NavigationRequest solicitud) {
    final destino = Uri.tryParse(solicitud.url);
    if (destino == null) return NavigationDecision.prevent;
    if (destino.scheme == 'about' || destino.scheme == 'blob') {
      return NavigationDecision.navigate;
    }
    if (_origen != null && ConfiguracionAcma.mismoOrigen(_origen!, destino)) {
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
    if (Platform.isAndroid && _permisosAndroidOk != true) {
      return Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.verified_user_outlined,
                        color: Color(0xFF047857), size: 64),
                    const SizedBox(height: 20),
                    const Text('Permisos necesarios para ACMA',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: 23, fontWeight: FontWeight.bold)),
                    const SizedBox(height: 14),
                    const Text(
                      'Al iniciar ACMA debes autorizar las notificaciones y '
                      'la ubicación del teléfono. Son necesarias para '
                      'utilizar esta aplicación. No se puede omitir este paso.',
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      'La ubicación se comparte con supervisores autorizados '
                      'solo después de iniciar sesión y activar el rastreo. '
                      'No se obtiene ubicación con la app cerrada.',
                      textAlign: TextAlign.center,
                      style: TextStyle(fontSize: 12, color: Color(0xFF62748E)),
                    ),
                    if (_errorPermisosAndroid != null) ...[
                      const SizedBox(height: 18),
                      Text(_errorPermisosAndroid!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(color: Color(0xFF9C4219))),
                    ],
                    const SizedBox(height: 24),
                    if (_revisandoPermisos)
                      const CircularProgressIndicator()
                    else ...[
                      SizedBox(
                        width: double.infinity,
                        child: FilledButton.icon(
                          icon: const Icon(Icons.shield_outlined),
                          onPressed: () => unawaited(
                              _comprobarPermisosAndroid(solicitar: true)),
                          label: const Text('Autorizar ubicación y notificaciones'),
                        ),
                      ),
                      const SizedBox(height: 10),
                      SizedBox(
                        width: double.infinity,
                        child: OutlinedButton.icon(
                          icon: const Icon(Icons.settings_outlined),
                          onPressed: () => unawaited(openAppSettings()),
                          label: const Text('Abrir ajustes de permisos'),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      );
    }
    if (_controlador == null) {
      return Scaffold(
        body: SafeArea(child: Center(child: Padding(
          padding: const EdgeInsets.all(28),
          child: _PantallaAvisoAcma(
            icono: Icons.wifi_off_rounded,
            titulo: 'ACMA no está disponible',
            descripcion: 'No se pudo establecer conexión con el servicio.',
            detalle: 'Verifica tu conexión e intenta abrir ACMA otra vez.',
            accion: FilledButton.icon(
              onPressed: () {
                final servidor = ConfiguracionAcma.url;
                if (servidor != null) _abrirServidor(servidor);
              },
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Reintentar'),
            ),
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
