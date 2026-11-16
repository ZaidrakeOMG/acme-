// ACMA: Railway Infrastructure as Code (IaC 2026).
// Para la prueba gratuita: UN servicio (React + FastAPI), sin Redis ni workers de pago.
// Las claves se cargan en Railway Variables, NUNCA se versionan aquí.
// Revisar antes de ejecutar: railway config plan && railway config apply
import { defineRailway, github, preserve, project, service } from "railway/iac";

export default defineRailway(() => {
  const acmaWeb = service("acma-web", {
    source: github("ZaidrakeOMG/acme-", {
      branch: "main",
    }),
    healthcheck: "/api/salud",
    healthcheckTimeout: 300,
    replicas: 1,
    env: {
      ACMA_ENTORNO: "produccion",
      DB_SCHEMA: "acma",
      ALMACENAMIENTO_MODO: "supabase",
      SUPABASE_BUCKET: "acma",
      MFA_OBLIGATORIO: "true",
      UVICORN_WORKERS: "1",
      DB_POOL_SIZE: "3",
      DB_POOL_OVERFLOW: "2",
      LOG_JSON: "true",
      // Sin Redis en la prueba inicial. Chat en tiempo real queda limitado
      // al proceso único; Celery y notificaciones programadas NO están activos.
      TIEMPO_REAL_MODO: "local",
      NOTIFICACIONES_ENVIO_INLINE: "false",
      // La cuenta Railway debe tener estos valores privados en Variables.
      // preserve() impide escribir secretos reales en GitHub.
      DATABASE_URL: preserve(),
      SUPABASE_URL: preserve(),
      SUPABASE_SECRET_KEY: preserve(),
      JWT_SECRETO: preserve(),
      CLAVE_CIFRADO: preserve(),
      // Si el dominio fue generado por Railway, el arranque deduce
      // APP_URL_PUBLICA y CORS_ORIGENES de RAILWAY_PUBLIC_DOMAIN.
    },
  });

  return project("acma", { resources: [acmaWeb] });
});
