import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Insignia } from '../../../components/ui'
import { useConexion } from '../../../hooks/useConexion'
import { mensajeDeError } from '../../../services/api'
import { archivoDeManual, listarManuales } from '../../../services/capacitacion'
import {
  SinEspacio, borrar, descargaAutomatica, espacio, fijarDescargaAutomatica, fijarTopeMb, guardarManual, guardados,
  topeMb, type EspacioDisponible,
} from '../../../services/bibliotecaOffline'
import { baseLocal, type BibliotecaOffline } from '../../../services/db'
import type { Manual } from '../../../types/capacitacion'
import { NOMBRE_CATEGORIA } from '../../../types/capacitacion'
import { tamanoArchivo as tamano } from '../../folios/comunes'

/**
 * «Mis manuales sin conexión» (§6.2 capa 3, ACT-5.3): lo guardado en el teléfono con su tamaño y versión, el aviso de
 * que hay una versión nueva, el botón para borrar, el límite de almacenamiento con la cuota del navegador y la
 * descarga selectiva de los manuales de los folios del día.
 */
export function MisManuales() {
  const { enLinea } = useConexion()
  const [filas, setFilas] = useState<BibliotecaOffline[]>([])
  const [disponibles, setDisponibles] = useState<Manual[]>([])
  const [espacioActual, setEspacioActual] = useState<EspacioDisponible | null>(null)
  const [tope, setTope] = useState(200)
  const [automatica, setAutomatica] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState<string | null>(null)

  const refrescar = useCallback(async () => {
    setFilas(await guardados())
    setEspacioActual(await espacio())
    setTope(await topeMb())
    setAutomatica(await descargaAutomatica())
  }, [])

  useEffect(() => { void refrescar() }, [refrescar])
  useEffect(() => {
    if (!enLinea) return
    void listarManuales({ solo_mis_folios: true }).then(setDisponibles).catch(() => setDisponibles([]))
  }, [enLinea])

  async function guardar(m: Manual) {
    setError(null)
    setAviso(null)
    setOcupado(m.id)
    try {
      await guardarManual({
        clase: 'manual', id: m.id, tipo_equipo_id: m.tipo_equipo_id, titulo: m.titulo, categoria: m.categoria,
        version: m.version, mime: m.mime, bytes: m.bytes, activo: true, de_mis_folios: true,
      })
      setAviso(`«${m.titulo}» quedó disponible sin señal`)
      await refrescar()
    } catch (e) {
      setError(e instanceof SinEspacio
        ? `No cabe: libera ${tamano(e.faltanBytes)} o sube el límite de almacenamiento`
        : mensajeDeError(e))
    } finally { setOcupado(null) }
  }

  /**
   * Reemplaza el archivo guardado por la versión vigente y quita el aviso. Cuando el servidor ya dijo cuál es la
   * versión vigente se reusa `guardarManual`, que revisa el espacio y registra la versión nueva en el servidor.
   */
  async function actualizar(fila: BibliotecaOffline) {
    setError(null)
    setOcupado(fila.id)
    try {
      const vigente = disponibles.find((m) => m.id === fila.id)
      if (vigente) {
        await guardarManual({
          clase: 'manual', id: vigente.id, tipo_equipo_id: vigente.tipo_equipo_id, titulo: vigente.titulo,
          categoria: vigente.categoria, version: vigente.version, mime: vigente.mime, bytes: vigente.bytes,
          activo: true, de_mis_folios: true,
        })
      } else {
        // La lista del servidor no está a la mano (pantalla abierta desde antes): se baja el archivo vigente igual.
        const { blob } = await archivoDeManual(fila.id)
        await baseLocal.biblioteca_offline.put({
          ...fila, archivo: blob, bytes: blob.size, version: fila.version + 1, desactualizado: false,
          descargado: new Date().toISOString(),
        })
      }
      setAviso(`«${fila.titulo}» actualizado`)
      await refrescar()
    } catch (e) {
      setError(e instanceof SinEspacio
        ? `No cabe la versión nueva: libera ${tamano(e.faltanBytes)} o sube el límite`
        : mensajeDeError(e))
    } finally { setOcupado(null) }
  }

  async function quitar(fila: BibliotecaOffline) {
    setError(null)
    try { await borrar(fila.clave); setAviso(`«${fila.titulo}» se borró del teléfono`); await refrescar() }
    catch (e) { setError(mensajeDeError(e)) }
  }

  const porDescargar = disponibles.filter((m) => !filas.some((f) => f.clave === `manual:${m.id}`))
  const usado = espacioActual?.usadoBytes ?? 0
  const limite = espacioActual?.topeBytes ?? tope * 1_000_000
  const porcentaje = Math.min(100, Math.round((usado / Math.max(1, limite)) * 100))
  const casiLleno = porcentaje >= 80

  return (
    <div className="mx-auto max-w-lg space-y-4">
      <Link to="/campo" className="text-xs text-primario underline">← Mis folios</Link>
      <div>
        <p className="text-xs uppercase tracking-wide text-slate-500">App del técnico</p>
        <h1 className="text-xl font-semibold text-slate-900">Mis manuales sin conexión</h1>
      </div>
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {!enLinea && <Aviso tipo="info">Sin conexión: puedes consultar y borrar lo guardado; para descargar necesitas señal.</Aviso>}

      <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="espacio-biblioteca">
        <div className="flex items-center justify-between text-sm">
          <span>{tamano(usado)} de {tamano(limite)} usados</span>
          <span className="text-xs text-slate-500">{filas.length} archivo(s)</span>
        </div>
        <div className="mt-2 h-2 w-full rounded bg-slate-200">
          <div className={`h-2 rounded ${casiLleno ? 'bg-red-500' : 'bg-acento'}`} style={{ width: `${porcentaje}%` }} />
        </div>
        {casiLleno && <p className="mt-2 text-xs text-red-700">Vas a quedarte sin espacio: borra algo o sube el límite.</p>}
        {espacioActual?.cuotaBytes != null && (
          <p className="mt-1 text-xs text-slate-500">
            El navegador te deja guardar hasta {tamano(espacioActual.cuotaBytes)} en este dispositivo.
          </p>
        )}
        <label className="mt-3 block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Límite de almacenamiento (MB)</span>
          <input type="number" min={10} max={2000} value={tope} aria-label="Límite de almacenamiento"
            className="w-28 rounded-lg border border-slate-300 px-2 py-1 text-base"
            onChange={(e) => setTope(Number(e.target.value))}
            onBlur={() => void fijarTopeMb(tope).then(refrescar)} />
        </label>
        <label className="mt-2 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={automatica}
            onChange={(e) => { setAutomatica(e.target.checked); void fijarDescargaAutomatica(e.target.checked) }} />
          Descargar solo con Wi-Fi los manuales de mis folios del día
        </label>
      </div>

      <section>
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">En el teléfono · {filas.length}</h2>
        {filas.length === 0 && <p className="text-sm text-slate-400">Todavía no guardas nada.</p>}
        <ul className="space-y-2" data-testid="manuales-offline">
          {filas.map((f) => (
            <li key={f.clave} className="rounded-xl border border-slate-200 bg-white p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-medium text-slate-800">{f.titulo}</p>
                  <p className="text-xs text-slate-500">
                    {f.clase === 'manual' ? 'Manual' : 'Puntos de revisión'} · v{f.version} · {tamano(f.bytes)}
                  </p>
                </div>
                {f.desactualizado && <Insignia tono="alerta">Hay versión nueva</Insignia>}
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                {f.desactualizado && f.clase === 'manual' && (
                  <Boton variante="secundario" className="min-h-10" disabled={!enLinea || ocupado === f.id}
                    onClick={() => void actualizar(f)}>Actualizar</Boton>
                )}
                <Boton variante="secundario" className="min-h-10" onClick={() => void quitar(f)}>Borrar</Boton>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {enLinea && (
        <section>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            De mis folios · {porDescargar.length}
          </h2>
          {porDescargar.length === 0 && (
            <p className="text-sm text-slate-400">
              {disponibles.length === 0
                ? 'Hoy no tienes folios con manual para descargar.'
                : 'Ya tienes todos los de tus folios.'}
            </p>
          )}
          <ul className="space-y-2" data-testid="manuales-por-descargar">
            {porDescargar.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 bg-white p-3">
                <div>
                  <p className="text-sm font-medium text-slate-800">{m.titulo}</p>
                  <p className="text-xs text-slate-500">
                    {m.tipo_equipo} · {NOMBRE_CATEGORIA[m.categoria] ?? m.categoria} · v{m.version} · {tamano(m.bytes)}
                  </p>
                </div>
                <Boton variante="secundario" className="min-h-10" disabled={ocupado === m.id}
                  onClick={() => void guardar(m)}>Guardar</Boton>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
