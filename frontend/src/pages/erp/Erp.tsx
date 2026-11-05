import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import { abrirBlob } from '../../services/minutas'
import { archivoExportacion, erpConfiguracion, eventosERP, exportaciones as listarExportaciones, exportarERP, guardarErpConfiguracion, procesarEventoERP } from '../../services/inventario'
import type { ErpConfig, EstadoEventoERP, EventoERP, Exportacion } from '../../types/inventario'
import { NOMBRE_ESTADO_EVENTO, NOMBRE_OPERACION } from '../../types/inventario'
import { fecha as fmtFecha } from '../folios/comunes'

type Vista = 'eventos' | 'exportaciones' | 'configuracion'

function moneda(v: string | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}

/** Integración con ERPs externos (§6.6): ACMA genera eventos en su formato interno y el adaptador los traduce. En Fase 1 la
 * exportación universal (XML de pólizas + Excel configurable) sustituye a los adaptadores. */
export function Erp() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || 'eventos'
  const [config, setConfig] = useState<ErpConfig | null>(null)
  const [eventos, setEventos] = useState<EventoERP[]>([])
  const [exportaciones, setExportaciones] = useState<Exportacion[]>([])
  const [estado, setEstado] = useState<EstadoEventoERP | ''>('')
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const hoy = new Date()
  const [rango, setRango] = useState({ desde: new Date(hoy.getFullYear(), hoy.getMonth(), 1).toISOString().slice(0, 10), hasta: hoy.toISOString().slice(0, 10) })

  const cargar = useCallback(async () => {
    try {
      setConfig(await erpConfiguracion())
      if (vista === 'eventos') setEventos(await eventosERP({ estado: estado || undefined, limite: 100 }))
      else if (vista === 'exportaciones') setExportaciones(await listarExportaciones())
    } catch (e) { setError(mensajeDeError(e)) }
  }, [vista, estado])
  useEffect(() => { void cargar() }, [cargar])

  function ir(v: Vista) {
    const p = new URLSearchParams(params)
    p.set('vista', v)
    setParams(p)
  }
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); setAviso(texto); await cargar() } catch (e) { setError(mensajeDeError(e)) }
  }
  if (!usuario) return null
  const escribe = usuario.rol === 'admin_prestador' || usuario.rol === 'superadmin'

  return (
    <div>
      <Encabezado titulo="Integración ERP" descripcion="ACMA nunca se conecta directamente con un ERP: genera un evento en su formato interno y un adaptador lo traduce. Los adaptadores de CONTPAQi y Microsip llegan en Fase 2; en Fase 1 el contador descarga la exportación universal en XML de pólizas o Excel configurable." />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas de ERP">
        {([['eventos', 'Bandeja de eventos'], ['exportaciones', 'Exportaciones'], ['configuracion', 'Configuración']] as [Vista, string][]).map(([v, texto]) => (
          <button key={v} role="tab" aria-selected={vista === v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
            onClick={() => ir(v)}>{texto}</button>
        ))}
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'eventos' && (
        <>
          <div className="mb-3">
            <Selector etiqueta="Estado" value={estado} onChange={(e) => setEstado(e.target.value as EstadoEventoERP | '')}
              opciones={[{ valor: '', texto: 'Todos' }, ...(Object.keys(NOMBRE_ESTADO_EVENTO) as EstadoEventoERP[]).map((e) => ({ valor: e, texto: NOMBRE_ESTADO_EVENTO[e] }))]} />
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-2" data-testid="eventos-erp">
            <Tabla filas={eventos} vacio="Sin eventos para el ERP" columnas={[
              { titulo: 'Fecha', celda: (e) => <span className="text-xs">{fmtFecha(e.created_at)}</span> },
              { titulo: 'Operación', celda: (e) => <span className="text-sm">{NOMBRE_OPERACION[e.operacion]}</span> },
              { titulo: 'Referencia', celda: (e) => <span className="font-mono text-xs">{String((e.payload_json.numero ?? e.payload_json.numero_folio ?? e.payload_json.codigo ?? e.entidad) as string)}</span> },
              { titulo: 'Importe', celda: (e) => moneda((e.payload_json.total ?? e.payload_json.valor_reposicion) as string | null) },
              { titulo: 'Estado', celda: (e) => <div className="flex flex-wrap gap-1">
                <Insignia tono={e.estado === 'procesado' ? 'ok' : e.estado === 'error' ? 'alerta' : 'acento'}>{NOMBRE_ESTADO_EVENTO[e.estado]}</Insignia>
                {e.adaptador && <Insignia>{e.adaptador}</Insignia>}
              </div> },
              { titulo: 'Detalle', celda: (e) => <span className="text-xs text-slate-500">{String((e.respuesta_json.detalle ?? e.ultimo_error ?? '') as string).slice(0, 60)}</span> },
              { titulo: 'Acción', celda: (e) => escribe && e.estado === 'pendiente'
                ? <Boton variante="secundario" onClick={() => void ejecutar(() => procesarEventoERP(e.id), 'Evento procesado con el adaptador configurado')}>Procesar</Boton>
                : <span className="text-xs text-slate-400">—</span> },
            ]} />
          </div>
        </>
      )}

      {vista === 'exportaciones' && (
        <div className="space-y-4">
          {escribe && (
            <Tarjeta titulo="Nueva exportación del período">
              <div className="flex flex-wrap items-end gap-2">
                <Campo etiqueta="Desde" type="date" value={rango.desde} onChange={(e) => setRango({ ...rango, desde: e.target.value })} />
                <Campo etiqueta="Hasta" type="date" value={rango.hasta} onChange={(e) => setRango({ ...rango, hasta: e.target.value })} />
                <Boton onClick={() => void ejecutar(() => exportarERP(rango.desde, rango.hasta), 'Exportación generada: descarga el XML o el Excel para tu contador')}>Generar exportación</Boton>
              </div>
            </Tarjeta>
          )}
          <div className="rounded-xl border border-slate-200 bg-white p-2">
            <Tabla filas={exportaciones} vacio="Sin exportaciones generadas" columnas={[
              { titulo: 'Período', celda: (e) => <span className="text-sm">{e.periodo_inicio} a {e.periodo_fin}</span> },
              { titulo: 'Eventos', celda: (e) => e.eventos_incluidos },
              { titulo: 'Total', celda: (e) => moneda(e.total) },
              { titulo: 'Generada', celda: (e) => <span className="text-xs">{fmtFecha(e.created_at)}</span> },
              { titulo: 'Descargas', celda: (e) => (
                <div className="flex gap-2">
                  <button className="text-xs text-primario underline" onClick={() => void archivoExportacion(e.id, 'xlsx').then((b) => abrirBlob(b, `erp-${e.periodo_inicio}.xlsx`)).catch((x) => setError(mensajeDeError(x)))}>Excel</button>
                  <button className="text-xs text-primario underline" onClick={() => void archivoExportacion(e.id, 'xml').then((b) => abrirBlob(b, `erp-${e.periodo_inicio}.xml`)).catch((x) => setError(mensajeDeError(x)))}>XML</button>
                </div>
              ) },
            ]} />
          </div>
        </div>
      )}

      {vista === 'configuracion' && config && <Configuracion config={config} escribe={escribe} alGuardar={(d) => ejecutar(() => guardarErpConfiguracion(d), 'Configuración guardada')} />}
    </div>
  )
}

