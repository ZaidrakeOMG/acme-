"""Prepara los datos que necesitan las pruebas de carga (ACT-1.6, §6.7: 50 técnicos simultáneos).

Es idempotente: se puede correr varias veces. Crea, usando la API real (no SQL directo):
  - `tecnicos` técnicos de carga con su ficha y habilidades heredadas del grupo del prestador,
  - una bolsa de equipos sin folio abierto para que el operador pueda capturar sin choques de duplicado,
  - un folio asignado a cada técnico de carga, para que su sincronización traiga trabajo de verdad.

Deja `datos_carga.json` junto a este archivo; `locustfile.py` lo lee al arrancar.

Uso (con la API de desarrollo levantada en http://localhost:8000):
    cd backend
    .venv/Scripts/python -m pruebas_carga.preparar --tecnicos 50 --equipos 300
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

import httpx

AQUI = Path(__file__).resolve().parent
SALIDA = AQUI / "datos_carga.json"
CONTRASENA = "Carga#Acma2026"
CONTRASENA_DEMO = "Demo#Acma2026"
SUPERADMIN = "superadmin@acma.dev"
ADMIN_PRESTADOR = "admin.prestador@acma.dev"
ADMIN_EMPRESA = "admin.empresa@acma.dev"
DESPACHADOR = "despachador@acma.dev"
OPERADOR = "operador@acma.dev"
# Usuarios de oficina del seed que navegan listados, detalle, minuta y tableros.
OFICINA = [ADMIN_EMPRESA, ADMIN_PRESTADOR, "mesa.control@acma.dev", DESPACHADOR, "direccion@acma.dev",
           "supervisor.prestador@acma.dev", "admin.un@acma.dev", "supervisor.operadores@acma.dev"]


class Api:
    """Cliente mínimo con sesión iniciada. Si el entorno exige MFA, avisa y se detiene: la carga se mide en
    desarrollo, donde MFA_OBLIGATORIO es false."""

    def __init__(self, base: str, email: str, contrasena: str) -> None:
        self.cliente = httpx.Client(base_url=base, timeout=60.0)
        r = self.cliente.post("/api/auth/login", json={"email": email, "contrasena": contrasena})
        r.raise_for_status()
        cuerpo = r.json()
        if not cuerpo.get("tokens"):
            sys.exit(f"{email} exige MFA. Pon MFA_OBLIGATORIO=false en el .env para medir carga y vuelve a intentar.")
        self.cliente.headers["Authorization"] = f"Bearer {cuerpo['tokens']['access_token']}"

    def get(self, ruta: str, **params):
        r = self.cliente.get(ruta, params=params or None)
        r.raise_for_status()
        return r.json()

    def post(self, ruta: str, cuerpo: dict, *, aceptar=(200, 201)):
        r = self.cliente.post(ruta, json=cuerpo)
        if r.status_code not in aceptar:
            raise RuntimeError(f"POST {ruta} -> {r.status_code}: {r.text[:300]}")
        return r.json()


def crear_tecnicos(prestador: Api, cuantos: int) -> list[str]:
    """Devuelve los correos de los técnicos de carga, creando los que falten.

    Se les certifican todas las habilidades del prestador: la asignación tiene restricción dura de habilidad por
    familia del equipo (§6.8.6) y sin ellas el despachador no podría darles trabajo.
    """
    habilidades = [{"habilidad_id": h["id"], "certificada": True, "fecha_certificacion": "2026-01-15",
                    "vigencia_hasta": "2028-01-15"} for h in prestador.get("/api/catalogos/habilidades")]
    existentes = {t["email"]: t for t in prestador.get("/api/catalogos/tecnicos", limite=1000) if t.get("email")}
    correos = []
    for i in range(1, cuantos + 1):
        email = f"carga.tecnico{i:03d}@acma.dev"
        ficha = existentes.get(email)
        if ficha is None:
            ficha = prestador.post("/api/catalogos/tecnicos", {
                "email": email, "nombre": f"Técnico de carga {i:03d}", "contrasena": CONTRASENA,
                "numero_empleado": f"C-{i:03d}", "telefono": f"5590000{i:03d}",
            })
        if habilidades and len(ficha.get("habilidades") or []) < len(habilidades):
            r = prestador.cliente.put(f"/api/catalogos/tecnicos/{ficha['id']}/habilidades",
                                      json={"habilidades": habilidades})
            r.raise_for_status()
        correos.append(email)
    return correos


def crear_equipos(empresa: Api, cuantos: int) -> list[dict]:
    """Bolsa de equipos para la captura del operador. Reutiliza los que ya existan con el prefijo de carga.

    Cada equipo se devuelve con su familia: el tipo de falla tiene que pertenecer a la familia del equipo
    (§6.8.6 valida la combinación), así que la carga elige la falla a partir de ella.
    """
    unidades = empresa.get("/api/unidades-negocio")
    tipos = empresa.get("/api/catalogos/tipos-equipo")
    assert unidades and tipos, "el seed de desarrollo debe estar aplicado"
    familia_de = {t["id"]: t["familia_id"] for t in tipos}
    equipos = [e for e in empresa.get("/api/catalogos/equipos") if e["codigo"].startswith("CARGA-")]
    while len(equipos) < cuantos:
        un = unidades[len(equipos) % len(unidades)]
        tipo = tipos[len(equipos) % len(tipos)]
        codigo = f"CARGA-{uuid.uuid4().hex[:8].upper()}"
        equipos.append(empresa.post("/api/catalogos/equipos", {
            "un_id": un["id"], "tipo_equipo_id": tipo["id"], "codigo": codigo, "nombre": f"Equipo de carga {codigo}",
        }))
    return [{"id": e["id"], "un_id": e["un_id"], "familia_id": familia_de.get(e["tipo_equipo_id"])}
            for e in equipos[:cuantos]]


def asignar_trabajo(empresa: Api, despacho: Api, equipos: list[dict], correos: list[str]) -> None:
    """Un folio asignado por técnico de carga, para que `/api/sync/catalogos` traiga trabajo real.

    Con las reglas de aprobación del seed el folio nace en `en_revision` y el despachador no puede asignarlo, así que
    las reglas se apagan mientras se crean estos folios y se vuelven a poner al terminar (igual que las pruebas).
    """
    # `POST /folios/{id}/asignar` espera el id del usuario del técnico, no el de su ficha.
    tecnicos = {t["email"]: t["usuario_id"] for t in despacho.get("/api/catalogos/tecnicos", limite=1000)
                if t.get("email")}
    fallas = empresa.get("/api/catalogos/tipos-falla")
    por_familia: dict[str, list[dict]] = {}
    for f in fallas:
        if not f.get("requiere_revision_manual"):  # con revisión manual el folio no llega a `autorizado`
            por_familia.setdefault(f["familia_equipo_id"], []).append(f)
    asignados = {f.get("tecnico_id") for f in despacho.get("/api/folios", limite=500)}
    libres = [e for e in equipos if por_familia.get(e.get("familia_id"))]
    reglas = [{k: r[k] for k in ("nivel", "criterio", "operador", "valor_json", "activa")}
              for r in empresa.get("/api/folios/aprobacion/configuracion")["reglas"]]
    empresa.cliente.put("/api/folios/aprobacion/reglas", json=[]).raise_for_status()
    try:
        _crear_y_asignar(empresa, despacho, correos, tecnicos, por_familia, libres, asignados)
    finally:
        empresa.cliente.put("/api/folios/aprobacion/reglas", json=reglas).raise_for_status()
        print(f"  reglas de aprobación restauradas ({len(reglas)})")


def _crear_y_asignar(empresa: Api, despacho: Api, correos, tecnicos, por_familia, libres, asignados) -> None:
    fallidos = 0
    for email in correos:
        tid = tecnicos.get(email)
        if tid is None or tid in asignados or not libres:
            continue
        # Un equipo con folio abierto responde 409/422 por la regla de duplicado: se prueba con el siguiente.
        folio = None
        while libres and folio is None:
            equipo = libres.pop()
            falla = por_familia[equipo["familia_id"]][0]
            r = empresa.cliente.post("/api/folios", json={
                "un_id": equipo["un_id"], "equipo_id": equipo["id"], "tipo_falla_id": falla["id"],
                "descripcion": f"Folio de preparación de carga para {email}", "confirmacion_un": True,
                "confirmacion_un_geolat": 19.4326, "confirmacion_un_geolng": -99.1332,
                "geolat_captura": 19.4326, "geolng_captura": -99.1332,
            })
            if r.status_code == 201:
                folio = r.json()
            elif r.status_code not in (409, 422):
                raise RuntimeError(f"POST /api/folios -> {r.status_code}: {r.text[:300]}")
        if folio is None:
            print("  se agotaron los equipos libres antes de asignar a todos los técnicos")
            return
        try:
            # §6.8.6 manda a revisión por ocho causas (sin contrato, severidad sin configurar, garantía, horario…);
            # el despachador la resuelve con `autorizar` y después sí se puede asignar.
            if folio.get("estado") == "en_revision":
                despacho.post(f"/api/folios/{folio['id']}/autorizar",
                              {"notas": "Preparación de la prueba de carga"})
            despacho.post(f"/api/folios/{folio['id']}/asignar", {"tecnico_id": tid})
        except RuntimeError as e:
            fallidos += 1
            if fallidos <= 3:  # con el primer puñado se entiende el motivo; el resto solo hace ruido
                print(f"  aviso: no se pudo asignar el folio de {email}: {e}")
    if fallidos:
        print(f"  {fallidos} de {len(correos)} técnicos quedaron sin folio asignado")


def main() -> None:
    p = argparse.ArgumentParser(description="Prepara los datos de las pruebas de carga de ACMA")
    p.add_argument("--base", default="http://localhost:8000")
    p.add_argument("--tecnicos", type=int, default=50)
    p.add_argument("--equipos", type=int, default=300, help="bolsa para la captura del operador (una por folio nuevo)")
    p.add_argument("--sin-asignar", action="store_true", help="no crear el folio asignado por técnico")
    args = p.parse_args()

    prestador = Api(args.base, ADMIN_PRESTADOR, CONTRASENA_DEMO)
    empresa = Api(args.base, ADMIN_EMPRESA, CONTRASENA_DEMO)
    despacho = Api(args.base, DESPACHADOR, CONTRASENA_DEMO)

    print(f"Creando/verificando {args.tecnicos} técnicos de carga…")
    correos = crear_tecnicos(prestador, args.tecnicos)
    print(f"Creando/verificando {args.equipos} equipos para la captura…")
    equipos = crear_equipos(empresa, args.equipos)
    if not args.sin_asignar:
        print("Asignando un folio por técnico de carga…")
        asignar_trabajo(empresa, despacho, list(equipos), correos)

    SALIDA.write_text(json.dumps({
        "base": args.base,
        "contrasena_carga": CONTRASENA,
        "contrasena_demo": CONTRASENA_DEMO,
        "tecnicos": correos,
        "oficina": OFICINA,
        "operador": OPERADOR,
        "equipos": equipos,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Listo. {len(correos)} técnicos y {len(equipos)} equipos en {SALIDA}")


if __name__ == "__main__":
    main()
