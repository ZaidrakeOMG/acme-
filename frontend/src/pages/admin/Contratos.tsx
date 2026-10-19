import { useState } from 'react'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import type { Contrato, NivelSeveridad, SLA, Tenant } from '../../types/api'

export const NIVELES: { nivel: NivelSeveridad; nombre: string }[] = [
  { nivel: 'critica', nombre: 'Crítica' },
  { nivel: 'alta', nombre: 'Alta' },
  { nivel: 'media', nombre: 'Media' },
  { nivel: 'baja', nombre: 'Baja' },
  { nivel: 'muy_baja', nombre: 'Muy baja' },
]

const SLA_INICIAL: Record<NivelSeveridad, [number, number]> = {
  critica: [2, 8], alta: [4, 24], media: [8, 72], baja: [24, 168], muy_baja: [72, 720],
}

export function Contratos() {
  const { usuario } = useAuth()
  const { datos, error, recargar } = useRecurso<Contrato[]>('/contratos')
  const tenants = useRecurso<Tenant[]>('/tenants')
  const [editar, setEditar] = useState<Contrato | 'nuevo' | null>(null)
  const puedeEditar = usuario?.rol === 'admin_prestador' || usuario?.rol === 'superadmin'
  const nombreTenant = (id: string) => tenants.datos?.find((t) => t.id === id)?.razon_social ?? id.slice(0, 8)

  return (
    <div>
      <Encabezado
        titulo="Contratos y SLAs"
        descripcion="Estructura del contrato por cliente y tiempos por severidad (1 a 4,320 horas). El contador de SLA llega en P10."
        acciones={puedeEditar && <Boton onClick={() => setEditar('nuevo')}>Nuevo contrato</Boton>}
      />
      <Tarjeta>
        {error && <Aviso>{error}</Aviso>}
        <Tabla
          filas={datos ?? []}
          columnas={[
            { titulo: 'Contrato', celda: (c) => <><p className="font-medium">{c.nombre}</p><p className="text-xs text-slate-500">{nombreTenant(c.tenant_id)}</p></> },
            { titulo: 'Vigencia', celda: (c) => `${c.fecha_inicio} → ${c.fecha_fin}` },
            { titulo: 'Modalidad', celda: (c) => <Insignia tono="acento">{c.modalidad}</Insignia> },
            {
              titulo: 'SLA crítico (resp./resol.)',
              celda: (c) => {
                const s = c.slas.find((x) => x.nivel_severidad === 'critica')
                return s ? `${s.tiempo_respuesta_horas} h / ${s.tiempo_resolucion_horas} h` : '—'
              },
            },
            { titulo: '', celda: (c) => <Boton variante="fantasma" onClick={() => setEditar(c)}>{puedeEditar ? 'Editar' : 'Ver'}</Boton> },
          ]}
        />
      </Tarjeta>
      <Modal titulo={editar === 'nuevo' ? 'Nuevo contrato' : 'Contrato'} abierto={editar !== null} alCerrar={() => setEditar(null)}>
        {editar && (
          <FormularioContrato
            contrato={editar === 'nuevo' ? null : editar}
            tenants={tenants.datos ?? []}
            soloLectura={!puedeEditar}
            alGuardar={async () => {
              setEditar(null)
              await recargar()
            }}
          />
        )}
      </Modal>
    </div>
  )
}

