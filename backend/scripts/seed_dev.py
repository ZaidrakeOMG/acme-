"""Datos de desarrollo: 1 prestador, 1 tenant, 3 UNs, 1 grupo, 1 contrato, 12 usuarios (los 11 roles) y, desde P02,
habilidades, técnicos, severidades, familias y tipos de equipo, equipos, tipos de falla y matriz de severidad;
desde P03, las 4 plantillas base de formularios, el catálogo «Causa raíz» y formularios demo publicados y asignados.

Ejecutar desde backend/:  .venv\\Scripts\\python -m scripts.seed_dev
Es idempotente: si el prestador demo ya existe, no hace nada. Fija el contexto RLS 'sistema' explícitamente.
"""
import asyncio
from datetime import UTC, date, datetime

from geoalchemy2 import WKTElement
from sqlalchemy import select

from core.rls import CONTEXTO_SISTEMA
from core.security import hashear_contrasena
from models.base import ModalidadContrato, NivelSeveridad, Rol, dominio_de_rol
from models.catalogos import (
    Equipo, FamiliaEquipo, Habilidad, NivelSeveridadCatalogo, Tecnico, TecnicoHabilidad, TipoEquipo, TipoFalla,
    TipoFallaSeveridad,
)
from models.contratos import Contrato, ContratoSLA
from models.formularios import (
    CatalogoPersonalizado, CatalogoPersonalizadoOpcion, EstadoFormulario, Formulario, FormularioAsignacion, FormularioVersion,
    TipoFormulario,
)
from models.organizaciones import Prestador, Tenant, TenantPrestador
from models.unidades import GrupoUN, GrupoUNMiembro, UnidadNegocio, UsuarioGrupo, UsuarioUN
from models.usuarios import Usuario
from schemas.formularios import EsquemaFormulario
from scripts.plantillas_formularios import CAPTURA_OPERADOR, CIERRE_CORRECTIVO, PLANTILLAS
from services import catalogos_service, permisos_service

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
    await catalogos_service.sembrar_niveles(db, prestador.id)
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
    niveles = {n.clave: n for n in (await db.execute(select(NivelSeveridadCatalogo).where(
        NivelSeveridadCatalogo.prestador_id == prestador.id))).scalars()}
    for nivel, (resp, resol, pen) in SLAS.items():
        db.add(ContratoSLA(tenant_id=tenant.id, prestador_id=prestador.id, contrato_id=contrato.id, nivel_severidad=nivel,
                           nivel_severidad_id=niveles[nivel.value].id, tiempo_respuesta_horas=resp,
                           tiempo_resolucion_horas=resol, penalizacion_valor=pen))
    await db.flush()
    await sembrar_catalogos(db, prestador, tenant, unidades, usuarios, niveles)
    await sembrar_formularios(db, prestador, tenant, usuarios)
    await db.flush()
    from scripts.seed_folios import sembrar_folios  # P04 (busca por sí mismo lo que necesita)
    await sembrar_folios(db)
    await db.flush()
    from scripts.seed_campo import sembrar_campo  # P05
    await sembrar_campo(db)
    await db.flush()
    from scripts.seed_preventivos import sembrar_preventivos  # P06
    await sembrar_preventivos(db)
    await db.commit()
    return True


# ----------------------------------------------------------------- P02

