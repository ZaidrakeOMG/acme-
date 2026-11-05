"""0012 — Índices que faltaban para los listados de folios, encontrados midiendo carga (ACT-1.6). P11a.

El listado de folios siempre ordena por `capturado_at DESC` con `LIMIT`, y los índices de P01 solo cubrían
`(tenant_id, estado)` y `(prestador_id, estado)`. El plan real era `Seq Scan` + `top-N heapsort` sobre todos los
folios del cliente para devolver 50: con 1,433 folios son 14 ms, pero crece lineal y es la consulta más llamada de
la aplicación (listados de oficina, bandeja del técnico y sincronización).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-05
"""
from core.sql_migracion import ex

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

INDICES = [
    # Alcance por cliente (Admin empresa, Admin UN, operador) + orden del listado.
    ("ix_folios_tenant_capturado", "folios (tenant_id, capturado_at DESC)"),
    # Alcance por prestador (mesa de control, despachador, dirección).
    ("ix_folios_prestador_capturado", "folios (prestador_id, capturado_at DESC)"),
    # Bandeja del técnico: §5 lo limita a sus folios y la app de campo la consulta en cada sincronización.
    ("ix_folios_tecnico_capturado", "folios (tecnico_id, capturado_at DESC)"),
]


def upgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    for nombre, definicion in INDICES:
        ex(f"CREATE INDEX IF NOT EXISTS {nombre} ON {definicion};")
    # El planeador necesita estadísticas frescas para preferir los índices nuevos.
    ex("ANALYZE folios;")


def downgrade() -> None:
    ex("SELECT set_config('app.rol', 'sistema', true);")
    for nombre, _ in INDICES:
        ex(f"DROP INDEX IF EXISTS {nombre};")
