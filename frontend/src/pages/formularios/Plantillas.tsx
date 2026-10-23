import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Renderizador } from '../../components/formularios/Renderizador'
import { Aviso, Boton, Encabezado, Insignia, Modal, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import type { Formulario } from '../../types/formularios'
import { camposDe } from '../../types/formularios'

/** Repositorio de plantillas base (§6.8.3c): vista previa y clonación con un clic. */
export function Plantillas() {
  const { usuario } = useAuth()
  const navegar = useNavigate()
  const { datos, error } = useRecurso<Formulario[]>('/formularios/plantillas')
  const [previa, setPrevia] = useState<Formulario | null>(null)
  const [valores, setValores] = useState<Record<string, unknown>>({})
  const [aviso, setAviso] = useState<string | null>(null)
  const puedeClonar = usuario?.rol === 'superadmin' || usuario?.rol === 'admin_prestador'

  async function clonar(p: Formulario) {
    setAviso(null)
    try {
      const f = await api<Formulario>(`/formularios/${p.id}/clonar`, { metodo: 'POST', cuerpo: { nombre: p.nombre } })
      navegar(`/formularios/constructor/${f.id}`)
    } catch (e) {
      setAviso(mensajeDeError(e))
    }
  }

  return (
    <div>
      <Encabezado titulo="Repositorio de plantillas" descripcion="Plantillas base diseñadas por el superadmin. Clónalas y adáptalas para todos tus clientes o para uno específico."
                  acciones={<Link to="/formularios"><Boton variante="secundario">Volver</Boton></Link>} />
      {(error || aviso) && <Aviso>{error ?? aviso}</Aviso>}
      <div className="grid gap-4 md:grid-cols-2">
        {(datos ?? []).map((p) => (
          <Tarjeta key={p.id} titulo={p.nombre} acciones={<Insignia tono="acento">{p.tipo.replace('_', ' ')}</Insignia>}>
            <p className="mb-2 text-sm text-slate-600">{p.descripcion}</p>
            <p className="mb-3 text-xs text-slate-500">{p.esquema_json.secciones.length} secciones · {camposDe(p.esquema_json).length} campos · {new Set(camposDe(p.esquema_json).map((c) => c.tipo)).size} tipos</p>
            <div className="flex gap-2">
              <Boton variante="secundario" onClick={() => { setPrevia(p); setValores({}) }}>Vista previa</Boton>
              {puedeClonar && <Boton onClick={() => void clonar(p)} data-testid={`clonar-${p.id}`}>Clonar</Boton>}
            </div>
          </Tarjeta>
        ))}
      </div>
      <Modal titulo={previa?.nombre ?? ''} abierto={previa !== null} alCerrar={() => setPrevia(null)}>
        {previa && <Renderizador esquema={previa.esquema_json} respuestas={valores} onChange={setValores} sinCatalogos />}
      </Modal>
    </div>
  )
}