function FormularioContrato({ contrato, tenants, soloLectura, alGuardar }: { contrato: Contrato | null; tenants: Tenant[]; soloLectura: boolean; alGuardar: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null)
  const [tenantId, setTenantId] = useState(contrato?.tenant_id ?? tenants[0]?.id ?? '')
  const [nombre, setNombre] = useState(contrato?.nombre ?? '')
  const [modalidad, setModalidad] = useState<'evento' | 'iguala'>(contrato?.modalidad ?? 'evento')
  const [folios, setFolios] = useState(String(contrato?.folios_correctivos_iguala ?? ''))
  const [inicio, setInicio] = useState(contrato?.fecha_inicio ?? '')
  const [fin, setFin] = useState(contrato?.fecha_fin ?? '')
  const [slas, setSlas] = useState<Record<NivelSeveridad, { resp: string; resol: string; pen: string }>>(() =>
    Object.fromEntries(
      NIVELES.map(({ nivel }) => {
        const s: SLA | undefined = contrato?.slas.find((x) => x.nivel_severidad === nivel)
        return [nivel, { resp: String(s?.tiempo_respuesta_horas ?? SLA_INICIAL[nivel][0]), resol: String(s?.tiempo_resolucion_horas ?? SLA_INICIAL[nivel][1]), pen: String(s?.penalizacion_valor ?? 0) }]
      }),
    ) as Record<NivelSeveridad, { resp: string; resol: string; pen: string }>,
  )

  async function guardar() {
    setError(null)
    const cuerpoSlas = NIVELES.map(({ nivel }) => ({
      nivel_severidad: nivel,
      tiempo_respuesta_horas: Number(slas[nivel].resp),
      tiempo_resolucion_horas: Number(slas[nivel].resol),
      penalizacion_tipo: 'porcentaje',
      penalizacion_valor: Number(slas[nivel].pen),
    }))
    const invalido = cuerpoSlas.find((s) => !(s.tiempo_respuesta_horas >= 1 && s.tiempo_resolucion_horas <= 4320 && s.tiempo_resolucion_horas >= s.tiempo_respuesta_horas))
    if (invalido) return setError('Cada nivel requiere respuesta ≥ 1 h, resolución ≤ 4,320 h y resolución ≥ respuesta')
    const cuerpo = {
      nombre, modalidad, fecha_inicio: inicio, fecha_fin: fin, slas: cuerpoSlas,
      folios_correctivos_iguala: modalidad === 'iguala' ? Number(folios || 0) : null,
    }
    try {
      if (contrato) await api(`/contratos/${contrato.id}`, { metodo: 'PATCH', cuerpo })
      else await api('/contratos', { metodo: 'POST', cuerpo: { ...cuerpo, tenant_id: tenantId } })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <fieldset disabled={soloLectura} className="space-y-3">
      {error && <Aviso>{error}</Aviso>}
      {!contrato && <Selector etiqueta="Cliente" value={tenantId} onChange={(e) => setTenantId(e.target.value)} opciones={tenants.map((t) => ({ valor: t.id, texto: t.razon_social }))} />}
      <Campo etiqueta="Nombre del contrato" value={nombre} onChange={(e) => setNombre(e.target.value)} />
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Inicio" type="date" value={inicio} onChange={(e) => setInicio(e.target.value)} />
        <Campo etiqueta="Fin" type="date" value={fin} onChange={(e) => setFin(e.target.value)} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Selector etiqueta="Modalidad" value={modalidad} onChange={(e) => setModalidad(e.target.value as 'evento' | 'iguala')} opciones={[{ valor: 'evento', texto: 'Por evento' }, { valor: 'iguala', texto: 'Iguala mensual' }]} />
        {modalidad === 'iguala' && <Campo etiqueta="Correctivos incluidos" type="number" min={0} value={folios} onChange={(e) => setFolios(e.target.value)} />}
      </div>
      <table className="w-full text-sm">
        <thead className="text-xs text-slate-500">
          <tr><th className="text-left">Severidad</th><th>Respuesta (h)</th><th>Resolución (h)</th><th>Penalización %</th></tr>
        </thead>
        <tbody>
          {NIVELES.map(({ nivel, nombre: n }) => (
            <tr key={nivel}>
              <td className="py-1 pr-2 font-medium">{n}</td>
              {(['resp', 'resol', 'pen'] as const).map((k) => (
                <td key={k} className="px-1 py-1">
                  <input
                    aria-label={`${n} ${k}`}
                    type="number"
                    min={k === 'pen' ? 0 : 1}
                    max={k === 'pen' ? 100 : 4320}
                    value={slas[nivel][k]}
                    onChange={(e) => setSlas({ ...slas, [nivel]: { ...slas[nivel], [k]: e.target.value } })}
                    className="w-full rounded border border-slate-300 px-2 py-1"
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!soloLectura && <Boton className="w-full" onClick={() => void guardar()}>Guardar contrato</Boton>}
    </fieldset>
  )
}
