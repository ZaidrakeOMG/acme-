# ACMA: estado de la BD Supabase previa a unificar la web

Fuente: `acme-.rar` original (18 migraciones) y resultados de consultas SQL compartidos por el usuario. **La nueva base Supabase no está conectada todavía en este entorno**, por lo que se trata de una revisión estática + evidencias aportadas; no de una prueba de integración real.

## Inventario comprobado

- Tablas y particiones en el Supabase del usuario: **201** = 178 tablas principales + 23 particiones.
- Alembic registra **0018**.
- RLS: **412 políticas** (413 CREATE en SQL V3 menos una política anterior eliminada), 176 tablas con RLS.
- Funciones: **33**; se revisaron por separado los 14 casos `SECURITY DEFINER` y sus `search_path=acma, extensions, pg_temp`.
- Roles: `acma_api` no omite RLS; los roles `anon` y `authenticated` no tienen USAGE al esquema `acma`.
- El catálogo cerrado `eventos_trigger_catalogo` tiene 5 entradas, lectura de `acma_api` pero no escritura.
- Hay cero usuarios de ACMA registrados.

Del SQL V3 extraído del RAR: 181 tablas nombradas directamente, más las 20 particiones temporales creadas por funciones; 114 tipos ENUM, 337 índices explícitos, 187 nombres únicos de triggers, 412 políticas finales, 175 tablas con FORCE RLS, 126 constraints nombradas y 2.520 columnas definidas en CREATE TABLE/ALTER TABLE ADD COLUMN. Comparación por AST: los **175 modelos SQLAlchemy** y sus **1.358 campos** nombrados están incluidos en el SQL V3 (cero faltantes **en comparación estática**).

## Pendientes para declarar 100 % la BD

1. Verificar en la nueva base nombres exactos de índices, triggers, ENUM, constraints, columnas y RLS mediante consultas de solo lectura. No repetir el SQL V3.
2. Confirmar `acma_api` LOGIN efectivo con TLS y contraseña privada. **V3 no asigna contraseñas** deliberadamente; public URL y publishable key no reemplazan el DSN de PostgreSQL.
3. Crear un primer `superadmin` real mediante `backend/scripts/bootstrap_superadmin.py`, sin ejecutar `seed_dev.py` en producción.
4. Comprobar bucket **privado** `acma` en Storage, respaldos/restauración y retención de particiones.
5. Probar en FastAPI autenticación+MFA, queries con RLS como usuarios de tenants diferentes, API/WS, formularios, evidencias, reportes, Celery Worker y Beat, chat y offline. Los jobs necesitan Redis externo o migración equivalente probada.
6. Auditar los permisos de funciones `SECURITY DEFINER` (`acma_api` recibió EXECUTE en todas las funciones de `acma` en el SQL V3; contrastar necesidad real y restringir con cuidado, sin romper los jobs).

## Web unificada

- React se conserva visual y funcionalmente; FastAPI la sirve como SPA en el mismo host y mantiene routers y WebSockets.
- SQLAlchemy usa `DB_SCHEMA=acma` para consultas a la base Supabase sin exponer el esquema a la REST API pública.
- `backend/scripts/preflight_supabase.py` comprueba rol `acma_api` y `search_path` antes del arranque.
- El usuario de la API no tiene permiso para leer `alembic_version`, por eso la comprobación de migración 0018 se hace desde SQL Editor, no con el rol de la web.

**No declarar migración ni aplicaciones móviles completas hasta probarlas contra el proyecto real.**
