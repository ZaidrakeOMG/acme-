"""Datos iniciales de PRODUCCIÓN: lo mínimo para que alguien pueda entrar y empezar a configurar. P11a.

Crea solo tres cosas:

1. **El superadmin inicial**, con la contraseña vencida a propósito: al entrar, ACMA le exige cambiarla antes de
   dejarlo hacer cualquier otra cosa (§6.9.5). La contraseña con la que se crea es temporal y de un solo uso.
2. **Las cuatro plantillas base de formularios** de §6.8.3c (cierre de correctivo, inspección preventiva,
   instalación de equipo y trabajo especial). Son de plataforma, no de ningún cliente: cada prestador las clona.
3. Opcionalmente, con `--familias-ejemplo`, un punto de partida de familias y tipos de equipo.

**No crea datos demo**: ni clientes, ni prestadores, ni unidades, ni equipos, ni folios. El catálogo de las 19
alertas y los roles de la base los dejan las migraciones; los niveles de severidad se siembran solos al crear cada
prestador desde la aplicación.

Uso (una sola vez, con la base ya migrada):

    docker compose -f docker-compose.prod.yml run --rm api python -m scripts.seed_produccion \\
        --email admin@cliente.com --nombre "Nombre Apellido"

Imprime la contraseña temporal UNA VEZ en la terminal. No se guarda en ningún archivo ni en el log.
"""
import argparse
import asyncio
import secrets
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from core.config import config
from core.db import nueva_sesion
from core.rls import CONTEXTO_SISTEMA
from core.security import hashear_contrasena
from models.base import Rol, dominio_de_rol
from models.catalogos import FamiliaEquipo, TipoEquipo
from models.formularios import EstadoFormulario, Formulario, FormularioVersion, TipoFormulario
from models.usuarios import Usuario
from schemas.formularios import EsquemaFormulario
from scripts.plantillas_formularios import PLANTILLAS

# Punto de partida, no datos demo: son las familias que el diseño usa como ejemplo y se activan solo si se piden.
FAMILIAS_EJEMPLO = {
    "Refrigeración": ["Refrigerador vertical", "Cámara de congelación"],
    "Climatización": ["Minisplit", "Aire acondicionado central"],
    "Iluminación": ["Lámpara LED de techo", "Anuncio luminoso"],
}


def contrasena_temporal() -> str:
    """Cumple la política de §6.9.5 (10+, mayúscula, minúscula, número y símbolo) y se cambia al primer acceso."""
    grupos = [
        "ABCDEFGHJKLMNPQRSTUVWXYZ",
        "abcdefghijkmnopqrstuvwxyz",
        "23456789",
        "!#$%&*+?",
    ]
    alfabeto = "".join(grupos)
    # Una letra de CADA clase: el generador previo podía omitir los números
    # por azar y producir contraseñas rechazadas en el primer cambio.
    caracteres = [secrets.choice(grupo) for grupo in grupos]
    caracteres += [secrets.choice(alfabeto) for _ in range(20)]
    # secrets.SystemRandom asegura una mezcla criptográficamente segura.
    secrets.SystemRandom().shuffle(caracteres)
    return "".join(caracteres)


async def crear_superadmin(db, email: str, nombre: str) -> str | None:
    """Devuelve la contraseña temporal, o None si el usuario ya existía."""
    existente = (await db.execute(select(Usuario).where(Usuario.email == email))).scalar_one_or_none()
    if existente is not None:
        print(f"  El usuario {email} ya existe: no se toca.")
        return None
    temporal = contrasena_temporal()
    db.add(Usuario(
        email=email, nombre=nombre, rol=Rol.superadmin, dominio=dominio_de_rol(Rol.superadmin),
        password_hash=hashear_contrasena(temporal),
        # Vencida desde su creación: §6.9.5 obliga a cambiarla antes de usar cualquier módulo.
        password_actualizado_at=datetime.now(UTC) - timedelta(days=config.contrasena_dias_admin + 1),
    ))
    return temporal


