"""Restricción de módulos por usuario. Nunca eleva permisos establecidos en los routers."""
from core.errors import ErrorAPI

MODULOS_VALIDOS = frozenset({
    "usuarios", "tenants", "prestadores", "unidades", "contratos", "alertas",
    "capacitacion", "auditoria", "catalogos", "formularios", "mis_formularios",
    "biblioteca", "operaciones", "folios", "app_campo", "preventivos",
    "reasignaciones", "minuta", "seguimiento", "clasificacion", "notificaciones",
    "mensajeria", "trabajos_especiales", "oc_activos", "inventario",
    "caja_chica", "presupuestos", "activos", "medidores", "rutas",
    "iso55000", "erp", "sla", "bi",
})

# Rutas de API por módulo; /api/auth y rutas personales siempre están disponibles.
_PREFIJOS = (
    ("/api/usuarios/me/", None),
    ("/api/usuarios", "usuarios"),
    ("/api/tenants", "tenants"),
    ("/api/prestadores", "prestadores"),
    ("/api/unidades-negocio", "unidades"),
    ("/api/grupos-un", "unidades"),
    ("/api/contratos", "contratos"),
    ("/api/alertas", "alertas"),
    ("/api/capacitacion", "capacitacion"),
    ("/api/auditoria", "auditoria"),
    ("/api/catalogos", "catalogos"),
    ("/api/formularios", "formularios"),
    ("/api/biblioteca", "biblioteca"),
    ("/api/operacion", "operaciones"),
    ("/api/folios", "folios"),
    ("/api/campo", "app_campo"),
    ("/api/preventivos", "preventivos"),
    ("/api/reasignaciones", "reasignaciones"),
    ("/api/minutas", "minuta"),
    ("/api/seguimiento", "seguimiento"),
    ("/api/clasificacion", "clasificacion"),
    ("/api/notificaciones", "notificaciones"),
    ("/api/mensajeria", "mensajeria"),
    ("/api/trabajos-especiales", "trabajos_especiales"),
    ("/api/oc-activos", "oc_activos"),
    ("/api/inventario", "inventario"),
    ("/api/caja-chica", "caja_chica"),
    ("/api/presupuestos", "presupuestos"),
    ("/api/activos", "activos"),
    ("/api/medidores", "medidores"),
    ("/api/rutas", "rutas"),
    ("/api/criticidad", "iso55000"),
    ("/api/erp", "erp"),
    ("/api/sla", "sla"),
    ("/api/bi", "bi"),
)


def modulo_de_ruta(ruta: str) -> str | None:
    for prefijo, modulo in _PREFIJOS:
        if ruta == prefijo or ruta.startswith(prefijo + "/") or (prefijo.endswith("/") and ruta.startswith(prefijo)):
            return modulo
    return None


def validar_modulos(modulos: list[str] | None) -> None:
    if modulos is None:
        return
    if set(modulos) - MODULOS_VALIDOS or len(set(modulos)) != len(modulos):
        raise ErrorAPI(422, "MODULOS_INVALIDOS", "La selección contiene módulos inválidos o duplicados")
