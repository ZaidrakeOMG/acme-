"""Contexto de Row Level Security.

Las políticas de PostgreSQL leen `app.usuario_id`, `app.tenant_id`,
`app.prestador_id` y `app.rol`. Si están vacíos, ninguna política devuelve filas
(fail-closed). El rol `sistema` lo usan Celery y los scripts; las políticas lo
tratan igual que `superadmin`.
"""
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.orm import Session

ROL_SISTEMA = "sistema"

_SQL_CONTEXTO = text(
    "SELECT set_config('app.usuario_id', :usuario_id, true),"
    " set_config('app.tenant_id', :tenant_id, true),"
    " set_config('app.prestador_id', :prestador_id, true),"
    " set_config('app.rol', :rol, true)"
)


@dataclass(frozen=True)
class ContextoRLS:
    usuario_id: UUID | None = None
    tenant_id: UUID | None = None
    prestador_id: UUID | None = None
    rol: str | None = None
    extra: dict = field(default_factory=dict, compare=False)

    def parametros(self) -> dict[str, str]:
        return {
            "usuario_id": str(self.usuario_id) if self.usuario_id else "",
            "tenant_id": str(self.tenant_id) if self.tenant_id else "",
            "prestador_id": str(self.prestador_id) if self.prestador_id else "",
            "rol": self.rol or "",
        }


CONTEXTO_SISTEMA = ContextoRLS(rol=ROL_SISTEMA)


class SesionRLS(Session):
    """Sesión síncrona subyacente de las AsyncSession de ACMA."""


@event.listens_for(SesionRLS, "after_begin")
def _aplicar_contexto(sesion, _transaccion, conexion) -> None:
    contexto: ContextoRLS = sesion.info.get("rls") or ContextoRLS()
    conexion.execute(_SQL_CONTEXTO, contexto.parametros())


async def fijar_contexto(sesion, contexto: ContextoRLS) -> None:
    """Cambia el contexto de la sesión y lo aplica de inmediato a la transacción en curso."""
    sesion.info["rls"] = contexto
    await sesion.execute(_SQL_CONTEXTO, contexto.parametros())