async def crear_plantillas(db, superadmin_id) -> int:
    """Las cuatro plantillas base de §6.8.3c, de plataforma (sin prestador ni cliente)."""
    ya = {f.nombre for f in (await db.execute(
        select(Formulario).where(Formulario.es_plantilla_base.is_(True)))).scalars()}
    creadas = 0
    for p in PLANTILLAS:
        if p["nombre"] in ya:
            continue
        f = Formulario(prestador_id=None, tenant_id=None, nombre=p["nombre"], descripcion=p["descripcion"],
                       tipo=TipoFormulario(p["tipo"]), rol_destino=p["rol_destino"], es_plantilla_base=True)
        db.add(f)
        await db.flush()
        v = FormularioVersion(
            formulario_id=f.id, prestador_id=None, tenant_id=None, numero_version=1,
            esquema_json=EsquemaFormulario.model_validate(p["esquema"]).model_dump(mode="json"),
            notas_version="Versión inicial", publicada_at=datetime.now(UTC), publicada_por=superadmin_id)
        db.add(v)
        await db.flush()
        f.version_publicada_id = v.id
        f.estado = EstadoFormulario.publicado
        creadas += 1
    return creadas


async def crear_familias(db) -> int:
    creadas = 0
    ya = {f.nombre for f in (await db.execute(
        select(FamiliaEquipo).where(FamiliaEquipo.tenant_id.is_(None)))).scalars()}
    for nombre, tipos in FAMILIAS_EJEMPLO.items():
        if nombre in ya:
            continue
        f = FamiliaEquipo(tenant_id=None, nombre=nombre)
        db.add(f)
        await db.flush()
        for t in tipos:
            db.add(TipoEquipo(tenant_id=None, familia_id=f.id, nombre=t))
        creadas += 1
    return creadas


async def sembrar(email: str, nombre: str, familias: bool) -> None:
    async with nueva_sesion(CONTEXTO_SISTEMA) as db:
        print("Sembrando los datos iniciales de producción…")
        temporal = await crear_superadmin(db, email, nombre)
        await db.flush()
        superadmin = (await db.execute(select(Usuario).where(Usuario.email == email))).scalar_one()
        plantillas = await crear_plantillas(db, superadmin.id)
        print(f"  Plantillas base creadas: {plantillas}")
        if familias:
            print(f"  Familias de equipo de ejemplo creadas: {await crear_familias(db)}")
        # F2-02: las plantillas de WhatsApp y SMS nacen en borrador; hay que someterlas a Meta antes de usarlas.
        from services.mensajeria.plantillas import sembrar_plantillas

        print(f"  Plantillas de WhatsApp y SMS creadas: {await sembrar_plantillas(db)}")
        await db.commit()

    print("\nListo.")
    if temporal:
        print("\n" + "=" * 72)
        print(f"  Usuario:            {email}")
        print(f"  Contrasena temporal: {temporal}")
        print("=" * 72)
        print("  Se muestra UNA sola vez y no queda en ningun archivo. ACMA exige cambiarla al entrar.")
        print("  Entregala por un canal seguro, nunca por correo junto con el usuario.\n")


def main() -> None:
    p = argparse.ArgumentParser(description="Datos iniciales de produccion de ACMA")
    p.add_argument("--email", required=True, help="correo del superadmin inicial")
    p.add_argument("--nombre", required=True, help="nombre completo del superadmin inicial")
    p.add_argument("--familias-ejemplo", action="store_true",
                   help="crea familias y tipos de equipo de ejemplo como punto de partida")
    args = p.parse_args()

    # El correo se valida con las mismas reglas que el login: un dominio reservado (.local, .test) crea un
    # superadmin que despues no puede entrar, y el error aparece hasta el primer dia de uso.
    from pydantic import TypeAdapter, ValidationError
    from pydantic.networks import EmailStr

    try:
        TypeAdapter(EmailStr).validate_python(args.email)
    except ValidationError as e:
        sys.exit(f"El correo «{args.email}» no sirve para iniciar sesion: {e.errors()[0]['msg']}")

    if not config.es_produccion:
        print(f"AVISO: el entorno es «{config.acma_entorno}», no «produccion». "
              "Para la base de desarrollo usa scripts.seed_dev.", file=sys.stderr)
    asyncio.run(sembrar(args.email, args.nombre, args.familias_ejemplo))


if __name__ == "__main__":
    main()
