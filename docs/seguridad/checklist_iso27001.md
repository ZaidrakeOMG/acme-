# Checklist ISO 27001 · ACMA

Qué pide la norma, qué hace ACMA y dónde se comprueba. Cada fila apunta al código y a la prueba automática que la
respalda, para que una auditoría pueda verificarla sin leer todo el sistema.

Estado al cierre de **P11a (5 de noviembre de 2026)**. Las filas marcadas *pendiente del cliente* no son trabajo de
software: dependen de una decisión o de la infraestructura que contrate el cliente, y están listadas en
[`docs/decisiones_para_validar.md`](../decisiones_para_validar.md).

Leyenda: ✅ implementado y probado · ⚙️ implementado, se verifica al desplegar · 🏢 pendiente del cliente · 🗓️ Fase 2.

---

## 1. Los seis requisitos del diseño §6.9.5

| Requisito ISO 27001 | Lo que pide el diseño v2.5 | Estado | Dónde está | Prueba |
|---|---|---|---|---|
| MFA | TOTP obligatorio para Admin empresa, Admin prestador y Superadmin; opcional para el resto | ✅ | `core/security.py`, `services/auth_service.py` | `test_auth.py`, `test_seguridad.py::test_totp_no_se_reutiliza` |
| Política de contraseñas | Mínimo 10 caracteres con complejidad, historial de 10, vencimiento de 90 días para administradores | ✅ | `core/security.py::validar_contrasena`, tabla `historial_contrasenas`, `core/dependencias.py` | `test_seguridad.py::test_politica_de_contrasena` y `::test_contrasena_vencida_bloquea_todo_menos_el_cambio` |
| Cifrado en reposo | AES-256 en columnas sensibles y archivos del Object Storage **con llaves por tenant** | ✅ | `core/security.py` (`cifrar`, `cifrar_archivo`, `clave_por_dueno`), `services/almacenamiento.py` | `test_seguridad.py::test_los_archivos_se_guardan_cifrados_con_llave_por_dueno` |
| Gestión de sesiones | JWT de 8 h (2 h administradores), refresh rotativo, cierre por inactividad | ✅ | `services/auth_service.py`, `core/cookies.py` | `test_seguridad.py::test_vida_de_la_sesion_por_rol` y `::test_sesion_expirada_y_cierre_por_inactividad` |
| Recuperación ante desastres | Respaldo diario a otra región, RTO < 4 h, RPO < 1 h, prueba trimestral | ⚙️ | `scripts/respaldo.sh`, `scripts/restaurar.sh`, `docs/operacion/recuperacion_desastres.md` | restauración medida y documentada; la *otra región* y la prueba trimestral son 🏢 |
| Gestión de vulnerabilidades | Escaneo de dependencias, análisis estático, parchado en 72 h de lo crítico | ⚙️ / 🗓️ | `pip-audit` y `npm audit`, documentados en la sección 5 | sin vulnerabilidades conocidas en el backend; el análisis estático y el plazo de parchado son Fase 2 |

## 2. Registro inmutable de eventos (§6.9.5)

La norma exige saber quién accedió, a qué, desde dónde y cuándo, sin posibilidad de alterar el registro.

| Categoría | Eventos | Dato adicional | Estado | Prueba |
|---|---|---|---|---|
| Autenticación | Login correcto y fallido, cierre de sesión, cambio y restablecimiento de contraseña | IP, user agent, geolocalización aproximada, timestamp | ✅ | `test_seguridad.py::test_auditoria_de_login_guarda_ip_y_geolocalizacion` |
| Acceso a datos sensibles | Consulta de costos, descarga de reportes, detalle de folio cerrado | Tabla, id del registro y número de registros devueltos | ✅ | `test_seguridad.py::test_auditoria_de_acceso_a_datos_sensibles` |
| Modificaciones críticas | Usuarios, roles, SLA y configuración | Valor anterior y valor nuevo | ✅ | `test_auditoria.py` |
| Operaciones de inventario | Movimientos sobre umbral, aprobación de caja chica, generación de OC | Monto, artículo, cantidad, quién aprobó | ✅ | `test_inventario.py`, `test_caja_chica.py`, `test_ordenes_compra.py` |
| Accesos a la API | Cada llamada REST con ruta, método, código y duración | Para detectar patrones anómalos | ✅ | `test_auditoria.py`, `test_seguridad.py::test_retencion_de_la_bitacora_de_api` |