HABILIDADES = [
    ("refrigeracion", "Refrigeración comercial"), ("electricidad", "Electricidad"), ("hvac", "Aire acondicionado y HVAC"),
    ("plomeria", "Plomería"), ("iluminacion", "Iluminación"),
]
TECNICOS_NUEVOS = [("tecnico3@acma.dev", "Tadeo Técnico"), ("tecnico4@acma.dev", "Tania Técnica")]
HABILIDADES_POR_TECNICO = [["refrigeracion", "electricidad"], ["hvac", "electricidad"], ["plomeria"], ["iluminacion", "electricidad", "hvac"]]
FAMILIAS = {
    "Refrigeración": ["Refrigerador vertical", "Cámara de congelación"],
    "Climatización": ["Minisplit", "Aire acondicionado central"],
    "Iluminación": ["Lámpara LED de techo", "Anuncio luminoso"],
}
FALLAS = {
    "Refrigeración": ["No enciende", "No enfría", "Ruido inusual"],
    "Climatización": ["No enciende", "No enfría", "Gotea agua"],
    "Iluminación": ["No enciende", "Parpadea"],
}
# (familia, tipo de falla) -> severidad por tipo de equipo, en el orden de FAMILIAS
MATRIZ = {
    ("Refrigeración", "No enciende"): ["critica", "critica"],
    ("Refrigeración", "No enfría"): ["alta", "critica"],
    ("Refrigeración", "Ruido inusual"): ["baja", "media"],
    ("Climatización", "No enciende"): ["media", "alta"],
    ("Climatización", "No enfría"): ["media", "alta"],
    ("Climatización", "Gotea agua"): ["baja", "media"],
    ("Iluminación", "No enciende"): ["muy_baja", "baja"],
    ("Iluminación", "Parpadea"): ["muy_baja", "muy_baja"],
}
# 12 equipos = 4 por UN: 2 de refrigeración, 1 de climatización, 1 de iluminación.
EQUIPOS_POR_UN = [("Refrigeración", 0), ("Refrigeración", 1), ("Climatización", 0), ("Iluminación", 0)]
EQUIPOS_SIN_CONTRATO = {2, 6}  # apuntan a un contrato vencido
EQUIPO_EN_GARANTIA = 9


async def sembrar_catalogos(db, prestador, tenant, unidades, usuarios, niveles) -> None:
    habilidades = {}
    for clave, nombre in HABILIDADES:
        h = Habilidad(prestador_id=prestador.id, clave=clave, nombre=nombre)
        db.add(h)
        habilidades[clave] = h
    await db.flush()

    hash_demo = hashear_contrasena(CONTRASENA_DEMO)
    usuarios_tecnicos = list((await db.execute(select(Usuario).where(
        Usuario.prestador_id == prestador.id, Usuario.rol == Rol.tecnico).order_by(Usuario.email))).scalars())
    for email, nombre in TECNICOS_NUEVOS:
        u = Usuario(email=email, nombre=nombre, rol=Rol.tecnico, dominio=dominio_de_rol(Rol.tecnico),
                    prestador_id=prestador.id, password_hash=hash_demo)
        db.add(u)
        usuarios_tecnicos.append(u)
    await db.flush()
    for i, u in enumerate(usuarios_tecnicos):
        t = Tecnico(prestador_id=prestador.id, usuario_id=u.id, numero_empleado=f"T-{i + 1:03d}", telefono=f"55100000{i:02d}",
                    vehiculo_placas=f"ACM-{i + 1:03d}", fecha_ingreso=date(2025, 1 + i, 15))
        db.add(t)
        await db.flush()
        for clave in HABILIDADES_POR_TECNICO[i]:
            db.add(TecnicoHabilidad(prestador_id=prestador.id, tecnico_id=t.id, habilidad_id=habilidades[clave].id,
                                    certificada=True, fecha_certificacion=date(2025, 6, 1), vigencia_hasta=date(2027, 6, 1)))

    familias, tipos = {}, {}
    for nombre, lista in FAMILIAS.items():
        f = FamiliaEquipo(tenant_id=None, nombre=nombre)
        db.add(f)
        await db.flush()
        familias[nombre] = f
        tipos[nombre] = []
        for tn in lista:
            x = TipoEquipo(tenant_id=None, familia_id=f.id, nombre=tn)
            db.add(x)
            tipos[nombre].append(x)
    await db.flush()

    fallas = {}
    for familia, lista in FALLAS.items():
        for desc in lista:
            tf = TipoFalla(prestador_id=prestador.id, descripcion=desc, familia_equipo_id=familias[familia].id)
            db.add(tf)
            fallas[(familia, desc)] = tf
    await db.flush()

    vencido = Contrato(tenant_id=tenant.id, prestador_id=prestador.id, nombre="Contrato 2025 (vencido)",
                       modalidad=ModalidadContrato.evento, fecha_inicio=date(2025, 1, 1), fecha_fin=date(2025, 12, 31))
    db.add(vencido)
    await db.flush()
    n = 0
    for un in unidades:
        for familia, indice in EQUIPOS_POR_UN:
            n += 1
            tipo = tipos[familia][indice]
            e = Equipo(tenant_id=tenant.id, un_id=un.id, tipo_equipo_id=tipo.id, codigo=f"EQ-{n:04d}",
                       nombre=f"{tipo.nombre} {un.codigo}", marca="Genérica", modelo=f"M-{n}", numero_serie=f"SN{n:06d}",
                       fecha_instalacion=date(2024, 3, 1), valor_reposicion=25000 + n * 1000,
                       contrato_id=vencido.id if n in EQUIPOS_SIN_CONTRATO else None,
                       garantia_vigente_hasta=date(2028, 12, 31) if n == EQUIPO_EN_GARANTIA else None)
            db.add(e)
    await db.flush()

    for (familia, desc), severidades in MATRIZ.items():
        for tipo, clave in zip(tipos[familia], severidades):
            db.add(TipoFallaSeveridad(tenant_id=tenant.id, tipo_falla_id=fallas[(familia, desc)].id, tipo_equipo_id=tipo.id,
                                      nivel_severidad_id=niveles[clave].id, configurado_por=usuarios[Rol.admin_empresa].id))
    await db.flush()


