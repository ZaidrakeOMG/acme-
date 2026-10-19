import { useState } from 'react'
import { Aviso, Boton, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import type { AlertaEfectiva, Prestador, Tenant } from '../../types/api'

const UNIDADES: Record<string, string> = { porcentaje: '%', minutos: 'min', horas: 'h', dias: 'días', metros: 'm', cantidad: '' }

export function Alertas() {
  const { usuario } = useAuth()
  const esSuper = usuario?.rol === 'superadmin'
  const tenants = useRecurso<Tenant[]>(esSuper ? '/tenants' : null)
  const prestadores = useRecurso<Prestador[]>(esSuper ? '/prestadores' : null)
  const [ambito, setAmbito] = useState('')
  const params = esSuper && ambito ? { [ambito.split(':')[0] === 't' ? 'tenant_id' : 'prestador_id']: ambito.split(':')[1] } : undefined
  const { datos, error, recargar } = useRecurso<AlertaEfectiva[]>(!esSuper || ambito ? '/alertas/configuracion' : null, params)
  const [editar, setEditar] = useState<AlertaEfectiva | null>(null)

  return (
    <div>
      <Encabezado titulo="Configuración de alertas" descripcion="Umbrales por cliente o prestador, dentro del rango que define el superadmin. Cada módulo activa su lógica en su prompt." />
      {esSuper && (
        <div className="mb-4 max-w-sm">
          <Selector
            etiqueta="Ámbito"
            value={ambito}
            onChange={(e) => setAmbito(e.target.value)}
            opciones={[
              { valor: '', texto: 'Selecciona un cliente o prestador…' },
              ...(tenants.datos ?? []).map((t) => ({ valor: `t:${t.id}`, texto: `Cliente · ${t.razon_social}` })),
              ...(prestadores.datos ?? []).map((p) => ({ valor: `p:${p.id}`, texto: `Prestador · ${p.razon_social}` })),
            ]}
          />
        </div>
      )}
      <Tarjeta>
        {error && <Aviso>{error}</Aviso>}
        <Tabla
          filas={(datos ?? []).map((a) => ({ ...a, id: a.clave }))}
          vacio={esSuper && !ambito ? 'Selecciona un ámbito' : 'Sin alertas'}
          columnas={[
            { titulo: 'Alerta', celda: (a) => <><p className="font-mono text-xs font-medium">{a.clave}</p><p className="text-xs text-slate-500">{a.descripcion}</p></> },
            { titulo: 'Umbral', celda: (a) => <span className="whitespace-nowrap">{Number(a.umbral_valor)} {UNIDADES[a.tipo_umbral]}{a.personalizada && <> <Insignia tono="acento">propio</Insignia></>}</span> },
            { titulo: 'Rango', celda: (a) => <span className="whitespace-nowrap text-xs text-slate-500">{Number(a.umbral_min)}–{Number(a.umbral_max)}</span> },
            { titulo: 'Canales', celda: (a) => a.canales.join(', ') },
            { titulo: 'Estado', celda: (a) => (a.activa ? <Insignia tono="ok">Activa</Insignia> : <Insignia>Inactiva</Insignia>) },
            { titulo: 'Lógica', celda: (a) => <span className="text-xs text-slate-500">{a.prompt_origen}</span> },
            { titulo: '', celda: (a) => <Boton variante="fantasma" onClick={() => setEditar(a)}>Ajustar</Boton> },
          ]}
        />
      </Tarjeta>
      <Modal titulo={editar?.clave ?? ''} abierto={editar !== null} alCerrar={() => setEditar(null)}>
        {editar && <FormularioAlerta alerta={editar} params={params} alGuardar={async () => { setEditar(null); await recargar() }} />}
      </Modal>
    </div>
  )
}

function FormularioAlerta({ alerta, params, alGuardar }: { alerta: AlertaEfectiva; params: Record<string, string | undefined> | undefined; alGuardar: () => Promise<void> }) {
  const [umbral, setUmbral] = useState(String(Number(alerta.umbral_valor)))
  const [canales, setCanales] = useState<Set<string>>(new Set(alerta.canales))
  const [activa, setActiva] = useState(alerta.activa)
  const [error, setError] = useState<string | null>(null)
  const min = Number(alerta.umbral_min)
  const max = Number(alerta.umbral_max)

  async function guardar() {
    const valor = Number(umbral)
    if (Number.isNaN(valor) || valor < min || valor > max) return setError(`El umbral debe estar entre ${min} y ${max}`)
    if (canales.size === 0) return setError('Selecciona al menos un canal')
    try {
      await api(`/alertas/configuracion/${alerta.clave}`, {
        metodo: 'PUT',
        params,
        cuerpo: { umbral_valor: valor, canales: [...canales], activa, parametros: alerta.parametros, destinatarios_roles: alerta.destinatarios_roles },
      })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function restablecer() {
    try {
      await api(`/alertas/configuracion/${alerta.clave}`, { metodo: 'DELETE', params })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">{alerta.descripcion}</p>
      {error && <Aviso>{error}</Aviso>}
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">Umbral ({UNIDADES[alerta.tipo_umbral] || alerta.tipo_umbral}) — rango {min} a {max}, default {Number(alerta.umbral_default)}</span>
        <input type="number" min={min} max={max} value={umbral} onChange={(e) => setUmbral(e.target.value)} className="w-full rounded-lg border border-slate-300 px-3 py-2" />
      </label>
      <fieldset className="text-sm">
        <legend className="mb-1 font-medium text-slate-700">Canales</legend>
        <div className="flex gap-4">
          {['push', 'email'].map((c) => (
            <label key={c} className="flex items-center gap-2">
              <input type="checkbox" checked={canales.has(c)} onChange={(e) => { const s = new Set(canales); if (e.target.checked) s.add(c); else s.delete(c); setCanales(s) }} />
              {c === 'push' ? 'Push' : 'Correo'}
            </label>
          ))}
        </div>
      </fieldset>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={activa} onChange={(e) => setActiva(e.target.checked)} /> Alerta activa
      </label>
      <div className="flex gap-2">
        <Boton className="flex-1" onClick={() => void guardar()}>Guardar</Boton>
        {alerta.personalizada && <Boton variante="secundario" onClick={() => void restablecer()}>Restablecer default</Boton>}
      </div>
    </div>
  )
}
