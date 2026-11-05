import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { abrirBlob } from '../../services/minutas'
import {
  aprobarGasto, archivoPoliza, crearFondo, generarPoliza, imagenGasto, listarFondos, listarGastos, listarPolizas, rechazarGasto, reponerFondo,
} from '../../services/inventario'
import type { Tecnico } from '../../types/api'
import type { EstadoGasto, Fondo, Gasto, Poliza } from '../../types/inventario'
import { NOMBRE_ESTADO_GASTO, ROLES_APRUEBAN_GASTO } from '../../types/inventario'
import { fecha as fmtFecha } from '../folios/comunes'

type Vista = 'gastos' | 'fondos' | 'polizas'

function moneda(v: string | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}

/** Caja chica (§6.4 Tipo C y §6.5): fondos por técnico, bandeja de gastos con foto y aprobación en un toque, y pólizas de reposición. */
export function CajaChica() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || 'gastos'
  const gastoId = params.get('gasto')
  const [gastos, setGastos] = useState<Gasto[]>([])
  const [fondos, setFondos] = useState<Fondo[]>([])
  const [polizas, setPolizas] = useState<Poliza[]>([])
  const [estado, setEstado] = useState<EstadoGasto | ''>('capturado')
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [nuevoFondo, setNuevoFondo] = useState(false)

  const cargar = useCallback(async () => {
    try {
      setFondos(await listarFondos())
      if (vista === 'gastos') setGastos(await listarGastos({ estado: estado || undefined }))
      else if (vista === 'polizas') setPolizas(await listarPolizas())
    } catch (e) { setError(mensajeDeError(e)) }
  }, [vista, estado])
  useEffect(() => { void cargar() }, [cargar])

  function ir(cambios: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); setNuevoFondo(false); setAviso(texto); await cargar() } catch (e) { setError(mensajeDeError(e)) }
  }
  if (!usuario) return null
  const aprueba = ROLES_APRUEBAN_GASTO.includes(usuario.rol)
  const esTecnico = usuario.rol === 'tecnico'

  return (
    <div>
      <Encabezado titulo="Caja chica" descripcion="Compras directas en refaccionaria: el técnico captura la factura desde el folio y el Admin prestador aprueba en un toque, lo que da de alta la refacción, mueve el inventario y afecta el fondo. La extracción OCR y la validación del CFDI ante el SAT llegan en Fase 2."
        acciones={aprueba && vista === 'fondos' ? <Boton onClick={() => setNuevoFondo(true)}>Autorizar fondo</Boton>
          : aprueba && vista === 'polizas' ? <Boton onClick={() => void ejecutar(async () => { const p = await generarPoliza({}); if (!p) throw new Error('No hay gastos aprobados sin consolidar hoy') }, 'Póliza de reposición generada')}>Generar póliza de hoy</Boton>
          : undefined} />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas de caja chica">
        {([['gastos', esTecnico ? 'Mis gastos' : 'Gastos'], ['fondos', 'Fondos'], ['polizas', 'Pólizas de reposición']] as [Vista, string][]).map(([v, texto]) => (
          <button key={v} role="tab" aria-selected={vista === v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
            onClick={() => ir({ vista: v })}>{texto}</button>
        ))}
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'gastos' && (
        <>
          <div className="mb-3">
            <Selector etiqueta="Estado" value={estado} onChange={(e) => setEstado(e.target.value as EstadoGasto | '')}
              opciones={[{ valor: '', texto: 'Todos' }, { valor: 'capturado', texto: 'Por aprobar' }, { valor: 'aprobado', texto: 'Aprobados' }, { valor: 'rechazado', texto: 'Rechazados' }]} />
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-2">
            <Tabla filas={gastos} vacio="Sin gastos de caja chica" columnas={[
              { titulo: 'Fecha', celda: (g) => <span className="text-xs">{fmtFecha(g.timestamp)}</span> },
              { titulo: 'Proveedor', celda: (g) => <button className="text-left text-sm text-primario underline" onClick={() => ir({ gasto: g.id })}>{g.proveedor}</button> },
              { titulo: 'Descripción', celda: (g) => <span className="text-sm">{g.descripcion.slice(0, 60)}</span> },
              { titulo: 'Técnico', celda: (g) => g.tecnico_nombre ?? '—' },
              { titulo: 'Folio', celda: (g) => g.folio_id ? <Link className="text-primario underline" to={`/folios/${g.folio_id}`}>{g.numero_folio}</Link> : '—' },
              { titulo: 'Total', celda: (g) => moneda(g.monto) },
              { titulo: 'Estado', celda: (g) => <div className="flex flex-wrap gap-1"><Insignia tono={g.estado === 'aprobado' ? 'ok' : g.estado === 'rechazado' ? 'neutro' : 'alerta'}>{NOMBRE_ESTADO_GASTO[g.estado]}</Insignia>{g.imagen_disponible && <Insignia>Con foto</Insignia>}</div> },
            ]} />
          </div>
        </>
      )}
      {vista === 'fondos' && (
        <div className="grid gap-4 md:grid-cols-2" data-testid="fondos">
          {fondos.length === 0 && <p className="text-sm text-slate-500">Sin fondos autorizados.</p>}
          {fondos.map((f) => (
            <Tarjeta key={f.id} titulo={f.tecnico_nombre ?? 'Técnico'} acciones={f.bajo_umbral ? <Insignia tono="alerta">Saldo bajo</Insignia> : undefined}>
              <p className="text-sm">Saldo <strong>{moneda(f.saldo_actual)}</strong> de {moneda(f.monto_inicial)} autorizados ({Number(f.porcentaje_saldo).toFixed(0)}%)</p>
              <div className="mt-2 h-2 w-full rounded bg-slate-200"><div className={`h-2 rounded ${f.bajo_umbral ? 'bg-red-500' : 'bg-acento'}`} style={{ width: `${Math.min(100, Number(f.porcentaje_saldo))}%` }} /></div>
              <p className="mt-2 text-xs text-slate-500">{f.gastos_pendientes} gasto(s) por aprobar · última reposición {f.fecha_ultima_reposicion ?? 'sin registrar'}</p>
              {aprueba && <div className="mt-2"><Boton variante="secundario" onClick={() => void ejecutar(() => reponerFondo(f.id), `Fondo de ${f.tecnico_nombre} repuesto`)}>Reponer fondo</Boton></div>}
            </Tarjeta>
          ))}
        </div>
      )}
      {vista === 'polizas' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          <Tabla filas={polizas} vacio="Sin pólizas generadas" columnas={[
            { titulo: 'Fecha', celda: (p) => p.fecha },
            { titulo: 'Gastos', celda: (p) => p.gastos },
            { titulo: 'Total', celda: (p) => moneda(p.total) },
            { titulo: 'Estado', celda: (p) => <Insignia tono={p.estado === 'contabilizado' ? 'ok' : 'acento'}>{p.estado}</Insignia> },
            { titulo: 'Descargas', celda: (p) => (
              <div className="flex gap-2">
                <button className="text-xs text-primario underline" onClick={() => void archivoPoliza(p.id, 'xlsx').then((b) => abrirBlob(b, `reposicion-${p.fecha}.xlsx`)).catch((e) => setError(mensajeDeError(e)))}>Excel</button>
                <button className="text-xs text-primario underline" onClick={() => void archivoPoliza(p.id, 'xml').then((b) => abrirBlob(b, `reposicion-${p.fecha}.xml`)).catch((e) => setError(mensajeDeError(e)))}>XML</button>
              </div>
            ) },
          ]} />
        </div>
      )}
      {nuevoFondo && <FormFondo alCerrar={() => setNuevoFondo(false)} alGuardar={(d) => ejecutar(() => crearFondo(d), 'Fondo autorizado')} />}
      {gastoId && <DetalleGasto gasto={gastos.find((g) => g.id === gastoId)} gastoId={gastoId} alCerrar={() => ir({ gasto: null })} alCambiar={async (t) => { setAviso(t); await cargar() }} />}
    </div>
  )
}