async def main() -> None:
    from core.db import nueva_sesion

    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        creado = await sembrar(db)
    if creado:
        print("Datos demo creados. Contraseña de todos los usuarios:", CONTRASENA_DEMO)
        for email, _, rol in USUARIOS:
            print(f"  {rol.value:<24} {email}")
        for email, _ in TECNICOS_NUEVOS:
            print(f"  {'tecnico':<24} {email}")
    else:
        from scripts.seed_campo import sembrar_campo
        from scripts.seed_folios import sembrar_folios
        from scripts.seed_preventivos import sembrar_preventivos
        async with nueva_sesion(CONTEXTO_SISTEMA) as db:
            folios = await sembrar_folios(db)
            await db.flush()
            campo = await sembrar_campo(db)
            await db.flush()
            preventivos = await sembrar_preventivos(db)
            await db.commit()
        agregado = [n for n, ok in (("folios demo (P04)", folios), ("datos de campo (P05)", campo), ("preventivos (P06)", preventivos)) if ok]
        print("Los datos demo ya existían;", f"se agregaron: {', '.join(agregado)}." if agregado else "no se modificó nada.")



# ----------------------------------------------------------------- P03

CAUSAS_RAIZ = [
    ("desgaste", "Desgaste normal"), ("mal_uso", "Mal uso del equipo"), ("falta_mantenimiento", "Falta de mantenimiento"),
    ("falla_electrica", "Falla eléctrica externa"), ("instalacion_deficiente", "Instalación deficiente"), ("otro", "Otra causa"),
]


def _publicar(db, f: Formulario, v: FormularioVersion, publicada_por) -> None:
    v.publicada_at = datetime.now(UTC)
    v.publicada_por = publicada_por
    f.version_publicada_id = v.id
    f.estado = EstadoFormulario.publicado


async def _formulario(db, *, prestador_id, tenant_id, nombre, tipo, roles, esquema, descripcion="", plantilla=False, publicado_por=None,
                      clonado_de=None) -> Formulario:
    f = Formulario(prestador_id=prestador_id, tenant_id=tenant_id, nombre=nombre, descripcion=descripcion, tipo=TipoFormulario(tipo),
                   rol_destino=roles, es_plantilla_base=plantilla, clonado_de_id=clonado_de)
    db.add(f)
    await db.flush()
    v = FormularioVersion(formulario_id=f.id, prestador_id=prestador_id, tenant_id=tenant_id, numero_version=1,
                          esquema_json=EsquemaFormulario.model_validate(esquema).model_dump(mode="json"), notas_version="Versión inicial")
    db.add(v)
    await db.flush()
    _publicar(db, f, v, publicado_por)
    await db.flush()
    return f


