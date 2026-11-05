import { useState } from 'react'
import { Aviso, Boton, Campo, Modal, Tabla, Tarjeta } from '../../../components/ui'
import { useRecurso } from '../../../hooks/useRecurso'
import { api, mensajeDeError } from '../../../services/api'
import type { Severidad } from '../../../types/api'
import { useAmbito } from '../Catalogos'

export function Severidades() {
  const ambito = useAmbito()
  const { datos, error, recargar } = useRecurso<Severidad[]>('/catalogos/severidades', ambito.params)
  const [editar, setEditar] = useState<Severidad | null>(null)
  return (
    <Tarjeta titulo="Niveles de severidad" >
      <p className="mb-3 text-sm text-slate-600">Los 5 niveles del prestador. Los tiempos son de referencia; los contractuales se fijan en cada contrato.</p>
      {error && <Aviso>{error}</Aviso>}
      <Tabla
        filas={datos ?? []}
        columnas={[
          { titulo: 'Orden', celda: (n) => n.orden },
          { titulo: 'Nivel', celda: (n) => <span className="flex items-center gap-2"><span className="h-4 w-4 rounded-full" style={{ background: n.color_hex }} /> {n.nombre} <code className="text-xs text-slate-400">{n.clave}</code></span> },
          { titulo: 'Respuesta', celda: (n) => `${n.tiempo_respuesta_horas} h` },
          { titulo: 'Resolución', celda: (n) => `${n.tiempo_resolucion_horas} h` },
          ...(ambito.puedeEditarPrestador ? [{ titulo: '', celda: (n: Severidad) => <Boton variante="fantasma" onClick={() => setEditar(n)}>Editar</Boton> }] : []),
        ]}
      />
      <Modal titulo={`Editar ${editar?.nombre ?? ''}`} abierto={editar !== null} alCerrar={() => setEditar(null)}>
        {editar && <FormularioSeveridad nivel={editar} alGuardar={async () => { setEditar(null); await recargar() }} />}
      </Modal>
    </Tarjeta>
  )
}

function FormularioSeveridad({ nivel, alGuardar }: { nivel: Severidad; alGuardar: () => Promise<void> }) {
  const ambito = useAmbito()
  const [f, setF] = useState({ nombre: nivel.nombre, color_hex: nivel.color_hex, tiempo_respuesta_horas: String(nivel.tiempo_respuesta_horas), tiempo_resolucion_horas: String(nivel.tiempo_resolucion_horas) })
  const [error, setError] = useState<string | null>(null)
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void (async () => {
      try {
        await api(`/catalogos/severidades/${nivel.id}`, { metodo: 'PATCH', params: ambito.params, cuerpo: {
          nombre: f.nombre, color_hex: f.color_hex, tiempo_respuesta_horas: Number(f.tiempo_respuesta_horas), tiempo_resolucion_horas: Number(f.tiempo_resolucion_horas) } })
        await alGuardar()
      } catch (err) { setError(mensajeDeError(err)) }
    })() }}>
      {error && <Aviso>{error}</Aviso>}
      <Campo etiqueta="Nombre" name="nombre" value={f.nombre} onChange={(e) => setF({ ...f, nombre: e.target.value })} />
      <Campo etiqueta="Color" name="color_hex" type="color" value={f.color_hex} onChange={(e) => setF({ ...f, color_hex: e.target.value })} />
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Respuesta (h)" name="resp" type="number" min={1} max={4320} value={f.tiempo_respuesta_horas} onChange={(e) => setF({ ...f, tiempo_respuesta_horas: e.target.value })} />
        <Campo etiqueta="Resolución (h)" name="resol" type="number" min={1} max={4320} value={f.tiempo_resolucion_horas} onChange={(e) => setF({ ...f, tiempo_resolucion_horas: e.target.value })} />
      </div>
      <Boton type="submit" className="w-full">Guardar</Boton>
    </form>
  )
}
