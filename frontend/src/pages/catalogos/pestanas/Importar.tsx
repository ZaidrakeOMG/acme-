import { useState } from 'react'
import { Aviso, Boton, Insignia, Selector, Tarjeta } from '../../../components/ui'
import { useRecurso } from '../../../hooks/useRecurso'
import { api, descargar, mensajeDeError } from '../../../services/api'
import type { CatalogoImportable, Importacion } from '../../../types/api'
import { useAmbito } from '../Catalogos'

/** Flujo §6.3: descargar plantilla → subir archivo → vista previa con errores → confirmar o cancelar. */
export function Importar() {
  const ambito = useAmbito()
  const catalogos = useRecurso<CatalogoImportable[]>('/catalogos/importar/catalogos')
  const disponibles = (catalogos.datos ?? []).filter((c) =>
    ambito.rol === 'superadmin' || (c.propietario === 'tenant' ? ambito.puedeEditarTenant : ambito.puedeEditarPrestador))
  const [clave, setClave] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [importacion, setImportacion] = useState<Importacion | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const catalogo = disponibles.find((c) => c.clave === clave)

  async function ejecutar(fn: () => Promise<void>) {
    setError(null)
    setOcupado(true)
    try {
      await fn()
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setOcupado(false)
    }
  }

  async function plantilla() {
    const blob = await descargar(`/catalogos/importar/${clave}/plantilla`)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `plantilla_${clave}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  }

  async function subir() {
    if (!archivo) return
    const formulario = new FormData()
    formulario.append('archivo', archivo)
    setImportacion(await api<Importacion>(`/catalogos/importar/${clave}`, { metodo: 'POST', params: ambito.params, formulario }))
  }

  return (
    <div className="space-y-4">
      <Tarjeta titulo="1. Catálogo y archivo">
        {(catalogos.error || error) && <Aviso>{catalogos.error ?? error}</Aviso>}
        <div className="grid gap-3 md:grid-cols-3">
          <Selector etiqueta="Catálogo" value={clave} onChange={(e) => { setClave(e.target.value); setImportacion(null) }}
                    opciones={[{ valor: '', texto: 'Selecciona…' }, ...disponibles.map((c) => ({ valor: c.clave, texto: c.nombre }))]} />
          <label className="block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Archivo CSV o Excel</span>
            <input type="file" accept=".csv,.xlsx" aria-label="Archivo" disabled={!clave} onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
          </label>
          <div className="flex items-end gap-2">
            <Boton variante="secundario" disabled={!clave || ocupado} onClick={() => void ejecutar(plantilla)}>Plantilla</Boton>
            <Boton disabled={!clave || !archivo || ocupado} onClick={() => void ejecutar(subir)}>Validar</Boton>
          </div>
        </div>
        {catalogo && (
          <p className="mt-3 text-xs text-slate-500">
            Columnas: {catalogo.columnas.map((c) => <code key={c.nombre} className={`mr-1 ${c.requerida ? 'font-semibold' : ''}`}>{c.nombre}{c.requerida ? '*' : ''}</code>)}
          </p>
        )}
      </Tarjeta>

      {importacion && (
        <Tarjeta
          titulo="2. Vista previa"
          acciones={
            importacion.estado === 'vista_previa' ? (
              <div className="flex gap-2">
                <Boton variante="secundario" disabled={ocupado} onClick={() => void ejecutar(async () => setImportacion(await api(`/catalogos/importar/${importacion.id}/cancelar`, { metodo: 'POST' })))}>Cancelar</Boton>
                <Boton disabled={ocupado || importacion.filas_ok === 0} onClick={() => void ejecutar(async () => setImportacion(await api(`/catalogos/importar/${importacion.id}/confirmar`, { metodo: 'POST' })))}>
                  Confirmar {importacion.filas_ok} fila(s)
                </Boton>
              </div>
            ) : <Insignia tono={importacion.estado === 'confirmada' ? 'ok' : 'neutro'}>{importacion.estado}</Insignia>
          }
        >
          <p className="mb-3 text-sm text-slate-700">
            <strong>{importacion.archivo_nombre}</strong>: {importacion.total_filas} filas · <span className="text-green-700">{importacion.filas_ok} válidas</span> ·{' '}
            <span className="text-red-700">{importacion.filas_error} con error</span> · {importacion.duplicados_json.length} duplicadas (se omiten)
          </p>
          {importacion.resultado && <Aviso tipo="exito">Importación aplicada: {importacion.resultado.creados} creados, {importacion.resultado.actualizados} actualizados.</Aviso>}
          {importacion.errores_json.length > 0 && (
            <details open className="mb-3">
              <summary className="cursor-pointer text-sm font-medium text-red-700">Errores ({importacion.errores_json.length})</summary>
              <ul className="mt-1 max-h-48 overflow-y-auto text-xs text-slate-700">
                {importacion.errores_json.map((e, i) => <li key={i}>Fila {e.fila}{e.columna ? ` · ${e.columna}` : ''}: {e.motivo}</li>)}
              </ul>
            </details>
          )}
          {importacion.duplicados_json.length > 0 && (
            <details className="mb-3">
              <summary className="cursor-pointer text-sm font-medium text-amber-700">Duplicados ({importacion.duplicados_json.length})</summary>
              <ul className="mt-1 max-h-48 overflow-y-auto text-xs text-slate-700">
                {importacion.duplicados_json.map((e, i) => <li key={i}>Fila {e.fila}: {e.motivo}</li>)}
              </ul>
            </details>
          )}
          {importacion.vista_previa.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-left text-slate-500"><tr>{Object.keys(importacion.vista_previa[0]!).map((k) => <th key={k} className="px-2 py-1">{k}</th>)}</tr></thead>
                <tbody>
                  {importacion.vista_previa.map((f, i) => (
                    <tr key={i} className="border-t border-slate-100">{Object.values(f).map((v, j) => <td key={j} className="px-2 py-1">{String(v ?? '')}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Tarjeta>
      )}
    </div>
  )
}