def _con_catalogo(esquema: dict, catalogo_id) -> dict:
    """Sustituye el id de catálogo personalizado de la plantilla por el real del prestador."""
    import copy
    e = copy.deepcopy(esquema)
    for s in e["secciones"]:
        for c in s["campos"]:
            fuente = c.get("fuente_opciones") or {}
            if fuente.get("catalogo") == "catalogo_personalizado":
                fuente["catalogo_personalizado_id"] = str(catalogo_id)
    return e


async def sembrar_formularios(db, prestador, tenant, usuarios) -> None:
    superadmin = usuarios[Rol.superadmin]
    admin_prestador = usuarios[Rol.admin_prestador]
    plantillas = {}
    for p in PLANTILLAS:
        plantillas[p["nombre"]] = await _formulario(db, prestador_id=None, tenant_id=None, nombre=p["nombre"], tipo=p["tipo"],
                                                    roles=p["rol_destino"], esquema=p["esquema"], descripcion=p["descripcion"],
                                                    plantilla=True, publicado_por=superadmin.id)

    catalogo = CatalogoPersonalizado(prestador_id=prestador.id, tenant_id=tenant.id, nombre="Causa raíz", clave="causa_raiz")
    db.add(catalogo)
    await db.flush()
    for i, (valor, etiqueta) in enumerate(CAUSAS_RAIZ):
        db.add(CatalogoPersonalizadoOpcion(catalogo_id=catalogo.id, prestador_id=prestador.id, tenant_id=tenant.id, valor=valor,
                                           etiqueta=etiqueta, orden=i))
    await db.flush()

    refrigeracion = (await db.execute(select(FamiliaEquipo).where(FamiliaEquipo.nombre == "Refrigeración"))).scalar_one()
    captura = await _formulario(db, prestador_id=prestador.id, tenant_id=None, nombre="Captura de folio (operador)", tipo="captura_operador",
                                roles=["operador", "admin_un", "admin_empresa", "supervisor_operadores", "mesa_control"],
                                esquema=CAPTURA_OPERADOR, descripcion="Formulario de captura del operador", publicado_por=admin_prestador.id)
    atencion = await _formulario(db, prestador_id=prestador.id, tenant_id=None, nombre="Cierre de correctivo (global)", tipo="atencion_tecnico",
                                 roles=["tecnico"], esquema=_con_catalogo(CIERRE_CORRECTIVO, catalogo.id),
                                 descripcion="Reporte de atención del técnico", publicado_por=admin_prestador.id,
                                 clonado_de=plantillas["Cierre de correctivo"].id)
    especifico = await _formulario(db, prestador_id=prestador.id, tenant_id=tenant.id, nombre="Cierre de correctivo · Cliente Demo",
                                   tipo="atencion_tecnico", roles=["tecnico"], esquema=_con_catalogo(CIERRE_CORRECTIVO, catalogo.id),
                                   descripcion="Versión específica para Cliente Demo (prioridad sobre la global)",
                                   publicado_por=admin_prestador.id, clonado_de=atencion.id)
    db.add_all([
        FormularioAsignacion(formulario_id=captura.id, prestador_id=prestador.id, tenant_id=None, tipo_folio="correctivo",
                             familia_equipo_id=refrigeracion.id, prioridad=3),
        FormularioAsignacion(formulario_id=atencion.id, prestador_id=prestador.id, tenant_id=None, tipo_folio="correctivo",
                             familia_equipo_id=refrigeracion.id, prioridad=3),
        FormularioAsignacion(formulario_id=especifico.id, prestador_id=prestador.id, tenant_id=tenant.id, tipo_folio="correctivo",
                             familia_equipo_id=refrigeracion.id, prioridad=11),
    ])
    await db.flush()


if __name__ == "__main__":
    asyncio.run(main())
