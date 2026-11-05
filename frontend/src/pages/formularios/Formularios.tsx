import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Aviso, Boton, Encabezado, Insignia, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import type { Formulario } from '../../types/formularios'

const NOMBRE_TIPO: Record<string, string> = { captura_operador: 'Captura (operador)', atencion_tecnico: 'Atención (técnico)', preventivo: 'Preventivo', trabajo_especial: 'Trabajo especial', encuesta: 'Encuesta', libre: 'Libre' }

/** Lista de formularios del prestador (o de todos, para superadmin) con filtros por tipo, alcance y estado. */
export function Formularios() {
  const { usuario } = useAuth()
  const navegar = useNavigate()
  const [tipo, setTipo] = useState('')
  const [alcance, setAlcance] = useState('')
  const [estado, setEstado] = useState('')
  const { datos, error, recargar } = useRecurso<Formulario[]>('/formularios', { tipo: tipo || undefined, alcance: alcance || undefined, estado: estado || undefined, plantillas: 'false' })
  const [aviso, setAviso] = useState<string | null>(null)
  const disena = usuario?.rol === 'superadmin' || usuario?.rol === 'admin_prestador'

  async function accion(f: Formulario, ruta: string) {
    setAviso(null)
    try {
      await api(`/formularios/${f.id}/${ruta}`, { metodo: 'POST', cuerpo: ruta === 'publicar' ? { notas_version: '' } : {} })
      await recargar()
    } catch (e) {
      setAviso(mensajeDeError(e))
    }
  }

  const selector = (etiqueta: string, valor: string, set: (v: string) => void, opciones: [string, string][]) => (
    <select aria-label={etiqueta} value={valor} onChange={(e) => set(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
      <option value="">{etiqueta}</option>
      {opciones.map(([v, t]) => <option key={v} value={v}>{t}</option>)}
    </select>
  )

  return (
    <div>
      <Encabezado titulo="Formularios dinámicos" descripcion="Diseña, versiona, asigna y publica formularios con los 22 tipos de campo."
                  acciones={<div className="flex gap-2">
                    <Link to="/formularios/plantillas"><Boton variante="secundario">Plantillas</Boton></Link>
                    {disena && <Link to="/formularios/constructor"><Boton>Nuevo formulario</Boton></Link>}
                  </div>} />
      <Tarjeta acciones={<div className="flex flex-wrap gap-2">
        {selector('Todos los tipos', tipo, setTipo, Object.entries(NOMBRE_TIPO))}
        {selector('Todo alcance', alcance, setAlcance, [['global', 'Global'], ['tenant', 'Por cliente']])}
        {selector('Todo estado', estado, setEstado, [['borrador', 'Borrador'], ['publicado', 'Publicado'], ['archivado', 'Archivado']])}
      </div>}>
        {(error || aviso) && <Aviso>{error ?? aviso}</Aviso>}
        <Tabla
          filas={datos ?? []}
          columnas={[
            { titulo: 'Formulario', celda: (f) => <><p className="font-medium">{f.nombre}</p><p className="text-xs text-slate-500">{f.descripcion}</p></> },
            { titulo: 'Tipo', celda: (f) => NOMBRE_TIPO[f.tipo] ?? f.tipo },
            { titulo: 'Alcance', celda: (f) => (f.tenant_id ? <Insignia tono="acento">Cliente</Insignia> : <Insignia>Global</Insignia>) },
            { titulo: 'Rol destino', celda: (f) => <span className="text-xs">{f.rol_destino.join(', ')}</span> },
            { titulo: 'Versión', celda: (f) => <span className="text-xs">{f.numero_version_publicada ? `v${f.numero_version_publicada} publicada` : '—'}{f.version_actual !== f.numero_version_publicada ? ` · v${f.version_actual} borrador` : ''}</span> },
            { titulo: 'Estado', celda: (f) => <Insignia tono={f.estado === 'publicado' ? 'ok' : f.estado === 'borrador' ? 'alerta' : 'neutro'}>{f.estado}</Insignia> },
            { titulo: '', celda: (f) => (
              <div className="flex flex-wrap gap-1">
                <Boton variante="fantasma" onClick={() => navegar(`/formularios/constructor/${f.id}`)}>{f.puede_editar ? 'Editar' : 'Ver'}</Boton>
                {f.puede_editar && f.version_actual !== f.numero_version_publicada && f.estado !== 'archivado' && <Boton variante="fantasma" onClick={() => void accion(f, 'publicar')}>Publicar v{f.version_actual}</Boton>}
                {disena && f.estado !== 'archivado' && <Boton variante="fantasma" onClick={() => void accion(f, 'clonar')}>Clonar</Boton>}
                {disena && f.puede_editar && f.estado !== 'archivado' && <Boton variante="fantasma" onClick={() => void accion(f, 'archivar')}>Archivar</Boton>}
              </div>
            ) },
          ]}
        />
      </Tarjeta>
    </div>
  )
}