**Inmutabilidad.** `audit_log`, `audit_accesos_api` y `audit_accesos_api_errores` son append-only por trigger de base
de datos (`acma_auditoria_inmutable`): ningún rol las modifica ni las borra, tampoco el dueño del esquema. Comprobado
en `test_seguridad.py::test_la_bitacora_de_api_no_se_puede_modificar`.

**Retención.** Las llamadas normales se conservan 90 días; los errores 4xx/5xx, un año. La purga suelta particiones
completas (`DETACH` + `DROP`), nunca `DELETE`, para no tocar filas de auditoría: función `acma_purgar_accesos_api()`,
tarea `acma.purgar_accesos_api` a las 03:50. `audit_log`, que guarda los eventos de negocio y de seguridad, no se
purga.

## 3. Control de acceso (Anexo A 5.15–5.18, 8.2–8.5)

| Control | Implementación en ACMA | Estado | Prueba |
|---|---|---|---|
| Aislamiento entre clientes | RLS *fail-closed* en todas las tablas con `tenant_id`/`prestador_id`, con `FORCE ROW LEVEL SECURITY`: sin contexto no se ve nada | ✅ | `test_rls.py`, `test_acceso_cruzado.py` |
| Verificación doble | Además de la RLS, cada servicio valida el dueño del recurso | ✅ | `test_acceso_cruzado.py::test_ningun_recurso_ajeno_responde_200` barre las 44+ rutas GET de la app con usuarios de otro cliente y de otro prestador |
| Privilegio mínimo en la base | La API corre con el rol `acma_api`, sin `BYPASSRLS`; las migraciones usan `acma_owner` | ✅ | `docker/postgres/01_roles.sh`; las pruebas usan `acma_api` igual que producción |
| Permisos por rol y por usuario | 16 roles, permisos por módulo, overrides por técnico y permisos de mesa de control | ✅ | `test_permisos_roles.py` |
| Bloqueo de fuerza bruta | 5 intentos en 10 minutos bloquean al usuario y a la IP, con aviso al administrador | ✅ | `test_seguridad.py::test_bloqueo_de_ip_avisa_al_administrador` |
| Altas y bajas | Un usuario inactivo pierde la sesión en su siguiente petición; cambiarle el rol invalida sus tokens | ✅ | `core/dependencias.py::usuario_actual`, `test_auth.py` |

## 4. Criptografía y comunicaciones (Anexo A 8.20–8.24)

| Control | Implementación | Estado |
|---|---|---|
| Cifrado en tránsito | TLS lo termina Caddy con certificado automático; HSTS de dos años, solo en producción | ⚙️ `docs/operacion/despliegue.md` |
| Cifrado de columnas sensibles | AES-256-GCM en el secreto TOTP y en los datos fiscales del prestador | ✅ |
| Cifrado de archivos | AES-256-GCM con llave derivada por HKDF para cada dueño; la ruta del objeto va firmada, así que un archivo no se puede mover al expediente de otro cliente | ✅ |
| Cifrado del disco | Volúmenes de PostgreSQL y MinIO sobre almacenamiento cifrado del proveedor | 🏢 es una opción del servidor contratado; `docs/operacion/despliegue.md` explica cómo verificarlo |
| Custodia de llaves | `CLAVE_CIFRADO` y `JWT_SECRETO` se generan con `scripts/generar_secretos.py` y viven solo en el gestor de secretos del cliente; el backend se niega a arrancar con valores de ejemplo | ✅ / 🏢 el gestor de secretos lo elige el cliente |
| Cabeceras del navegador | CSP `default-src 'none'`, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, COOP y CORP; `Cache-Control: no-store` en toda la API | ✅ `test_seguridad.py::test_cabeceras_de_seguridad_de_la_api` |
| CSRF | El refresh vive en cookie `httpOnly` con ruta limitada a `/api/auth` y `SameSite=Strict`, más doble envío con la cabecera `X-ACMA-CSRF` | ✅ `test_auth.py::test_sesion_en_cookie_httponly_y_csrf` |
| CORS | Solo los orígenes configurados; el comodín está prohibido en producción | ✅ `test_seguridad.py::test_cors_acepta_la_cabecera_csrf_y_solo_los_origenes_configurados` |