function FormFondo({ alCerrar, alGuardar }: { alCerrar: () => void; alGuardar: (d: { tecnico_id: string; monto_inicial: string }) => Promise<void> }) {
  const [d, setD] = useState({ tecnico_id: '', monto_inicial: '5000' })
  const tecnicos = useRecurso<Tecnico[]>('/catalogos/tecnicos')
  return (
    <Modal titulo="Autorizar fondo de caja chica" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-fondo">
        <Aviso tipo="info">El técnico necesita además el permiso `usar_caja_chica` en el catálogo de técnicos.</Aviso>
        <Selector etiqueta="Técnico" value={d.tecnico_id} onChange={(e) => setD({ ...d, tecnico_id: e.target.value })}
          opciones={[{ valor: '', texto: 'Elegir…' }, ...(tecnicos.datos ?? []).map((t) => ({ valor: t.usuario_id, texto: t.nombre }))]} />
        <Campo etiqueta="Monto autorizado" type="number" value={d.monto_inicial} onChange={(e) => setD({ ...d, monto_inicial: e.target.value })} />
        <div className="flex gap-2"><Boton disabled={!d.tecnico_id || Number(d.monto_inicial) <= 0} onClick={() => void alGuardar(d)}>Autorizar</Boton><Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton></div>
      </div>
    </Modal>
  )
}

