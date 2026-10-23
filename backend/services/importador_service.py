"""Importador de catálogos desde CSV/Excel (§6.3, ACT-1.3): vista previa → confirmar o cancelar.

Cada catálogo define columnas, validación por fila (con los catálogos existentes cargados una vez) y cómo aplicar
las filas válidas. Los duplicados contra la base se reportan y se omiten; los duplicados dentro del archivo son error.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from geoalchemy2 import WKTElement
from openpyxl import Workbook, load_workbook
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ErrorAPI
from core.security import errores_politica_contrasena, hashear_contrasena
from models.base import Dominio, Rol
from models.catalogos import (
    Equipo, FamiliaEquipo, Habilidad, NivelSeveridadCatalogo, Tecnico, TecnicoHabilidad, TipoEquipo, TipoFalla,
    TipoFallaSeveridad,
)
from models.unidades import GrupoUN, GrupoUNMiembro, UnidadNegocio
from models.usuarios import Usuario

MAX_FILAS = 10_000
MAX_BYTES = 15_000_000


@dataclass
class Columna:
    nombre: str
    requerida: bool = False
    descripcion: str = ""
    ejemplo: str = ""


@dataclass
class Catalogo:
    clave: str
    nombre: str
    dominio: Dominio  # tenant o prestador: quién lo importa
    columnas: list[Columna]
    claves_unicas: tuple[str, ...]  # columnas que identifican la fila (duplicados)


CATALOGOS: dict[str, Catalogo] = {
    "tecnicos": Catalogo("tecnicos", "Técnicos", Dominio.prestador, [
        Columna("email", True, "Correo del técnico (será su usuario)", "juan.perez@prestador.com"),
        Columna("nombre", True, "Nombre completo", "Juan Pérez"),
        Columna("contrasena", True, "Contraseña inicial (10+ caracteres, mayúscula, minúscula, número y símbolo)", "Inicial#2026"),
        Columna("numero_empleado", False, "Número de empleado", "T-015"),
        Columna("telefono", False, "Teléfono", "5512345678"),
        Columna("vehiculo_placas", False, "Placas del vehículo", "ABC-123-D"),
        Columna("fecha_ingreso", False, "Fecha de ingreso (AAAA-MM-DD)", "2026-01-15"),
        Columna("habilidades", False, "Claves de habilidades separadas por ;", "refrigeracion;electricidad"),
    ], ("email",)),
    "unidades_negocio": Catalogo("unidades_negocio", "Unidades de negocio", Dominio.tenant, [
        Columna("codigo", True, "Código único de la UN", "SUC-010"),
        Columna("nombre", True, "Nombre", "Sucursal Norte"),
        Columna("direccion", False, "Dirección", "Av. Norte 10, Monterrey"),
        Columna("lat", False, "Latitud", "25.6866"),
        Columna("lng", False, "Longitud", "-100.3161"),
        Columna("zona_horaria", False, "Zona horaria IANA", "America/Monterrey"),
        Columna("grupo", False, "Nombre del grupo de UNs (debe existir)", "Zona Norte"),
    ], ("codigo",)),
    "severidades": Catalogo("severidades", "Niveles de severidad", Dominio.prestador, [
        Columna("clave", True, "muy_baja, baja, media, alta o critica", "critica"),
        Columna("nombre", False, "Nombre visible", "Crítica"),
        Columna("color_hex", False, "Color #RRGGBB", "#D32F2F"),
        Columna("tiempo_respuesta_horas", False, "1 a 4320", "2"),
        Columna("tiempo_resolucion_horas", False, "1 a 4320", "8"),
    ], ("clave",)),
    "familias_equipo": Catalogo("familias_equipo", "Familias de equipo", Dominio.tenant, [
        Columna("nombre", True, "Nombre de la familia", "Refrigeración"),
        Columna("descripcion", False, "Descripción", "Equipos de frío comercial"),
    ], ("nombre",)),
    "tipos_equipo": Catalogo("tipos_equipo", "Tipos de equipo", Dominio.tenant, [
        Columna("familia", True, "Nombre de la familia (global o propia)", "Refrigeración"),
        Columna("nombre", True, "Nombre del tipo", "Cámara de congelación"),
        Columna("descripcion", False, "Descripción", ""),
    ], ("familia", "nombre")),
    "tipos_falla": Catalogo("tipos_falla", "Tipos de falla", Dominio.prestador, [
        Columna("descripcion", True, "Síntoma técnico", "No enciende"),
        Columna("familia", True, "Nombre de la familia global", "Refrigeración"),
    ], ("familia", "descripcion")),
    "equipos": Catalogo("equipos", "Equipos", Dominio.tenant, [
        Columna("codigo", True, "Código único del equipo", "EQ-0001"),
        Columna("nombre", True, "Nombre", "Refrigerador vitrina 1"),
        Columna("un_codigo", True, "Código de la UN", "SUC-001"),
        Columna("familia", True, "Familia del tipo de equipo", "Refrigeración"),
        Columna("tipo_equipo", True, "Tipo de equipo", "Refrigerador vertical"),
        Columna("marca", False, "Marca", "Torrey"),
        Columna("modelo", False, "Modelo", "RV-32"),
        Columna("numero_serie", False, "Número de serie", "SN123456"),
        Columna("fecha_instalacion", False, "AAAA-MM-DD", "2024-05-10"),
        Columna("valor_reposicion", False, "Monto", "45000"),
        Columna("garantia_vigente_hasta", False, "AAAA-MM-DD", "2027-05-10"),
    ], ("codigo",)),
    "matriz_severidad": Catalogo("matriz_severidad", "Matriz de severidad", Dominio.tenant, [
        Columna("tipo_falla", True, "Descripción del tipo de falla", "No enciende"),
        Columna("tipo_equipo", True, "Nombre del tipo de equipo", "Refrigerador vertical"),
        Columna("severidad", True, "Clave del nivel: muy_baja, baja, media, alta, critica", "critica"),
    ], ("tipo_falla", "tipo_equipo")),
}


@dataclass
class Resultado:
    columnas: list[str]
    validas: list[dict[str, Any]] = field(default_factory=list)
    errores: list[dict[str, Any]] = field(default_factory=list)
    duplicados: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0


# ------------------------------------------------------------------ lectura

def _normalizar(nombre: str) -> str:
    n = nombre.strip().lower()
    return re.sub(r"[^a-z0-9_]", "_", n.translate(str.maketrans("áéíóúñ", "aeioun")))


def leer_archivo(nombre: str, contenido: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """Devuelve (columnas, filas como dict de texto). Soporta .csv (utf-8/latin-1) y .xlsx."""
    if len(contenido) > MAX_BYTES:
        raise ErrorAPI(413, "ARCHIVO_DEMASIADO_GRANDE", "El archivo no puede exceder 15 MB")
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if extension in ("xlsx", "xlsm"):
        libro = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
        hoja = libro.worksheets[0]
        filas_crudas = [list(f) for f in hoja.iter_rows(values_only=True)]
        libro.close()
    elif extension == "csv":
        texto = contenido.decode("utf-8-sig") if _es_utf8(contenido) else contenido.decode("latin-1")
        try:
            dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t|")
        except csv.Error:
            dialecto = csv.excel
        filas_crudas = list(csv.reader(io.StringIO(texto), dialecto))
    else:
        raise ErrorAPI(422, "FORMATO_NO_SOPORTADO", "Sube un archivo .csv o .xlsx")
    filas_crudas = [f for f in filas_crudas if any(c not in (None, "") for c in f)]
    if not filas_crudas:
        raise ErrorAPI(422, "ARCHIVO_VACIO", "El archivo no tiene datos")
    columnas = [_normalizar(str(c or "")) for c in filas_crudas[0]]
    if len(filas_crudas) - 1 > MAX_FILAS:
        raise ErrorAPI(422, "DEMASIADAS_FILAS", f"Máximo {MAX_FILAS:,} filas por importación")
    filas = []
    for cruda in filas_crudas[1:]:
        fila = {}
        for i, col in enumerate(columnas):
            if not col:
                continue
            valor = cruda[i] if i < len(cruda) else None
            if isinstance(valor, (datetime, date)):
                valor = valor.date().isoformat() if isinstance(valor, datetime) else valor.isoformat()
            elif isinstance(valor, float) and valor.is_integer():
                valor = str(int(valor))
            fila[col] = "" if valor is None else str(valor).strip()
        filas.append(fila)
    return columnas, filas


def _es_utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def plantilla_xlsx(catalogo: Catalogo) -> bytes:
    libro = Workbook()
    hoja = libro.active
    hoja.title = catalogo.nombre[:30]
    hoja.append([c.nombre for c in catalogo.columnas])
    hoja.append([c.ejemplo for c in catalogo.columnas])
    ayuda = libro.create_sheet("Instrucciones")
    ayuda.append(["Columna", "Obligatoria", "Descripción"])
    for c in catalogo.columnas:
        ayuda.append([c.nombre, "Sí" if c.requerida else "No", c.descripcion])
    for h in (hoja, ayuda):
        for col in h.columns:
            h.column_dimensions[col[0].column_letter].width = 28
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


# -------------------------------------------------------------- validación

def _fecha(v: str) -> date | None:
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(v[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError("Fecha inválida; usa AAAA-MM-DD")


def _decimal(v: str) -> Decimal | None:
    if not v:
        return None
    try:
        d = Decimal(v.replace(",", "").replace("$", ""))
    except InvalidOperation:
        raise ValueError("Número inválido")
    if d < 0:
        raise ValueError("No puede ser negativo")
    return d


def _entero(v: str, minimo: int, maximo: int) -> int | None:
    if not v:
        return None
    try:
        n = int(float(v))
    except ValueError:
        raise ValueError("Número entero inválido")
    if not minimo <= n <= maximo:
        raise ValueError(f"Debe estar entre {minimo} y {maximo}")
    return n


def _flotante(v: str, minimo: float, maximo: float) -> float | None:
    if not v:
        return None
    try:
        f = float(v)
    except ValueError:
        raise ValueError("Número inválido")
    if not minimo <= f <= maximo:
        raise ValueError(f"Debe estar entre {minimo} y {maximo}")
    return f


class Contexto:
    """Catálogos existentes, cargados una vez por importación, para validar referencias y duplicados."""

    def __init__(self, db: AsyncSession, tenant_id: UUID | None, prestador_id: UUID | None):
        self.db, self.tenant_id, self.prestador_id = db, tenant_id, prestador_id
        self.d: dict[str, Any] = {}

    async def cargar(self, catalogo: str) -> None:
        db, t, p = self.db, self.tenant_id, self.prestador_id
        if catalogo == "tecnicos":
            self.d["emails"] = {e.lower() for e in (await db.execute(select(Usuario.email))).scalars()}
            self.d["habilidades"] = {h.clave: h.id for h in (await db.execute(
                select(Habilidad).where(Habilidad.prestador_id == p))).scalars()}
        if catalogo in ("unidades_negocio", "equipos"):
            self.d["unidades"] = {u.codigo.lower(): u.id for u in (await db.execute(
                select(UnidadNegocio).where(UnidadNegocio.tenant_id == t))).scalars()}
        if catalogo == "unidades_negocio":
            self.d["grupos"] = {g.nombre.lower(): g.id for g in (await db.execute(
                select(GrupoUN).where(GrupoUN.tenant_id == t))).scalars()}
        if catalogo == "severidades":
            self.d["niveles"] = {n.clave: n.id for n in (await db.execute(
                select(NivelSeveridadCatalogo).where(NivelSeveridadCatalogo.prestador_id == p))).scalars()}
        if catalogo in ("familias_equipo", "tipos_equipo", "tipos_falla", "equipos"):
            familias = (await db.execute(select(FamiliaEquipo).where(
                or_(FamiliaEquipo.tenant_id.is_(None), FamiliaEquipo.tenant_id == t) if t else FamiliaEquipo.tenant_id.is_(None)
            ))).scalars().all()
            self.d["familias"] = {f.nombre.lower(): f for f in familias}
        if catalogo in ("tipos_equipo", "equipos", "matriz_severidad"):
            tipos = (await db.execute(select(TipoEquipo).where(
                or_(TipoEquipo.tenant_id.is_(None), TipoEquipo.tenant_id == t)))).scalars().all()
            self.d["tipos"] = {(x.familia_id, x.nombre.lower()): x for x in tipos}
            self.d["tipos_por_nombre"] = {x.nombre.lower(): x for x in tipos}
        if catalogo == "tipos_falla":
            self.d["fallas"] = {(f.familia_equipo_id, f.descripcion.lower()) for f in (await db.execute(
                select(TipoFalla).where(TipoFalla.prestador_id == p))).scalars()}
        if catalogo == "equipos":
            self.d["codigos_equipo"] = {c.lower() for c in (await db.execute(
                select(Equipo.codigo).where(Equipo.tenant_id == t))).scalars()}
        if catalogo == "matriz_severidad":
            from services.catalogos_service import prestadores_del_tenant
            prestadores = await prestadores_del_tenant(db, t)
            self.d["fallas_por_desc"] = {}
            for f in (await db.execute(select(TipoFalla).where(
                    TipoFalla.prestador_id.in_(prestadores), TipoFalla.activa.is_(True)))).scalars():
                self.d["fallas_por_desc"].setdefault(f.descripcion.lower(), []).append(f)
            self.d["niveles_por_prestador"] = {}
            for n in (await db.execute(select(NivelSeveridadCatalogo).where(
                    NivelSeveridadCatalogo.prestador_id.in_(prestadores)))).scalars():
                self.d["niveles_por_prestador"].setdefault(n.prestador_id, {})[n.clave] = n.id
            self.d["celdas"] = {(c.tipo_falla_id, c.tipo_equipo_id) for c in (await db.execute(
                select(TipoFallaSeveridad).where(TipoFallaSeveridad.tenant_id == t))).scalars()}


def _validar_fila(catalogo: str, f: dict[str, str], ctx: Contexto) -> tuple[dict[str, Any] | None, bool, list[tuple[str, str]]]:
    """Devuelve (fila normalizada, es_duplicado_en_bd, errores[(columna, motivo)])."""
    errores: list[tuple[str, str]] = []
    n: dict[str, Any] = {}
    d = ctx.d

    def campo(col: str, conv=None, **kw):
        try:
            n[col] = conv(f.get(col, ""), **kw) if conv else (f.get(col, "") or None)
        except ValueError as e:
            errores.append((col, str(e)))

    if catalogo == "tecnicos":
        email = f.get("email", "").lower()
        n["email"], n["nombre"] = email, f.get("nombre", "")
        if "@" not in email or "." not in email.split("@")[-1]:
            errores.append(("email", "Correo inválido"))
        politica = errores_politica_contrasena(f.get("contrasena", ""))
        if politica:
            errores.append(("contrasena", "; ".join(politica)))
        n["contrasena"] = f.get("contrasena", "")
        for col in ("numero_empleado", "telefono", "vehiculo_placas"):
            campo(col)
        campo("fecha_ingreso", _fecha)
        claves = [c.strip() for c in f.get("habilidades", "").split(";") if c.strip()]
        desconocidas = [c for c in claves if c not in d["habilidades"]]
        if desconocidas:
            errores.append(("habilidades", f"Habilidades inexistentes: {', '.join(desconocidas)}"))
        n["habilidades"] = claves
        return (n, email in d["emails"], errores)

    if catalogo == "unidades_negocio":
        n["codigo"], n["nombre"], n["direccion"] = f.get("codigo", ""), f.get("nombre", ""), f.get("direccion", "")
        campo("lat", _flotante, minimo=-90, maximo=90)
        campo("lng", _flotante, minimo=-180, maximo=180)
        if (n.get("lat") is None) != (n.get("lng") is None):
            errores.append(("lat", "Latitud y longitud van juntas"))
        n["zona_horaria"] = f.get("zona_horaria") or "America/Mexico_City"
        grupo = f.get("grupo", "").lower()
        n["grupo_id"] = None
        if grupo:
            if grupo not in d["grupos"]:
                errores.append(("grupo", f"El grupo «{f['grupo']}» no existe"))
            else:
                n["grupo_id"] = str(d["grupos"][grupo])
        return (n, n["codigo"].lower() in d["unidades"], errores)

    if catalogo == "severidades":
        clave = f.get("clave", "").lower()
        if clave not in d["niveles"]:
            errores.append(("clave", "Clave inválida; usa muy_baja, baja, media, alta o critica"))
        n["clave"], n["nombre"] = clave, f.get("nombre") or None
        color = f.get("color_hex", "")
        if color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            errores.append(("color_hex", "Color inválido; usa #RRGGBB"))
        n["color_hex"] = color or None
        campo("tiempo_respuesta_horas", _entero, minimo=1, maximo=4320)
        campo("tiempo_resolucion_horas", _entero, minimo=1, maximo=4320)
        return (n, False, errores)  # las severidades siempre existen: la importación las actualiza

    if catalogo == "familias_equipo":
        n["nombre"], n["descripcion"] = f.get("nombre", ""), f.get("descripcion", "")
        return (n, n["nombre"].lower() in d["familias"], errores)

    if catalogo == "tipos_equipo":
        fam = d["familias"].get(f.get("familia", "").lower())
        if fam is None:
            errores.append(("familia", f"La familia «{f.get('familia', '')}» no existe"))
        n["familia_id"] = str(fam.id) if fam else None
        n["nombre"], n["descripcion"] = f.get("nombre", ""), f.get("descripcion", "")
        return (n, bool(fam) and (fam.id, n["nombre"].lower()) in d["tipos"], errores)

    if catalogo == "tipos_falla":
        fam = d["familias"].get(f.get("familia", "").lower())
        if fam is None or fam.tenant_id is not None:
            errores.append(("familia", f"La familia global «{f.get('familia', '')}» no existe"))
        n["familia_equipo_id"] = str(fam.id) if fam else None
        n["descripcion"] = f.get("descripcion", "")
        return (n, bool(fam) and (fam.id, n["descripcion"].lower()) in d["fallas"], errores)

    if catalogo == "equipos":
        n["codigo"], n["nombre"] = f.get("codigo", ""), f.get("nombre", "")
        un = d["unidades"].get(f.get("un_codigo", "").lower())
        if un is None:
            errores.append(("un_codigo", f"La UN «{f.get('un_codigo', '')}» no existe"))
        n["un_id"] = str(un) if un else None
        fam = d["familias"].get(f.get("familia", "").lower())
        tipo = d["tipos"].get((fam.id, f.get("tipo_equipo", "").lower())) if fam else None
        if fam is None:
            errores.append(("familia", f"La familia «{f.get('familia', '')}» no existe"))
        elif tipo is None:
            errores.append(("tipo_equipo", f"El tipo «{f.get('tipo_equipo', '')}» no existe en la familia «{fam.nombre}»"))
        n["tipo_equipo_id"] = str(tipo.id) if tipo else None
        for col in ("marca", "modelo", "numero_serie"):
            campo(col)
        campo("fecha_instalacion", _fecha)
        campo("valor_reposicion", _decimal)
        campo("garantia_vigente_hasta", _fecha)
        for col in ("fecha_instalacion", "garantia_vigente_hasta", "valor_reposicion"):
            if n.get(col) is not None:
                n[col] = str(n[col])
        return (n, n["codigo"].lower() in d["codigos_equipo"], errores)

    if catalogo == "matriz_severidad":
        candidatas = d["fallas_por_desc"].get(f.get("tipo_falla", "").lower(), [])
        tipo = d["tipos_por_nombre"].get(f.get("tipo_equipo", "").lower())
        # La misma descripción puede existir en varias familias: se elige la de la familia del tipo de equipo.
        falla = next((c for c in candidatas if tipo and c.familia_equipo_id == tipo.familia_id), None)
        if not candidatas:
            errores.append(("tipo_falla", f"El tipo de falla «{f.get('tipo_falla', '')}» no existe"))
        if tipo is None:
            errores.append(("tipo_equipo", f"El tipo de equipo «{f.get('tipo_equipo', '')}» no existe"))
        elif candidatas and falla is None:
            errores.append(("tipo_equipo", "El tipo de falla y el tipo de equipo son de familias distintas"))
        nivel = None
        if falla:
            nivel = d["niveles_por_prestador"].get(falla.prestador_id, {}).get(f.get("severidad", "").lower())
            if nivel is None:
                errores.append(("severidad", "Clave inválida; usa muy_baja, baja, media, alta o critica"))
        n["tipo_falla_id"] = str(falla.id) if falla else None
        n["tipo_equipo_id"] = str(tipo.id) if tipo else None
        n["nivel_severidad_id"] = str(nivel) if nivel else None
        n["_etiqueta"] = f"{f.get('tipo_falla', '')} × {f.get('tipo_equipo', '')}"
        return (n, False, errores)  # las celdas existentes se actualizan

    raise ErrorAPI(404, "CATALOGO_DESCONOCIDO", f"Catálogo {catalogo} no soportado")


async def validar(db: AsyncSession, catalogo: Catalogo, columnas: list[str], filas: list[dict[str, str]],
                  tenant_id: UUID | None, prestador_id: UUID | None) -> Resultado:
    faltantes = [c.nombre for c in catalogo.columnas if c.requerida and c.nombre not in columnas]
    if faltantes:
        raise ErrorAPI(422, "COLUMNAS_FALTANTES", "Faltan columnas obligatorias", faltantes)
    ctx = Contexto(db, tenant_id, prestador_id)
    await ctx.cargar(catalogo.clave)
    r = Resultado(columnas=columnas, total=len(filas))
    vistas: set[tuple[str, ...]] = set()
    for i, fila in enumerate(filas, start=2):  # fila 1 = encabezados
        errores = [(c.nombre, "Obligatoria") for c in catalogo.columnas if c.requerida and not fila.get(c.nombre)]
        normalizada, duplicado_bd, mas = (None, False, []) if errores else _validar_fila(catalogo.clave, fila, ctx)
        errores += mas
        llave = tuple(fila.get(c, "").lower() for c in catalogo.claves_unicas)
        if not errores and llave in vistas:
            errores.append((catalogo.claves_unicas[0], "Fila repetida dentro del archivo"))
        vistas.add(llave)
        if errores:
            r.errores += [{"fila": i, "columna": col, "motivo": motivo} for col, motivo in errores]
        elif duplicado_bd:
            r.duplicados.append({"fila": i, "columna": catalogo.claves_unicas[0], "motivo": "Ya existe en ACMA; se omite"})
        else:
            r.validas.append({"_fila": i, **normalizada})
    return r


# --------------------------------------------------------------- aplicación

async def aplicar(db: AsyncSession, catalogo: str, filas: list[dict[str, Any]], tenant_id: UUID | None,
                  prestador_id: UUID | None, actor_id: UUID) -> dict[str, int]:
    creados = actualizados = 0
    if catalogo == "tecnicos":
        habilidades = {h.clave: h.id for h in (await db.execute(select(Habilidad).where(Habilidad.prestador_id == prestador_id))).scalars()}
        for f in filas:
            u = Usuario(email=f["email"], nombre=f["nombre"], telefono=f.get("telefono"), rol=Rol.tecnico, dominio=Dominio.prestador,
                        prestador_id=prestador_id, password_hash=hashear_contrasena(f["contrasena"]))
            db.add(u)
            await db.flush()
            t = Tecnico(prestador_id=prestador_id, usuario_id=u.id, numero_empleado=f.get("numero_empleado"), telefono=f.get("telefono"),
                        vehiculo_placas=f.get("vehiculo_placas"), fecha_ingreso=_fecha(f.get("fecha_ingreso") or ""))
            db.add(t)
            await db.flush()
            for clave in f.get("habilidades", []):
                db.add(TecnicoHabilidad(prestador_id=prestador_id, tecnico_id=t.id, habilidad_id=habilidades[clave], certificada=True))
            creados += 1
    elif catalogo == "unidades_negocio":
        for f in filas:
            ubic = WKTElement(f"POINT({f['lng']} {f['lat']})", srid=4326) if f.get("lat") is not None else None
            un = UnidadNegocio(tenant_id=tenant_id, codigo=f["codigo"], nombre=f["nombre"], direccion=f.get("direccion") or "",
                               ubicacion=ubic, zona_horaria=f["zona_horaria"], grupo_id=UUID(f["grupo_id"]) if f.get("grupo_id") else None)
            db.add(un)
            await db.flush()
            if un.grupo_id:
                db.add(GrupoUNMiembro(tenant_id=tenant_id, grupo_id=un.grupo_id, unidad_id=un.id))
            creados += 1
    elif catalogo == "severidades":
        niveles = {n.clave: n for n in (await db.execute(select(NivelSeveridadCatalogo).where(
            NivelSeveridadCatalogo.prestador_id == prestador_id))).scalars()}
        for f in filas:
            n = niveles[f["clave"]]
            for col in ("nombre", "color_hex", "tiempo_respuesta_horas", "tiempo_resolucion_horas"):
                if f.get(col) is not None:
                    setattr(n, col, f[col])
            if n.tiempo_resolucion_horas < n.tiempo_respuesta_horas:
                n.tiempo_resolucion_horas = n.tiempo_respuesta_horas
            actualizados += 1
    elif catalogo == "familias_equipo":
        for f in filas:
            db.add(FamiliaEquipo(tenant_id=tenant_id, nombre=f["nombre"], descripcion=f.get("descripcion") or ""))
            creados += 1
    elif catalogo == "tipos_equipo":
        for f in filas:
            db.add(TipoEquipo(tenant_id=tenant_id, familia_id=UUID(f["familia_id"]), nombre=f["nombre"], descripcion=f.get("descripcion") or ""))
            creados += 1
    elif catalogo == "tipos_falla":
        for f in filas:
            db.add(TipoFalla(prestador_id=prestador_id, descripcion=f["descripcion"], familia_equipo_id=UUID(f["familia_equipo_id"])))
            creados += 1
    elif catalogo == "equipos":
        for f in filas:
            db.add(Equipo(tenant_id=tenant_id, un_id=UUID(f["un_id"]), tipo_equipo_id=UUID(f["tipo_equipo_id"]), codigo=f["codigo"],
                          nombre=f["nombre"], marca=f.get("marca"), modelo=f.get("modelo"), numero_serie=f.get("numero_serie"),
                          fecha_instalacion=_fecha(f.get("fecha_instalacion") or ""),
                          valor_reposicion=Decimal(f["valor_reposicion"]) if f.get("valor_reposicion") else None,
                          garantia_vigente_hasta=_fecha(f.get("garantia_vigente_hasta") or "")))
            creados += 1
    elif catalogo == "matriz_severidad":
        existentes = {(c.tipo_falla_id, c.tipo_equipo_id): c for c in (await db.execute(
            select(TipoFallaSeveridad).where(TipoFallaSeveridad.tenant_id == tenant_id))).scalars()}
        for f in filas:
            llave = (UUID(f["tipo_falla_id"]), UUID(f["tipo_equipo_id"]))
            celda = existentes.get(llave)
            if celda is None:
                celda = TipoFallaSeveridad(tenant_id=tenant_id, tipo_falla_id=llave[0], tipo_equipo_id=llave[1])
                db.add(celda)
                existentes[llave] = celda
                creados += 1
            else:
                actualizados += 1
            celda.nivel_severidad_id, celda.configurado_por, celda.activa = UUID(f["nivel_severidad_id"]), actor_id, True
    await db.flush()
    return {"creados": creados, "actualizados": actualizados}