## 5. Gestión de vulnerabilidades (Anexo A 8.8)

Auditoría ejecutada el **5 de noviembre de 2026**:

```bash
cd backend && .venv/Scripts/python -m pip_audit
```

```bash
cd frontend && npm audit
```

- **Backend:** `No known vulnerabilities found` sobre todas las dependencias instaladas.
- **Frontend:** 10 avisos al empezar (3 bajos, 7 moderados, ninguno alto ni crítico). `npm audit fix` dejó 6, todos de
  la cadena de construcción (`vite-plugin-pwa` → `workbox-build` → `glob`, `minimatch`, `deepmerge`): no viajan en el
  paquete que recibe el navegador. El arreglo que propone npm es *bajar* `vite-plugin-pwa` de 2.x a 1.1.0, un
  retroceso de versión que cambiaría el generador del service worker; no se aplica y queda como riesgo aceptado hasta
  que `vite-plugin-pwa` publique una 2.x con la cadena actualizada.
- **Imágenes de contenedor** fijadas por versión exacta o digest en `docker-compose.yml`, para que ningún `pull`
  cambie la versión por debajo. Subirla es un cambio explícito y commiteado.

Pendiente de Fase 2 según el diseño: análisis estático de código y el compromiso de parchar lo crítico en 72 horas.

## 6. Restricciones duras del negocio (§6.7)

No las pide la norma, pero se verifican igual porque protegen la integridad del expediente:

| Restricción | Cómo se garantiza | Prueba |
|---|---|---|
| La evidencia de una orden cerrada es inmutable por 5 años | Trigger `acma_evidencia_folio_inmutable` sobre `folio_evidencias`: con el folio cerrado o cancelado no hay `UPDATE`, `DELETE` ni `TRUNCATE`, ni siquiera desde la base de datos | `test_seguridad.py::test_la_evidencia_de_un_folio_cerrado_no_se_puede_borrar` |
| El fondo de caja chica nunca queda negativo | Validación en el servicio antes de registrar el gasto | `test_seguridad.py::test_el_fondo_de_caja_chica_nunca_queda_negativo` |
| Sellos de fecha y geolocalización no editables por el usuario | El servidor los fija; un ajuste declarado se audita y respeta el radio permitido | `test_seguridad.py::test_el_sello_de_fecha_y_la_geolocalizacion_no_son_editables` |
| 50 técnicos en simultáneo, escalable a 500+ | Medido con las pruebas de carga | `docs/rendimiento/resultados.md` |

## 7. Lo que queda fuera del software

| Tema | Por qué depende del cliente |
|---|---|
| Respaldo en otra región | Hay que contratar el destino (otro servidor u otro almacenamiento S3) y definir quién custodia esa copia |
| Prueba trimestral de restauración | Es un procedimiento con responsable y calendario; el guion está en `docs/operacion/recuperacion_desastres.md` |
| Gestor de secretos | ACMA lee variables de entorno; de dónde salen las decide el cliente |
| Cifrado del disco | Es una opción del servidor o del proveedor de nube |
| Certificación formal | Requiere el sistema de gestión documental completo (políticas, responsables, formación, auditoría interna), que es un proyecto aparte del software |

> ACMA cubre los controles técnicos que la certificación exige del sistema. La certificación la obtiene la
> organización, no el software.