function Configuracion({ config, escribe, alGuardar }: { config: ErpConfig; escribe: boolean; alGuardar: (d: Record<string, unknown>) => Promise<void> }) {
  const [d, setD] = useState({
    adaptador: config.adaptador,
    columnas: (config.columnas_excel_json ?? []).join(', '),
    cuentas: Object.entries(config.cuentas_contables_json ?? {}).map(([k, v]) => `${k}=${v}`).join('\n'),
    centros: Object.entries(config.centros_costos_json ?? {}).map(([k, v]) => `${k}=${v}`).join('\n'),
    exportacion_automatica: config.exportacion_automatica,
  })
  function pares(texto: string) {
    const salida: Record<string, string> = {}
    for (const linea of texto.split('\n')) {
      const [clave, valor] = linea.split('=')
      if (clave?.trim() && valor !== undefined) salida[clave.trim()] = valor.trim()
    }
    return salida
  }
  return (
    <div className="grid gap-4 md:grid-cols-2" data-testid="config-erp">
      <Tarjeta titulo="Adaptador">
        <Selector etiqueta="ERP del prestador" value={d.adaptador} onChange={(e) => setD({ ...d, adaptador: e.target.value as ErpConfig['adaptador'] })}
          opciones={config.adaptadores_disponibles.map((a) => ({ valor: a.clave, texto: a.fase === 2 ? `${a.nombre} — Fase 2` : a.nombre }))} />
        <ul className="mt-2 text-xs text-slate-600">
          {config.adaptadores_disponibles.map((a) => <li key={a.clave}>{a.nombre} {a.fase === 2 && <Insignia>Fase 2</Insignia>}</li>)}
        </ul>
        <p className="mt-2 text-xs text-slate-500">Con un adaptador de Fase 2 seleccionado, los eventos quedan registrados como omitidos con su motivo: el modelo de datos ya existe y Fase 2 solo agrega el worker que los procesa.</p>
        <label className="mt-2 flex items-center gap-1 text-sm"><input type="checkbox" checked={d.exportacion_automatica}
          onChange={(e) => setD({ ...d, exportacion_automatica: e.target.checked })} /> Generar la exportación automáticamente al cierre de período</label>
      </Tarjeta>
      <Tarjeta titulo="Columnas del Excel">
        <Campo etiqueta="Columnas (separadas por coma)" value={d.columnas} onChange={(e) => setD({ ...d, columnas: e.target.value })} />
        <p className="mt-1 text-xs text-slate-500">Disponibles: fecha, tipo, referencia, concepto, centro_costos, cuenta_contable, subtotal, iva, total, moneda, entidad, entidad_id.</p>
      </Tarjeta>
      <Tarjeta titulo="Cuentas contables por operación">
        <textarea className="w-full rounded-lg border border-slate-300 p-2 text-sm" rows={4} aria-label="Cuentas contables"
          value={d.cuentas} onChange={(e) => setD({ ...d, cuentas: e.target.value })} placeholder="registrar_gasto=5101-001" />
      </Tarjeta>
      <Tarjeta titulo="Centros de costos por operación">
        <textarea className="w-full rounded-lg border border-slate-300 p-2 text-sm" rows={4} aria-label="Centros de costos"
          value={d.centros} onChange={(e) => setD({ ...d, centros: e.target.value })} placeholder="registrar_gasto=MANTENIMIENTO" />
      </Tarjeta>
      {escribe && (
        <div className="md:col-span-2">
          <Boton onClick={() => void alGuardar({
            adaptador: d.adaptador, exportacion_automatica: d.exportacion_automatica,
            columnas_excel_json: d.columnas.split(',').map((x) => x.trim()).filter(Boolean),
            cuentas_contables_json: pares(d.cuentas), centros_costos_json: pares(d.centros),
          })}>Guardar configuración</Boton>
        </div>
      )}
    </div>
  )
}
