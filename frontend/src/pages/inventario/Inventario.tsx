import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import {
  ajusteInventario, aprobarOC, cancelarOC, crearArticulo, crearOC, crearUbicacion, entradaInventario, listarArticulos, listarExistencias,
  listarMovimientos, listarOCs, obtenerOC, recibirOC, traspasoInventario,
} from '../../services/inventario'
import type { Tecnico } from '../../types/api'
import type { Articulo, EstadoOC, Existencia, Movimiento, OrdenCompra, Ubicacion } from '../../types/inventario'
import { ESTADOS_OC, NOMBRE_ESTADO_OC, NOMBRE_MOVIMIENTO, NOMBRE_ORIGEN, ROLES_ESCRIBEN_INVENTARIO, ROLES_GESTIONAN_INVENTARIO } from '../../types/inventario'
import { fecha as fmtFecha } from '../folios/comunes'

type Vista = 'existencias' | 'articulos' | 'movimientos' | 'ordenes'

function moneda(v: string | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}

/** Inventario del prestador (§6.4): artículos, existencias por almacén y vehículo, movimientos y órdenes de compra. */
export function Inventario() {
  const { usuario } = useAuth()
  const [params, setParams] = useSearchParams()
  const vista = (params.get('vista') as Vista) || (usuario?.rol === 'tecnico' ? 'existencias' : 'existencias')
  const ocId = params.get('oc')
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [existencias, setExistencias] = useState<Existencia[]>([])
  const [articulos, setArticulos] = useState<Articulo[]>([])
  const [movimientos, setMovimientos] = useState<Movimiento[]>([])
  const [ordenes, setOrdenes] = useState<OrdenCompra[]>([])
  const [filtros, setFiltros] = useState({ ubicacion_id: '', solo_bajo_minimo: false, q: '', estado: '' })
  const [modal, setModal] = useState<'articulo' | 'ubicacion' | 'entrada' | 'traspaso' | 'ajuste' | 'oc' | null>(null)
  const ubicaciones = useRecurso<Ubicacion[]>('/inventario/ubicaciones')

  const cargar = useCallback(async () => {
    try {
      if (vista === 'existencias') setExistencias(await listarExistencias({ ubicacion_id: filtros.ubicacion_id || undefined, solo_bajo_minimo: filtros.solo_bajo_minimo }))
      else if (vista === 'articulos') setArticulos(await listarArticulos({ q: filtros.q || undefined }))
      else if (vista === 'movimientos') setMovimientos(await listarMovimientos({ ubicacion_id: filtros.ubicacion_id || undefined }))
      else setOrdenes(await listarOCs({ estado: filtros.estado || undefined }))
    } catch (e) { setError(mensajeDeError(e)) }
  }, [vista, filtros])
  useEffect(() => { void cargar() }, [cargar])

  function ir(cambios: Record<string, string | null>) {
    const p = new URLSearchParams(params)
    for (const [k, v] of Object.entries(cambios)) { if (v) p.set(k, v); else p.delete(k) }
    setParams(p)
  }
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); setModal(null); setAviso(texto); await cargar(); await ubicaciones.recargar() } catch (e) { setError(mensajeDeError(e)) }
  }
  if (!usuario) return null
  const escribe = ROLES_ESCRIBEN_INVENTARIO.includes(usuario.rol)
  const gestiona = ROLES_GESTIONAN_INVENTARIO.includes(usuario.rol)
  const esTecnico = usuario.rol === 'tecnico'
  const vistas: { v: Vista; texto: string }[] = esTecnico
    ? [{ v: 'existencias', texto: 'Mi vehículo' }, { v: 'movimientos', texto: 'Movimientos' }]
    : [{ v: 'existencias', texto: 'Existencias' }, { v: 'articulos', texto: 'Artículos' }, { v: 'movimientos', texto: 'Movimientos' }, { v: 'ordenes', texto: 'Órdenes de compra' }]

  return (
    <div>
      <Encabezado titulo="Inventario" descripcion="Tres orígenes de refacciones: almacén, orden de compra y caja chica. Cada movimiento recalcula la existencia y el costo promedio ponderado; el historial es inmutable."
        acciones={gestiona ? (
          <div className="flex flex-wrap gap-2">
            {escribe && <Boton variante="secundario" onClick={() => setModal('articulo')}>Nuevo artículo</Boton>}
            {escribe && <Boton variante="secundario" onClick={() => setModal('ubicacion')}>Nuevo almacén o vehículo</Boton>}
            <Boton onClick={() => setModal('entrada')}>Entrada</Boton>
            <Boton variante="secundario" onClick={() => setModal('traspaso')}>Traspaso</Boton>
            {escribe && <Boton variante="secundario" onClick={() => setModal('ajuste')}>Ajuste</Boton>}
            <Boton variante="secundario" onClick={() => setModal('oc')}>Nueva OC</Boton>
          </div>
        ) : undefined} />
      <div className="mb-3 flex flex-wrap gap-1" role="tablist" aria-label="Vistas de inventario">
        {vistas.map(({ v, texto }) => (
          <button key={v} role="tab" aria-selected={vista === v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`}
            onClick={() => ir({ vista: v })}>{texto}</button>
        ))}
      </div>
      <div className="mb-4 flex flex-wrap items-end gap-2">
        {vista !== 'articulos' && vista !== 'ordenes' && !esTecnico && (
          <Selector etiqueta="Ubicación" value={filtros.ubicacion_id} onChange={(e) => setFiltros({ ...filtros, ubicacion_id: e.target.value })}
            opciones={[{ valor: '', texto: 'Todas' }, ...(ubicaciones.datos ?? []).map((u) => ({ valor: u.id, texto: `${u.nombre} (${u.tipo})` }))]} />
        )}
        {vista === 'existencias' && (
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={filtros.solo_bajo_minimo}
            onChange={(e) => setFiltros({ ...filtros, solo_bajo_minimo: e.target.checked })} /> Solo bajo mínimo</label>
        )}
        {vista === 'articulos' && <Campo etiqueta="Buscar" value={filtros.q} onChange={(e) => setFiltros({ ...filtros, q: e.target.value })} />}
        {vista === 'ordenes' && (
          <Selector etiqueta="Estado" value={filtros.estado} onChange={(e) => setFiltros({ ...filtros, estado: e.target.value })}
            opciones={[{ valor: '', texto: 'Todos' }, ...ESTADOS_OC.map((e) => ({ valor: e, texto: NOMBRE_ESTADO_OC[e] }))]} />
        )}
      </div>
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'existencias' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          <Tabla filas={existencias} vacio="Sin existencias registradas" columnas={[
            { titulo: 'Artículo', celda: (e) => <span className="font-mono text-xs">{e.codigo}</span> },
            { titulo: 'Descripción', celda: (e) => <span className="text-sm">{e.descripcion}</span> },
            { titulo: 'Ubicación', celda: (e) => <span>{e.ubicacion} <span className="text-xs text-slate-500">{e.ubicacion_tipo}</span></span> },
            { titulo: 'Cantidad', celda: (e) => <span className={e.bajo_minimo ? 'font-semibold text-red-700' : ''}>{Number(e.cantidad)} {e.unidad}</span> },
            { titulo: 'Mínimo', celda: (e) => <span className="text-xs">{Number(e.stock_minimo)}{e.bajo_minimo && <> <Insignia tono="alerta">Bajo mínimo</Insignia></>}</span> },
            { titulo: 'Costo promedio', celda: (e) => moneda(e.costo_promedio) },
          ]} />
        </div>
      )}
      {vista === 'articulos' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          <Tabla filas={articulos} vacio="Sin artículos en el catálogo" columnas={[
            { titulo: 'Código', celda: (a) => <span className="font-mono text-xs">{a.codigo}</span> },
            { titulo: 'Descripción', celda: (a) => <span className="text-sm">{a.descripcion}</span> },
            { titulo: 'Categoría', celda: (a) => a.categoria || '—' },
            { titulo: 'Número de parte', celda: (a) => <span className="text-xs">{a.numero_parte ?? '—'}</span> },
            { titulo: 'Costo vigente', celda: (a) => moneda(a.costo_unitario_vigente) },
            { titulo: 'Mínimo', celda: (a) => Number(a.stock_minimo_default) },
            { titulo: 'Estado', celda: (a) => <Insignia tono={a.activo ? 'ok' : 'neutro'}>{a.activo ? 'Activo' : 'Inactivo'}</Insignia> },
          ]} />
        </div>
      )}
      {vista === 'movimientos' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2" data-testid="movimientos">
          <Tabla filas={movimientos} vacio="Sin movimientos" columnas={[
            { titulo: 'Fecha', celda: (m) => <span className="text-xs">{fmtFecha(m.timestamp)}</span> },
            { titulo: 'Tipo', celda: (m) => <Insignia tono={m.tipo === 'ajuste' ? 'alerta' : 'acento'}>{NOMBRE_MOVIMIENTO[m.tipo]}</Insignia> },
            { titulo: 'Artículo', celda: (m) => <span className="font-mono text-xs">{m.codigo ?? '—'}</span> },
            { titulo: 'Cantidad', celda: (m) => Number(m.cantidad) },
            { titulo: 'Origen → destino', celda: (m) => <span className="text-xs">{m.ubicacion_origen ?? '—'} → {m.ubicacion_destino ?? '—'}</span> },
            { titulo: 'Procedencia', celda: (m) => <span className="text-xs">{NOMBRE_ORIGEN[m.origen]}</span> },
            { titulo: 'Folio', celda: (m) => m.folio_id ? <Link className="text-primario underline" to={`/folios/${m.folio_id}`}>{m.numero_folio}</Link> : <span className="text-xs text-slate-400">{m.razon}</span> },
          ]} />
        </div>
      )}
      {vista === 'ordenes' && (
        <div className="rounded-xl border border-slate-200 bg-white p-2">
          <Tabla filas={ordenes} vacio="Sin órdenes de compra" columnas={[
            { titulo: 'Número', celda: (o) => <button className="text-left font-mono text-sm text-primario underline" onClick={() => ir({ oc: o.id })}>{o.numero}</button> },
            { titulo: 'Proveedor', celda: (o) => o.proveedor },
            { titulo: 'Folio', celda: (o) => o.folio_id ? <Link className="text-primario underline" to={`/folios/${o.folio_id}`}>{o.numero_folio}</Link> : '—' },
            { titulo: 'Estado', celda: (o) => <Insignia tono={o.estado === 'recibida' ? 'ok' : o.estado === 'cancelada' ? 'neutro' : 'acento'}>{NOMBRE_ESTADO_OC[o.estado]}</Insignia> },
            { titulo: 'Total', celda: (o) => moneda(o.total) },
            { titulo: 'Creada', celda: (o) => <span className="text-xs">{fmtFecha(o.created_at)}</span> },
          ]} />
        </div>
      )}

      {modal === 'articulo' && <FormArticulo alCerrar={() => setModal(null)} alGuardar={(d) => ejecutar(() => crearArticulo(d), 'Artículo creado')} />}
      {modal === 'ubicacion' && <FormUbicacion alCerrar={() => setModal(null)} alGuardar={(d) => ejecutar(() => crearUbicacion(d), 'Ubicación creada')} />}
      {modal === 'entrada' && <FormMovimiento tipo="entrada" ubicaciones={ubicaciones.datos ?? []} alCerrar={() => setModal(null)}
        alGuardar={(d) => ejecutar(() => entradaInventario(d as Parameters<typeof entradaInventario>[0]), 'Entrada registrada')} />}
      {modal === 'traspaso' && <FormMovimiento tipo="traspaso" ubicaciones={ubicaciones.datos ?? []} alCerrar={() => setModal(null)}
        alGuardar={(d) => ejecutar(() => traspasoInventario(d as Parameters<typeof traspasoInventario>[0]), 'Traspaso registrado')} />}
      {modal === 'ajuste' && <FormMovimiento tipo="ajuste" ubicaciones={ubicaciones.datos ?? []} alCerrar={() => setModal(null)}
        alGuardar={(d) => ejecutar(() => ajusteInventario(d as Parameters<typeof ajusteInventario>[0]), 'Ajuste registrado')} />}
      {modal === 'oc' && <FormOC alCerrar={() => setModal(null)} alGuardar={(d) => ejecutar(() => crearOC(d), 'Orden de compra creada')} />}
      {ocId && <DetalleOC ocId={ocId} alCerrar={() => ir({ oc: null })} alCambiar={async (t) => { setAviso(t); await cargar() }} />}
    </div>
  )
}

function FormArticulo({ alCerrar, alGuardar }: { alCerrar: () => void; alGuardar: (d: Record<string, string>) => Promise<void> }) {
  const [d, setD] = useState({ codigo: '', descripcion: '', categoria: '', unidad: 'pieza', numero_parte: '', costo_unitario_vigente: '0', stock_minimo_default: '0' })
  return (
    <Modal titulo="Nuevo artículo" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-articulo">
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta="Código" value={d.codigo} onChange={(e) => setD({ ...d, codigo: e.target.value })} />
          <Campo etiqueta="Número de parte" value={d.numero_parte} onChange={(e) => setD({ ...d, numero_parte: e.target.value })} />
        </div>
        <Campo etiqueta="Descripción" value={d.descripcion} onChange={(e) => setD({ ...d, descripcion: e.target.value })} />
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta="Categoría" value={d.categoria} onChange={(e) => setD({ ...d, categoria: e.target.value })} />
          <Campo etiqueta="Unidad" value={d.unidad} onChange={(e) => setD({ ...d, unidad: e.target.value })} />
          <Campo etiqueta="Costo unitario" type="number" value={d.costo_unitario_vigente} onChange={(e) => setD({ ...d, costo_unitario_vigente: e.target.value })} />
          <Campo etiqueta="Stock mínimo" type="number" value={d.stock_minimo_default} onChange={(e) => setD({ ...d, stock_minimo_default: e.target.value })} />
        </div>
        <div className="flex gap-2"><Boton disabled={!d.codigo || d.descripcion.length < 2} onClick={() => void alGuardar(d)}>Crear</Boton><Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton></div>
      </div>
    </Modal>
  )
}

function FormUbicacion({ alCerrar, alGuardar }: { alCerrar: () => void; alGuardar: (d: Record<string, string>) => Promise<void> }) {
  const [d, setD] = useState({ nombre: '', tipo: 'almacen', tecnico_id: '', placas: '' })
  const tecnicos = useRecurso<Tecnico[]>('/catalogos/tecnicos')
  return (
    <Modal titulo="Nuevo almacén o vehículo" abierto alCerrar={alCerrar}>
      <div className="space-y-3">
        <Selector etiqueta="Tipo" value={d.tipo} onChange={(e) => setD({ ...d, tipo: e.target.value })}
          opciones={[{ valor: 'almacen', texto: 'Almacén' }, { valor: 'vehiculo', texto: 'Vehículo de un técnico' }]} />
        <Campo etiqueta="Nombre" value={d.nombre} onChange={(e) => setD({ ...d, nombre: e.target.value })} />
        {d.tipo === 'vehiculo' && (
          <>
            <Selector etiqueta="Técnico" value={d.tecnico_id} onChange={(e) => setD({ ...d, tecnico_id: e.target.value })}
              opciones={[{ valor: '', texto: 'Elegir…' }, ...(tecnicos.datos ?? []).map((t) => ({ valor: t.usuario_id, texto: t.nombre }))]} />
            <Campo etiqueta="Placas" value={d.placas} onChange={(e) => setD({ ...d, placas: e.target.value })} />
          </>
        )}
        <div className="flex gap-2">
          <Boton disabled={d.nombre.length < 2 || (d.tipo === 'vehiculo' && !d.tecnico_id)}
            onClick={() => void alGuardar(Object.fromEntries(Object.entries(d).filter(([, v]) => v)) as Record<string, string>)}>Crear</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function FormMovimiento({ tipo, ubicaciones, alCerrar, alGuardar }: { tipo: 'entrada' | 'traspaso' | 'ajuste'; ubicaciones: Ubicacion[]; alCerrar: () => void; alGuardar: (d: Record<string, string>) => Promise<void> }) {
  const [d, setD] = useState({ articulo_id: '', ubicacion_id: '', origen_id: '', destino_id: '', cantidad: '1', costo_unitario: '', referencia: '', razon: '' })
  const articulos = useRecurso<Articulo[]>('/inventario/articulos', { activo: 'true' })
  const titulos = { entrada: 'Entrada a almacén', traspaso: 'Traspaso almacén → vehículo', ajuste: 'Ajuste de inventario' }
  const listo = d.articulo_id && Number(d.cantidad) !== 0 && (tipo === 'traspaso' ? d.origen_id && d.destino_id : d.ubicacion_id) && (tipo !== 'ajuste' || d.razon.trim().length >= 5)
  return (
    <Modal titulo={titulos[tipo]} abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid={`form-${tipo}`}>
        {tipo === 'ajuste' && <Aviso tipo="info">El ajuste admite cantidades negativas (merma) y exige razón escrita; queda en el historial inmutable.</Aviso>}
        <Selector etiqueta="Artículo" value={d.articulo_id} onChange={(e) => setD({ ...d, articulo_id: e.target.value })}
          opciones={[{ valor: '', texto: 'Elegir…' }, ...(articulos.datos ?? []).map((a) => ({ valor: a.id, texto: `${a.codigo} · ${a.descripcion}` }))]} />
        {tipo === 'traspaso' ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <Selector etiqueta="Origen" value={d.origen_id} onChange={(e) => setD({ ...d, origen_id: e.target.value })}
              opciones={[{ valor: '', texto: 'Elegir…' }, ...ubicaciones.map((u) => ({ valor: u.id, texto: `${u.nombre} (${u.tipo})` }))]} />
            <Selector etiqueta="Destino" value={d.destino_id} onChange={(e) => setD({ ...d, destino_id: e.target.value })}
              opciones={[{ valor: '', texto: 'Elegir…' }, ...ubicaciones.map((u) => ({ valor: u.id, texto: `${u.nombre} (${u.tipo})` }))]} />
          </div>
        ) : (
          <Selector etiqueta="Ubicación" value={d.ubicacion_id} onChange={(e) => setD({ ...d, ubicacion_id: e.target.value })}
            opciones={[{ valor: '', texto: 'Elegir…' }, ...ubicaciones.map((u) => ({ valor: u.id, texto: `${u.nombre} (${u.tipo})` }))]} />
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          <Campo etiqueta={tipo === 'ajuste' ? 'Cantidad (+ suma, − resta)' : 'Cantidad'} type="number" value={d.cantidad} onChange={(e) => setD({ ...d, cantidad: e.target.value })} />
          {tipo === 'entrada' && <Campo etiqueta="Costo unitario" type="number" value={d.costo_unitario} onChange={(e) => setD({ ...d, costo_unitario: e.target.value })} />}
          {tipo === 'entrada' && <Campo etiqueta="Referencia" value={d.referencia} onChange={(e) => setD({ ...d, referencia: e.target.value })} />}
        </div>
        <Campo etiqueta={tipo === 'ajuste' ? 'Razón (obligatoria)' : 'Razón o nota'} value={d.razon} onChange={(e) => setD({ ...d, razon: e.target.value })} />
        <div className="flex gap-2">
          <Boton disabled={!listo} onClick={() => void alGuardar(Object.fromEntries(Object.entries(d).filter(([, v]) => v !== '')) as Record<string, string>)}>Registrar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function FormOC({ alCerrar, alGuardar }: { alCerrar: () => void; alGuardar: (d: { proveedor: string; partidas: { articulo_id: string; cantidad: string }[]; folio_id?: string | null; notas?: string }) => Promise<void> }) {
  const [d, setD] = useState({ proveedor: '', notas: '', folio_id: '' })
  const [partidas, setPartidas] = useState<{ articulo_id: string; cantidad: string }[]>([{ articulo_id: '', cantidad: '1' }])
  const articulos = useRecurso<Articulo[]>('/inventario/articulos', { activo: 'true' })
  const validas = partidas.filter((p) => p.articulo_id && Number(p.cantidad) > 0)
  return (
    <Modal titulo="Nueva orden de compra" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-oc">
        <Aviso tipo="info">Tipo B de §6.4: el despachador la genera cuando el técnico reporta pendiente de refacción; al aprobarse se envía el evento al ERP.</Aviso>
        <Campo etiqueta="Proveedor" value={d.proveedor} onChange={(e) => setD({ ...d, proveedor: e.target.value })} />
        <Campo etiqueta="Folio relacionado (opcional)" value={d.folio_id} onChange={(e) => setD({ ...d, folio_id: e.target.value })} />
        {partidas.map((p, i) => (
          <div key={i} className="grid gap-2 sm:grid-cols-[1fr_7rem]">
            <Selector etiqueta={`Artículo ${i + 1}`} value={p.articulo_id} onChange={(e) => setPartidas(partidas.map((x, j) => j === i ? { ...x, articulo_id: e.target.value } : x))}
              opciones={[{ valor: '', texto: 'Elegir…' }, ...(articulos.datos ?? []).map((a) => ({ valor: a.id, texto: `${a.codigo} · ${a.descripcion}` }))]} />
            <Campo etiqueta="Cantidad" type="number" value={p.cantidad} onChange={(e) => setPartidas(partidas.map((x, j) => j === i ? { ...x, cantidad: e.target.value } : x))} />
          </div>
        ))}
        <Boton variante="secundario" onClick={() => setPartidas([...partidas, { articulo_id: '', cantidad: '1' }])}>Agregar partida</Boton>
        <Campo etiqueta="Notas" value={d.notas} onChange={(e) => setD({ ...d, notas: e.target.value })} />
        <div className="flex gap-2">
          <Boton disabled={d.proveedor.length < 2 || validas.length === 0}
            onClick={() => void alGuardar({ proveedor: d.proveedor, notas: d.notas, folio_id: d.folio_id || null, partidas: validas })}>Crear</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}

function DetalleOC({ ocId, alCerrar, alCambiar }: { ocId: string; alCerrar: () => void; alCambiar: (t: string) => Promise<void> }) {
  const { usuario } = useAuth()
  const [oc, setOc] = useState<OrdenCompra | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [razon, setRazon] = useState('')
  const cargar = useCallback(async () => { try { setOc(await obtenerOC(ocId)) } catch (e) { setError(mensajeDeError(e)) } }, [ocId])
  useEffect(() => { void cargar() }, [cargar])
  if (!oc || !usuario) return <Modal titulo="Orden de compra" abierto alCerrar={alCerrar}>{error ? <Aviso>{error}</Aviso> : <p className="text-sm text-slate-500">Cargando…</p>}</Modal>
  const escribe = ROLES_ESCRIBEN_INVENTARIO.includes(usuario.rol)
  const gestiona = ROLES_GESTIONAN_INVENTARIO.includes(usuario.rol)
  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); await cargar(); await alCambiar(texto) } catch (e) { setError(mensajeDeError(e)) }
  }
  return (
    <Modal titulo={`${oc.numero} · ${NOMBRE_ESTADO_OC[oc.estado as EstadoOC]}`} abierto alCerrar={alCerrar}>
      {error && <div className="mb-2"><Aviso>{error}</Aviso></div>}
      <div className="space-y-3 text-sm" data-testid="detalle-oc">
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          <dt className="text-slate-500">Proveedor</dt><dd>{oc.proveedor}</dd>
          <dt className="text-slate-500">Total</dt><dd>{moneda(oc.total)} {oc.moneda}</dd>
          <dt className="text-slate-500">Folio</dt><dd>{oc.folio_id ? <Link className="text-primario underline" to={`/folios/${oc.folio_id}`}>{oc.numero_folio}</Link> : '—'}</dd>
          <dt className="text-slate-500">Aprobada</dt><dd>{oc.aprobada_at ? fmtFecha(oc.aprobada_at) : 'pendiente'}</dd>
          <dt className="text-slate-500">Recibida</dt><dd>{oc.recibida_at ? fmtFecha(oc.recibida_at) : 'pendiente'}</dd>
          {oc.numero_oc_erp && <><dt className="text-slate-500">OC en el ERP</dt><dd>{oc.numero_oc_erp}</dd></>}
          {oc.razon_cancelacion && <><dt className="text-slate-500">Cancelación</dt><dd>{oc.razon_cancelacion}</dd></>}
        </dl>
        <Tarjeta titulo="Partidas">
          <ul className="text-sm">{oc.partidas.map((p) => (
            <li key={p.id}>{p.codigo} · {p.descripcion} — {Number(p.cantidad)} × {moneda(p.costo_unitario)}{Number(p.recibido) > 0 && <span className="text-xs text-green-700"> · recibido {Number(p.recibido)}</span>}</li>
          ))}</ul>
        </Tarjeta>
        {oc.estado === 'borrador' && escribe && <Boton onClick={() => void ejecutar(() => aprobarOC(oc.id), `${oc.numero} aprobada`)}>Aprobar</Boton>}
        {(oc.estado === 'aprobada' || oc.estado === 'enviada_erp') && gestiona && <Boton onClick={() => void ejecutar(() => recibirOC(oc.id), `${oc.numero} recibida: la refacción entró al almacén`)}>Marcar como recibida</Boton>}
        {oc.estado !== 'recibida' && oc.estado !== 'cancelada' && gestiona && (
          <div className="flex flex-wrap items-end gap-2">
            <Campo etiqueta="Razón de cancelación" value={razon} onChange={(e) => setRazon(e.target.value)} />
            <Boton variante="peligro" disabled={razon.trim().length < 3} onClick={() => void ejecutar(() => cancelarOC(oc.id, razon), `${oc.numero} cancelada`)}>Cancelar OC</Boton>
          </div>
        )}
      </div>
    </Modal>
  )
}
