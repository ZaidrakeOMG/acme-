# ACMA — Gestión de mantenimiento

Proyecto de gestión de mantenimiento con **React + FastAPI + PostgreSQL/Supabase** y aplicación Android mediante **Flutter WebView**.

El repositorio contiene el código de la plataforma, sus migraciones, pruebas, los scripts necesarios para desarrollo y las instrucciones de despliegue. Los datos de producción permanecen en Supabase.

## Actualizar ACMA desde GitHub

En CMD o PowerShell, dentro de la carpeta de ACMA:

```bat
git status
git switch main
git pull --ff-only origin main
```

Si Git detecta cambios locales, revísalos antes de actualizar: no los descartes ni uses `git reset --hard` sobre información que quieras conservar.


## Probar la web local sin pedir claves de Supabase

El iniciador `PROBAR_ACMA_WEB.bat` NO pide la Secret API Key ni una cadena PostgreSQL.
Usa el archivo privado `.env` de la raíz. Si ese archivo no existe, busca
`.env.prueba.local` en la misma carpeta y lo copia una sola vez a `.env` sin
sobrescribir configuraciones existentes.

Si no encuentra ninguno de los dos, se detiene con instrucciones, **sin pedir
contraseñas por consola**. La configuración no se puede recuperar del repositorio:
las claves reales nunca se suben a GitHub. Puedes copiar `.env.supabase.example`
a `.env.prueba.local` y llenar tus valores **una sola vez**.

La revisión de `.env` durante el arranque es de solo lectura: no mueve, renombra
ni reemplaza el archivo ni pide confirmaciones. Si el esquema es incorrecto,
corrígelo manualmente con `DB_SCHEMA=acma`. El arranque todavía valida de forma
real PostgreSQL, los permisos del rol y el bucket privado de Supabase: **no evita
los errores de conexión**.

Para diagnosticar desde CMD sin modificar el archivo:

```bat
backend\.venv\Scripts\python.exe scripts\diagnosticar_env_supabase.py --solo-validar
```

Para arrancar:

```bat
PROBAR_ACMA_WEB.bat
```


## Web publicada

**Railway:** https://acme-production-ee493e67.up.railway.app/

**Salud de la API:** https://acme-production-ee493e67.up.railway.app/api/salud

Railway compila automáticamente los cambios de la rama `main` cuando está habilitado el despliegue desde GitHub. Las credenciales pertenecen a las variables privadas de Railway. Nunca subas `.env`, passwords, tokens JWT ni claves de Supabase a GitHub.

## Android Studio (abre ACMA con doble clic)

1. En **Android Studio → Device Manager** inicia un emulador Android.
2. En el Explorador de archivos de Windows, abre la carpeta raiz de ACMA.
3. Haz doble clic en **PROBAR_ACMA_FLUTTER_ANDROID.bat**.

El lanzador detecta el emulador, instala la app de prueba y la abre con el ACMA publicado en Railway. **No hace falta iniciar el backend local ni copiar claves de Supabase.**

Para probar con **FastAPI local** en lugar de Railway, primero inicia **PROBAR_ACMA_WEB.bat** y despues ejecuta desde CMD:

```bat
PROBAR_ACMA_FLUTTER_ANDROID.bat --local
```

Tambien puedes abrir `mobile_flutter` en Android Studio y ejecutar:

```powershell
flutter run --dart-define=ACMA_BASE_URL=https://acme-production-ee493e67.up.railway.app
```

La WebView carga las pantallas de React publicadas en Railway. Para cambiar el icono del launcher o codigo Flutter nativo hay que recompilar e instalar la aplicacion.

Se conserva `GENERAR_APK_ACMA_RAILWAY.bat` para APK y `GENERAR_AAB_ACMA_PLAYSTORE.bat` para Google Play. Ver [instrucciones de Android](mobile_flutter/README.md) y [despliegue de Android](docs/despliegue/RAILWAY_ANDROID.md).

## Scripts de Windows conservados

| Archivo | Uso |
|---|---|
| `PROBAR_ACMA_WEB.bat` | Iniciar y probar web + API local contra la configuración privada existente. |
| `PROBAR_ACMA_FLUTTER_ANDROID.bat` | Emulador conectado a Railway con doble clic; con `--local` usa backend local. |
| `GENERAR_APK_ACMA_RAILWAY.bat` | Crear APK de prueba para Railway. |
| `GENERAR_AAB_ACMA_PLAYSTORE.bat` | Compilar AAB con firma de publicación configurada. |
| `CREAR_ADMIN_ACMA.bat` | Configuración inicial de administrador, solo si hace falta. |

Los scripts de Docker, despliegue e infraestructura siguen en `deploy/` y las migraciones en `backend/alembic/`. No ejecutes migraciones de producción sin respaldo.

## Documentación técnica

- [Configuración Supabase](docs/supabase_pasos_acma.md)
- [Despliegue Railway Android](docs/despliegue/RAILWAY_ANDROID.md)
- [Google Play](docs/despliegue/PLAYSTORE_ANDROID.md)
- [Procedimientos de operación](docs/operacion/despliegue.md)
- [Seguridad](docs/seguridad/checklist_iso27001.md)

La función opcional de GPS de personal está en desarrollo separado; no queda habilitada por clonar o actualizar la rama `main`.
