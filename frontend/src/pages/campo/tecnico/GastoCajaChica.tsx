import { useCallback, useEffect, useState } from 'react'
import { Aviso, Boton, Insignia, Selector } from '../../../components/ui'
import { api } from '../../../services/api'
import { capturarGasto, extraerOCR, listarFondos, listarGastos } from '../../../services/inventario'
import type { Articulo, Fondo, Gasto } from '../../../types/inventario'
import { NOMBRE_ESTADO_GASTO } from '../../../types/inventario'

function moneda(v: string | number | null | undefined) {
  return v == null || v === '' ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}

async function aBase64(archivo: File): Promise<string> {
  const buffer = await archivo.arrayBuffer()
  let binario = ''
  const bytes = new Uint8Array(buffer)
  for (let i = 0; i < bytes.length; i += 1) binario += String.fromCharCode(bytes[i]!)
  return btoa(binario)
}

/** Caja chica desde la atención del folio (§6.4 Tipo C): el técnico fotografía la factura y captura los datos; el Admin
 * prestador aprueba en un toque. La extracción OCR y la validación del CFDI llegan en Fase 2. */
export function GastoCajaChica({ folioId, alRegistrar }: { folioId: string; alRegistrar?: () => Promise<void> | void }) {
  const [fondo, setFondo] = useState<Fondo | null>(null)
  const [gastos, setGastos] = useState<Gasto[]>([])
  const [articulos, setArticulos] = useState<Articulo[]>([])
  const [abierto, setAbierto] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [d, setD] = useState({ proveedor: '', rfc_proveedor: '', uuid_cfdi: '', descripcion: '', numero_parte: '', articulo_id: '',
                               cantidad: '1', subtotal: '', iva: '', imagen_base64: '', nombre_imagen: '', mime: '' })

  const cargar = useCallback(async () => {
    try {
      const fondos = await listarFondos()
      setFondo(fondos[0] ?? null)
      setGastos(await listarGastos({ folio_id: folioId }))
    } catch { setFondo(null) }
  }, [folioId])
  useEffect(() => { void cargar() }, [cargar])
  useEffect(() => { if (abierto) api<Articulo[]>('/inventario/articulos', { params: { activo: true } }).then(setArticulos).catch(() => setArticulos([])) }, [abierto])

  async function tomarFoto(archivo: File) {
    setError(null)
    try {
      const base64 = await aBase64(archivo)
      setD((x) => ({ ...x, imagen_base64: base64, nombre_imagen: archivo.name, mime: archivo.type || 'image/jpeg' }))
      const r = await extraerOCR(base64, archivo.type || 'image/jpeg')
      if (r.disponible) {
        setD((x) => ({ ...x, proveedor: r.proveedor ?? x.proveedor, rfc_proveedor: r.rfc_proveedor ?? x.rfc_proveedor, uuid_cfdi: r.uuid_cfdi ?? x.uuid_cfdi,
                       descripcion: r.descripcion ?? x.descripcion, subtotal: r.subtotal ?? x.subtotal, iva: r.iva ?? x.iva }))
      } else {
        setAviso(r.detalle)
      }
    } catch { setAviso('Foto guardada; captura los datos de la factura a mano') }
  }

  async function enviar() {
    setError(null)
    setEnviando(true)
    try {
      await capturarGasto({ folio_id: folioId, ...Object.fromEntries(Object.entries(d).filter(([, v]) => v !== '')) })
      setD({ proveedor: '', rfc_proveedor: '', uuid_cfdi: '', descripcion: '', numero_parte: '', articulo_id: '', cantidad: '1', subtotal: '', iva: '',
             imagen_base64: '', nombre_imagen: '', mime: '' })
      setAbierto(false)
      setAviso('Gasto enviado al Admin prestador para su aprobación')
      await cargar()
      await alRegistrar?.()
    } catch (e) { setError((e as { mensaje?: string }).mensaje ?? 'No se pudo registrar el gasto') } finally { setEnviando(false) }
  }

  if (!fondo) return null
  const total = (Number(d.subtotal) || 0) + (Number(d.iva) || 0)
  const listo = d.proveedor.trim().length >= 2 && d.descripcion.trim().length >= 2 && Number(d.subtotal) > 0

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" data-testid="caja-chica-campo">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-800">Caja chica</h2>
        <Insignia tono={fondo.bajo_umbral ? 'alerta' : 'ok'}>Saldo {moneda(fondo.saldo_actual)}</Insignia>
      </div>
      <p className="mt-1 text-xs text-slate-500">Compra directa en refaccionaria: toma la foto de la factura y captura los datos. Al aprobarse se da de alta la refacción y el folio se desbloquea para cierre.</p>
      {error && <div className="mt-2"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mt-2"><Aviso tipo="info">{aviso}</Aviso></div>}
      {gastos.length > 0 && (
        <ul className="mt-2 text-sm text-slate-700">{gastos.map((g) => (
          <li key={g.id}>{g.proveedor} · {moneda(g.monto)} <Insignia tono={g.estado === 'aprobado' ? 'ok' : g.estado === 'rechazado' ? 'neutro' : 'alerta'}>{NOMBRE_ESTADO_GASTO[g.estado]}</Insignia></li>
        ))}</ul>
      )}
      {!abierto ? (
        <Boton className="mt-3 min-h-12 w-full text-base" variante="secundario" onClick={() => setAbierto(true)}>Capturar gasto de caja chica</Boton>
      ) : (
        <form className="mt-3 grid gap-2" onSubmit={(e) => { e.preventDefault(); void enviar() }}>
          <label className="text-sm">
            <span className="mb-1 block text-slate-700">Foto de la factura</span>
            <input type="file" accept="image/*" capture="environment" aria-label="Foto de la factura"
              onChange={(e) => { const a = e.target.files?.[0]; if (a) void tomarFoto(a) }} className="w-full text-sm" />
          </label>
          {d.imagen_base64 && <p className="text-xs text-green-700">Foto lista ({d.nombre_imagen})</p>}
          <input aria-label="Proveedor" placeholder="Proveedor" value={d.proveedor} onChange={(e) => setD({ ...d, proveedor: e.target.value })}
            className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
          <div className="grid grid-cols-2 gap-2">
            <input aria-label="RFC del proveedor" placeholder="RFC" value={d.rfc_proveedor} onChange={(e) => setD({ ...d, rfc_proveedor: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
            <input aria-label="Folio fiscal (UUID)" placeholder="Folio fiscal" value={d.uuid_cfdi} onChange={(e) => setD({ ...d, uuid_cfdi: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
          </div>
          <input aria-label="Descripción" placeholder="Descripción de la refacción" value={d.descripcion} onChange={(e) => setD({ ...d, descripcion: e.target.value })}
            className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
          <div className="grid grid-cols-2 gap-2">
            <input aria-label="Número de parte" placeholder="Número de parte" value={d.numero_parte} onChange={(e) => setD({ ...d, numero_parte: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
            <input aria-label="Cantidad" type="number" min={1} step="1" value={d.cantidad} onChange={(e) => setD({ ...d, cantidad: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
          </div>
          <Selector etiqueta="Artículo del catálogo (opcional)" value={d.articulo_id} onChange={(e) => setD({ ...d, articulo_id: e.target.value })}
            opciones={[{ valor: '', texto: 'Sin artículo (compra fuera de catálogo)' }, ...articulos.map((a) => ({ valor: a.id, texto: `${a.codigo} · ${a.descripcion}` }))]} />
          <div className="grid grid-cols-2 gap-2">
            <input aria-label="Subtotal" type="number" min={0} step="0.01" placeholder="Subtotal" value={d.subtotal} onChange={(e) => setD({ ...d, subtotal: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
            <input aria-label="IVA" type="number" min={0} step="0.01" placeholder="IVA" value={d.iva} onChange={(e) => setD({ ...d, iva: e.target.value })}
              className="rounded-lg border border-slate-300 px-3 py-2 text-base" />
          </div>
          <p className="text-sm text-slate-700">Total: <strong>{moneda(total)}</strong></p>
          <div className="flex gap-2">
            <Boton type="submit" className="min-h-12 flex-1 text-base" disabled={!listo || enviando}>Enviar para aprobación</Boton>
            <Boton type="button" variante="secundario" onClick={() => setAbierto(false)}>Cancelar</Boton>
          </div>
        </form>
      )}
    </div>
  )
}
