import { useEffect, useState } from 'react'
import { Aviso, Boton, Insignia } from '../../../components/ui'
import { mensajeDeError } from '../../../services/api'
import { apoyoDeFolio, archivoDeManual } from '../../../services/capacitacion'
import { SinEspacio, guardarManual } from '../../../services/bibliotecaOffline'
import { baseLocal, type BibliotecaOffline } from '../../../services/db'
import type { ApoyoDeFolio, Manual, PuntoRevision } from '../../../types/capacitacion'
import { NOMBRE_CATEGORIA } from '../../../types/capacitacion'
import { tamanoArchivo as tamano } from '../../folios/comunes'

/**
 * Apoyo documental durante la atención (§6.10.4): los puntos de revisión que el contrato exige para ese tipo de
 * equipo y los manuales del equipo, que se pueden abrir en el momento o guardar en el teléfono.
 *
 * Sin señal la pantalla no se queda vacía: se usa lo que el dispositivo ya tenga descargado.
 */
export function ApoyoDelFolio({ folioId, enLinea }: { folioId: string; enLinea: boolean }) {
  const [apoyo, setApoyo] = useState<ApoyoDeFolio | null>(null)
  const [guardados, setGuardados] = useState<BibliotecaOffline[]>([])
  const [abierto, setAbierto] = useState<{ titulo: string; url: string; mime: string | null } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  useEffect(() => {
    let vivo = true
    void (async () => {
      try {
        const r = await apoyoDeFolio(folioId)
        if (vivo) setApoyo(r)
      } catch (e) {
        if (vivo && enLinea) setError(mensajeDeError(e))
      }
      const locales = await baseLocal.biblioteca_offline.toArray()
      if (vivo) setGuardados(locales)
    })()
    return () => { vivo = false }
  }, [folioId, enLinea])

  const tipoId = apoyo?.tipo_equipo_id ?? null
  const localesDelTipo = guardados.filter((g) => !tipoId || g.tipo_equipo_id === tipoId)
  const puntosLocales = localesDelTipo.find((g) => g.clase === 'contenido_servicio')?.puntos_revision as PuntoRevision[] | null | undefined
  const puntos = apoyo?.contenido?.puntos_revision ?? puntosLocales ?? []
  const manuales = apoyo?.manuales ?? []
  const manualesLocales = localesDelTipo.filter((g) => g.clase === 'manual')

  function estaGuardado(m: Manual) {
    return guardados.some((g) => g.clave === `manual:${m.id}`)
  }

  async function abrir(m: Manual) {
    setError(null)
    const local = guardados.find((g) => g.clave === `manual:${m.id}`)
    if (local?.archivo) {
      setAbierto({ titulo: m.titulo, url: URL.createObjectURL(local.archivo), mime: local.mime })
      return
    }
    try {
      const { blob } = await archivoDeManual(m.id)
      setAbierto({ titulo: m.titulo, url: URL.createObjectURL(blob), mime: m.mime })
    } catch (e) { setError(mensajeDeError(e)) }
  }

  async function abrirLocal(g: BibliotecaOffline) {
    if (!g.archivo) return
    setAbierto({ titulo: g.titulo, url: URL.createObjectURL(g.archivo), mime: g.mime })
  }

  async function guardar(m: Manual) {
    setError(null)
    setAviso(null)
    try {
      await guardarManual({
        clase: 'manual', id: m.id, tipo_equipo_id: m.tipo_equipo_id, titulo: m.titulo, categoria: m.categoria,
        version: m.version, mime: m.mime, bytes: m.bytes, activo: true, de_mis_folios: true,
      })
      setGuardados(await baseLocal.biblioteca_offline.toArray())
      setAviso(`«${m.titulo}» quedó disponible sin señal`)
    } catch (e) {
      setError(e instanceof SinEspacio
        ? `No cabe: libera ${tamano(e.faltanBytes)} en «Mis manuales sin conexión» o sube el límite`
        : mensajeDeError(e))
    }
  }

  // Sin puntos de revisión ni manuales no hay nada que mostrar: el equipo no tiene documentación cargada todavía.
  if (puntos.length === 0 && manuales.length === 0 && manualesLocales.length === 0) return null

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="apoyo-del-folio">
      <h2 className="text-sm font-semibold text-slate-800">Qué revisar y con qué</h2>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {!apoyo && <p className="mt-1 text-xs text-amber-800">Sin señal: se muestra lo que tienes descargado.</p>}

      {puntos.length > 0 && (
        <div className="mt-2">
          <p className="text-xs uppercase tracking-wide text-slate-500">
            Puntos de revisión del contrato{apoyo?.contenido?.periodicidad ? ` · ${apoyo.contenido.periodicidad}` : ''}
          </p>
          <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm text-slate-800" data-testid="puntos-del-folio">
            {puntos.map((p, i) => (
              <li key={i}>
                {p.descripcion}
                {p.obligatorio !== false && <Insignia tono="alerta">Obligatorio</Insignia>}
              </li>
            ))}
          </ol>
        </div>
      )}

      {manuales.length > 0 && (
        <ul className="mt-3 space-y-2">
          {manuales.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 p-2">
              <span className="text-sm">
                {m.titulo}
                <span className="block text-xs text-slate-500">
                  {NOMBRE_CATEGORIA[m.categoria] ?? m.categoria} · v{m.version} · {tamano(m.bytes)}
                </span>
              </span>
              <span className="flex gap-2">
                <Boton variante="secundario" className="min-h-10" onClick={() => void abrir(m)}>Ver manual</Boton>
                {estaGuardado(m)
                  ? <Insignia tono="ok">En el teléfono</Insignia>
                  : <Boton variante="secundario" className="min-h-10" onClick={() => void guardar(m)}>Guardar</Boton>}
              </span>
            </li>
          ))}
        </ul>
      )}

      {manuales.length === 0 && manualesLocales.length > 0 && (
        <ul className="mt-3 space-y-2">
          {manualesLocales.map((g) => (
            <li key={g.clave} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-200 p-2">
              <span className="text-sm">{g.titulo}<span className="block text-xs text-slate-500">v{g.version} · {tamano(g.bytes)}</span></span>
              <Boton variante="secundario" className="min-h-10" onClick={() => void abrirLocal(g)}>Ver manual</Boton>
            </li>
          ))}
        </ul>
      )}

      {abierto && (
        <div className="mt-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-medium text-slate-800">{abierto.titulo}</p>
            <button className="text-xs text-primario underline" onClick={() => setAbierto(null)}>Cerrar</button>
          </div>
          {abierto.mime?.startsWith('image/')
            ? <img src={abierto.url} alt={abierto.titulo} className="mt-1 max-h-[60vh] w-full object-contain" />
            : abierto.mime?.startsWith('video/')
              ? <video src={abierto.url} controls className="mt-1 max-h-[60vh] w-full" />
              : <iframe src={abierto.url} title={abierto.titulo} className="mt-1 h-[60vh] w-full rounded border border-slate-200" />}
        </div>
      )}
    </div>
  )
}
