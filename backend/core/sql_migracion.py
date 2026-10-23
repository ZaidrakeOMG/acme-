"""Utilidades para migraciones Alembic con SQL explícito (desde 0002; 0001 conserva su copia)."""
from alembic import op


def lit(v) -> str:
    """Literal SQL seguro para datos semilla escritos en la migración."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def sentencias(sql: str) -> list[str]:
    """Divide un bloque SQL en sentencias respetando cadenas, cuerpos $$...$$ y comentarios (asyncpg ejecuta una a la vez)."""
    partes, actual, i, en_comillas, en_dolar = [], [], 0, False, False
    while i < len(sql):
        if not en_comillas and sql.startswith("$$", i):
            en_dolar = not en_dolar
            actual.append("$$")
            i += 2
            continue
        c = sql[i]
        if c == "-" and sql.startswith("--", i) and not en_comillas and not en_dolar:
            fin = sql.find("\n", i)
            i = len(sql) if fin == -1 else fin
            continue
        if c == "'" and not en_dolar:
            en_comillas = not en_comillas
        if c == ";" and not en_comillas and not en_dolar:
            partes.append("".join(actual).strip())
            actual = []
        else:
            actual.append(c)
        i += 1
    partes.append("".join(actual).strip())
    return [p for p in partes if p]


def ex(sql: str) -> None:
    for sentencia in sentencias(sql):
        op.execute(sentencia)


def rls(tabla: str, *politicas: str) -> None:
    ex(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY; ALTER TABLE {tabla} FORCE ROW LEVEL SECURITY;")
    for p in politicas:
        ex(p)


def versionar(*tablas: str) -> None:
    """Índice en updated_at y trigger acma_version() (§6.2 capa 1)."""
    for t in tablas:
        ex(f"CREATE INDEX ix_{t}_updated_at ON {t} (updated_at);")
        ex(f"CREATE TRIGGER trg_{t}_version BEFORE INSERT OR UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION acma_version();")


def politicas_tenant(t: str) -> tuple[str, str]:
    return (
        f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_tenant_visible(tenant_id));",
        f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING (acma_es_plataforma() OR tenant_id = acma_ctx_tenant())"
        f" WITH CHECK (acma_es_plataforma() OR tenant_id = acma_ctx_tenant());",
    )


def politicas_prestador(t: str, lectura_tenants: bool = False) -> tuple[str, ...]:
    """Escritura solo del prestador; con lectura_tenants, los tenants que atiende también leen."""
    escritura = (f"CREATE POLICY {t}_escritura ON {t} FOR ALL USING (acma_es_plataforma() OR prestador_id = acma_ctx_prestador())"
                 f" WITH CHECK (acma_es_plataforma() OR prestador_id = acma_ctx_prestador());")
    if not lectura_tenants:
        return (escritura,)
    return (f"CREATE POLICY {t}_lectura ON {t} FOR SELECT USING (acma_prestador_visible(prestador_id));", escritura)
