"""Datos de desarrollo: 1 prestador, 1 tenant, 3 UNs, 1 grupo, 1 contrato y 12 usuarios (los 11 roles).

Ejecutar desde backend/:  .venv\\Scripts\\python -m scripts.seed_dev
Es idempotente: si el prestador demo ya existe, no hace nada. Fija el contexto RLS 'sistema' explícitamente.
"""
import asyncio
from datetime import date

from geoalchemy2 import WKTElement
from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from core.security import hashear_contrasena
from models.base import ModalidadContrato, NivelSeveridad, Rol, dominio_de_rol
from models.contratos import Contrato, ContratoSLA
from models.organizaciones import Prestador, Tenant, TenantPrestador
from models.unidades import GrupoUN, GrupoUNMiembro, UnidadNegocio, UsuarioGrupo, UsuarioUN
from models.usuarios import Usuario
from services import permisos_service

# Solo desarrollo. MFA deshabilitado (MFA_OBLIGATORIO=false en .env de desarrollo).
CONTRASENA_DEMO = "Demo#Acma2026"

USUARIOS = [
    ("superadmin@acma.dev", "Sofía Plataforma", Rol.superadmin),
    ("admin.prestador@acma.dev", "Arturo Prestador", Rol.admin_prestador),
    ("direccion@acma.dev", "Diana Dirección", Rol.direccion_prestador),
    ("mesa.control@acma.dev", "Marco Mesa", Rol.mesa_control),
    ("despachador@acma.dev", "Daniel Despacho", Rol.despachador),
    ("supervisor.prestador@acma.dev", "Silvia Supervisión", Rol.supervisor_prestador),
    ("tecnico1@acma.dev", "Tomás Técnico", Rol.tecnico),
    ("tecnico2@acma.dev", "Teresa Técnica", Rol.tecnico),
    ("admin.empresa@acma.dev", "Elena Empresa", Rol.admin_empresa),
    ("admin.un@acma.dev", "Úrsula Unidad", Rol.admin_un),
    ("supervisor.operadores@acma.dev", "Óscar Supervisor", Rol.supervisor_operadores),
    ("operador@acma.dev", "Olga Operadora", Rol.operador),
]

UNIDADES = [
    ("SUC-001", "Sucursal Centro", "Av. Juárez 100, Centro, CDMX", 19.4326, -99.1332),
    ("SUC-002", "Sucursal Polanco", "Av. Presidente Masaryk 200, Polanco, CDMX", 19.4333, -99.1950),
    ("SUC-003", "Sucursal Coyoacán", "Av. Miguel Ángel de Quevedo 300, Coyoacán, CDMX", 19.3467, -99.1617),
]

SLAS = {  # severidad: (respuesta h, resolución h, penalización %)
    NivelSeveridad.critica: (2, 8, 10),
    NivelSeveridad.alta: (4, 24, 7),
    NivelSeveridad.media: (8, 72, 5),
    NivelSeveridad.baja: (24, 168, 3),
    NivelSeveridad.muy_baja: (72, 720, 1),
}


async def sembrar(db) -> bool:
    if (await db.execute(select(Prestador).where(Prestador.rfc == "PDE200101AB1"))).scalar_one_or_none():
        return False

    prestador = Prestador(razon_social="Prestador Demo", rfc="PDE200101AB1", pais="MX")
    tenant = Tenant(razon_social="Cliente Demo", rfc="CDE200101XY2", pais="MX", moneda="MXN")
    db.add_all([prestador, tenant])
    await db.flush()
    await permisos_service.sembrar_defaults(db, prestador.id)
    db.add(TenantPrestador(tenant_id=tenant.id, prestador_id=prestador.id, vigencia_inicio=date(2026, 1, 1)))

    grupo = GrupoUN(tenant_id=tenant.id, nombre="Zona Metropolitana", descripcion="Sucursales de la CDMX")
    db.add(grupo)
    await db.flush()

    unidades = []
    for codigo, nombre, direccion, lat, lng in UNIDADES:
        un = UnidadNegocio(tenant_id=tenant.id, codigo=codigo, nombre=nombre, direccion=direccion, grupo_id=grupo.id,
                           ubicacion=WKTElement(f"POINT({lng} {lat})", srid=4326))
        db.add(un)
        unidades.append(un)
    await db.flush()
    for un in unidades:
        db.add(GrupoUNMiembro(tenant_id=tenant.id, grupo_id=grupo.id, unidad_id=un.id))

    hash_demo = hashear_contrasena(CONTRASENA_DEMO)
    usuarios: dict[Rol, Usuario] = {}
    for email, nombre, rol in USUARIOS:
        dominio = dominio_de_rol(rol)
        u = Usuario(email=email, nombre=nombre, rol=rol, dominio=dominio, password_hash=hash_demo,
                    tenant_id=tenant.id if dominio.value == "tenant" else None,
                    prestador_id=prestador.id if dominio.value == "prestador" else None)
        db.add(u)
        usuarios.setdefault(rol, u)
    await db.flush()

    db.add(UsuarioUN(tenant_id=tenant.id, usuario_id=usuarios[Rol.operador].id, unidad_id=unidades[0].id))
    for un in unidades[:2]:
        db.add(UsuarioUN(tenant_id=tenant.id, usuario_id=usuarios[Rol.admin_un].id, unidad_id=un.id))
    db.add(UsuarioGrupo(tenant_id=tenant.id, usuario_id=usuarios[Rol.supervisor_operadores].id, grupo_id=grupo.id))
    grupo.responsable_id = usuarios[Rol.admin_empresa].id

    contrato = Contrato(tenant_id=tenant.id, prestador_id=prestador.id, nombre="Contrato de mantenimiento 2026",
                        modalidad=ModalidadContrato.evento, fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 12, 31),
                        penalizacion_tope_porcentaje=15, calificacion_json={"escala": "1-5", "minima_aceptable": 4})
    db.add(contrato)
    await db.flush()
    for nivel, (resp, resol, pen) in SLAS.items():
        db.add(ContratoSLA(tenant_id=tenant.id, prestador_id=prestador.id, contrato_id=contrato.id, nivel_severidad=nivel,
                           tiempo_respuesta_horas=resp, tiempo_resolucion_horas=resol, penalizacion_valor=pen))
    await db.commit()
    return True


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        creado = await sembrar(db)
    if creado:
        print("Datos demo creados. Contraseña de todos los usuarios:", CONTRASENA_DEMO)
        for email, _, rol in USUARIOS:
            print(f"  {rol.value:<24} {email}")
    else:
        print("Los datos demo ya existían; no se modificó nada.")


if __name__ == "__main__":
    asyncio.run(main())
