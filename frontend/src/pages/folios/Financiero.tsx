import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Insignia, Tabla } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import { costosDelFolio, validarCosto } from '../../services/inventario'
import type { Financiero as Datos } from '../../types/inventario'
import { NOMBRE_ORIGEN } from '../../types/inventario'
import { fecha as fmtFecha } from './comunes'

function moneda(v: string | null | undefined) {
  return v == null ? '—' : `$${Number(v).toLocaleString('es-MX', { minimumFractionDigits: 2 })}`
}

/** Sección «Datos financieros» del archivo del folio (§6.8.6, P09): desglose del costo, refacciones, gastos de caja chica y validación. */
export function Financiero({ folioId, alCambiar }: { folioId: string; alCambiar?: () => Promise<void> | void }) {
  const { usuario } = useAuth()
  const [d, setD] = useState<Datos | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [campos, setCampos] = useState({ ajuste: '', razon_ajuste: '', costo_otros: '', centro_costos: '' })
  const cargar = useCallback(async () => {
    try { setD(await costosDelFolio(folioId)) } catch (e) { setError(mensajeDeError(e)) }
  }, [folioId])
  useEffect(() => { void cargar() }, [cargar])
  if (!usuario) return null
  if (!d) return <p className="text-sm text-slate-500">{error ?? 'Cargando los datos financieros…'}</p>
  if (!d.visible) return <p className="text-sm text-slate-500" data-testid="financiero-oculto">{d.motivo ?? 'No tienes habilitada la visibilidad de costos.'}</p>
  const c = d.costo

  async function validar() {
    setError(null)
    try {
      setD(await validarCosto(folioId, {
        ajuste: campos.ajuste || null, razon_ajuste: campos.razon_ajuste, costo_otros: campos.costo_otros || null,
        centro_costos: campos.centro_costos || null,
      }))
      setAviso('Costo validado: se registró el gasto en el ERP y se cargó a los presupuestos aplicables')
      await alCambiar?.()
    } catch (e) { setError(mensajeDeError(e)) }
  }

  return (
    <div className="space-y-3 text-sm" data-testid="financiero-folio">
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}
      {c === null ? (
        <p className="text-slate-500">El costo se calcula al cerrar el folio: refacciones consumidas más mano de obra por la tarifa vigente.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-2xl font-semibold" data-testid="costo-total">{moneda(c.costo_total)}</span>
            <Insignia tono={c.validado_at ? 'ok' : 'alerta'}>{c.validado_at ? 'Costo validado' : 'Pendiente de validar'}</Insignia>
            {c.documento_erp_ref && <Insignia>ERP {c.documento_erp_ref}</Insignia>}
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-slate-500">Refacciones</dt><dd>{moneda(c.costo_refacciones)}</dd>
            <dt className="text-slate-500">Mano de obra</dt><dd>{moneda(c.costo_mano_obra)} <span className="text-xs text-slate-500">({Number(c.horas_mano_obra)} h × {moneda(c.tarifa_hora)}, horas {c.origen_horas})</span></dd>
            <dt className="text-slate-500">Otros</dt><dd>{moneda(c.costo_otros)}</dd>
            {Number(c.ajuste) !== 0 && <><dt className="text-slate-500">Ajuste</dt><dd>{moneda(c.ajuste)} <span className="text-xs text-slate-500">{c.razon_ajuste}</span></dd></>}
            <dt className="text-slate-500">Centro de costos</dt><dd>{c.centro_costos || '—'}</dd>
            {c.validado_at && <><dt className="text-slate-500">Validado</dt><dd>{c.validado_por_nombre ?? '—'} · {fmtFecha(c.validado_at)}</dd></>}
          </dl>
        </>
      )}
      <div>
        <h4 className="text-xs font-semibold uppercase text-slate-500">Refacciones consumidas ({d.refacciones.length})</h4>
        {d.refacciones.length === 0 ? <p className="text-slate-500">Sin refacciones registradas.</p> : (
          <Tabla filas={d.refacciones} vacio="" columnas={[
            { titulo: 'Descripción', celda: (r) => <span className="text-sm">{r.descripcion}</span> },
            { titulo: 'Cantidad', celda: (r) => Number(r.cantidad) },
            { titulo: 'Origen', celda: (r) => <Insignia tono={r.origen === 'caja_chica' ? 'acento' : 'neutro'}>{NOMBRE_ORIGEN[r.origen]}</Insignia> },
            { titulo: 'Costo unitario', celda: (r) => moneda(r.costo_unitario) },
            { titulo: 'Importe', celda: (r) => moneda(r.importe) },
          ]} />
        )}
      </div>
      {d.gastos_caja_chica.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase text-slate-500">Gastos de caja chica ({d.gastos_caja_chica.length})</h4>
          <ul className="text-xs text-slate-600" data-testid="gastos-folio">{d.gastos_caja_chica.map((g) => (
            <li key={g.id}><Link className="text-primario underline" to={`/caja-chica?gasto=${g.id}`}>{g.proveedor}</Link> · {moneda(g.monto)} · {g.estado}</li>
          ))}</ul>
        </div>
      )}
      {d.puede_validar && (
        <div className="rounded-lg border border-slate-200 p-2" data-testid="validar-costo">
          <p className="mb-1 font-medium">Validar el costo</p>
          <p className="mb-2 text-xs text-slate-500">Al validarlo se genera el evento de gasto para el ERP y se carga a los presupuestos de la UN, de sus grupos y del tipo de actividad.</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <Campo etiqueta="Ajuste (+ o −)" type="number" value={campos.ajuste} onChange={(e) => setCampos({ ...campos, ajuste: e.target.value })} />
            <Campo etiqueta="Razón del ajuste" value={campos.razon_ajuste} onChange={(e) => setCampos({ ...campos, razon_ajuste: e.target.value })} />
            <Campo etiqueta="Otros costos" type="number" value={campos.costo_otros} onChange={(e) => setCampos({ ...campos, costo_otros: e.target.value })} />
            <Campo etiqueta="Centro de costos" value={campos.centro_costos} onChange={(e) => setCampos({ ...campos, centro_costos: e.target.value })} />
          </div>
          <div className="mt-2">
            <Boton disabled={!!campos.ajuste && Number(campos.ajuste) !== 0 && campos.razon_ajuste.trim().length < 3} onClick={() => void validar()}>Validar costo</Boton>
          </div>
        </div>
      )}
    </div>
  )
}