function DetalleGasto({ gasto, gastoId, alCerrar, alCambiar }: { gasto: Gasto | undefined; gastoId: string; alCerrar: () => void; alCambiar: (t: string) => Promise<void> }) {
  const { usuario } = useAuth()
  const [g, setG] = useState<Gasto | undefined>(gasto)
  const [imagen, setImagen] = useState<string | null>(null)
  const [razon, setRazon] = useState('')
  const [error, setError] = useState<string | null>(null)
  const cargar = useCallback(async () => {
    try {
      const lista = await listarGastos({})
      setG(lista.find((x) => x.id === gastoId))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [gastoId])
  useEffect(() => { if (!g) void cargar() }, [g, cargar])
  useEffect(() => {
    if (g?.imagen_disponible) void imagenGasto(g.id).then((b) => setImagen(URL.createObjectURL(b))).catch(() => setImagen(null))
  }, [g])
  if (!g || !usuario) return <Modal titulo="Gasto de caja chica" abierto alCerrar={alCerrar}>{error ? <Aviso>{error}</Aviso> : <p className="text-sm text-slate-500">Cargando…</p>}</Modal>
  const aprueba = ROLES_APRUEBAN_GASTO.includes(usuario.rol) && g.estado === 'capturado'
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); await cargar(); await alCambiar(texto) } catch (e) { setError(mensajeDeError(e)) }
  }
  return (
    <Modal titulo={`${g.proveedor} · ${moneda(g.monto)}`} abierto alCerrar={alCerrar}>
      {error && <div className="mb-2"><Aviso>{error}</Aviso></div>}
      <div className="space-y-3 text-sm" data-testid="detalle-gasto">
        <div className="flex flex-wrap gap-1">
          <Insignia tono={g.estado === 'aprobado' ? 'ok' : g.estado === 'rechazado' ? 'neutro' : 'alerta'}>{NOMBRE_ESTADO_GASTO[g.estado]}</Insignia>
          <Insignia tono={g.estado_cfdi === 'vigente' ? 'ok' : 'neutro'}>CFDI: {g.estado_cfdi === 'no_validado' ? 'validación SAT en Fase 2' : g.estado_cfdi}</Insignia>
        </div>
        {imagen && <img src={imagen} alt="Factura capturada por el técnico" className="max-h-64 rounded border border-slate-200" />}
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-slate-500">Descripción</dt><dd>{g.descripcion}</dd>
          <dt className="text-slate-500">RFC / UUID</dt><dd>{g.rfc_proveedor ?? '—'} · {g.uuid_cfdi ?? 'sin folio fiscal'}</dd>
          <dt className="text-slate-500">Importes</dt><dd>subtotal {moneda(g.subtotal)} · IVA {moneda(g.iva)} · total {moneda(g.monto)}</dd>
          <dt className="text-slate-500">Técnico</dt><dd>{g.tecnico_nombre} · {fmtFecha(g.timestamp)}</dd>
          <dt className="text-slate-500">Folio</dt><dd>{g.folio_id ? <Link className="text-primario underline" to={`/folios/${g.folio_id}`}>{g.numero_folio}</Link> : 'sin folio'}</dd>
          <dt className="text-slate-500">Contabilidad</dt><dd>{g.centro_costos || '—'} · {g.cuenta_contable || '—'}</dd>
          {g.articulo_codigo && <><dt className="text-slate-500">Artículo</dt><dd>{g.articulo_codigo} × {Number(g.cantidad)}</dd></>}
          {g.razon_rechazo && <><dt className="text-slate-500">Rechazo</dt><dd>{g.razon_rechazo}</dd></>}
          {g.aprobado_por_nombre && <><dt className="text-slate-500">Resuelto por</dt><dd>{g.aprobado_por_nombre} · {fmtFecha(g.aprobado_at)}</dd></>}
        </dl>
        {aprueba && (
          <div className="rounded-lg border border-slate-200 p-2" data-testid="resolver-gasto">
            <p className="mb-1 font-medium">Revisa y confirma</p>
            <Campo etiqueta="Razón (obligatoria al rechazar)" value={razon} onChange={(e) => setRazon(e.target.value)} />
            <div className="mt-2 flex gap-2">
              <Boton onClick={() => void ejecutar(() => aprobarGasto(g.id), `Gasto aprobado: se dio de alta la refacción y se descontó del fondo`)}>Aprobar</Boton>
              <Boton variante="peligro" disabled={razon.trim().length < 3} onClick={() => void ejecutar(() => rechazarGasto(g.id, razon), 'Gasto rechazado')}>Rechazar</Boton>
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}
