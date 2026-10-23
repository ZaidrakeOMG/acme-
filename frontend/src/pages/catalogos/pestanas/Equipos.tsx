import { useState } from 'react'
import { Buscador } from '../../../components/Buscador'
import { Aviso, Boton, Campo, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../../components/ui'
import { useRecurso } from '../../../hooks/useRecurso'
import { api, mensajeDeError } from '../../../services/api'
import type { Contrato, Equipo, FamiliaEquipo, TipoEquipo, UnidadNegocio } from '../../../types/api'
import { useAmbito } from '../Catalogos'

export function Equipos() {
  const ambito = useAmbito()
  const [unId, setUnId] = useState('')
  const [q, setQ] = useState('')
  const [soloContrato, setSoloContrato] = useState(false)
  const unidades = useRecurso<UnidadNegocio[]>('/unidades-negocio', { tenant_id: ambito.params.tenant_id })
  const { datos, error, recargar } = useRecurso<Equipo[]>('/catalogos/equipos', {
    ...ambito.params, un_id: unId || undefined, q: q || undefined, con_contrato: soloContrato ? 'true' : undefined,
  })
  const [editar, setEditar] = useState<Equipo | 'nuevo' | null>(null)
  const puedeEditar = ambito.puedeEditarTenant || ambito.rol === 'admin_un'
  const nombreUn = (id: string) => unidades.datos?.find((u) => u.id === id)?.nombre ?? id.slice(0, 8)

  return (
    <Tarjeta
      titulo="Equipos"
      acciones={
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label="Unidad de negocio" value={unId} onChange={(e) => setUnId(e.target.value)} className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm">
            <option value="">Todas las UNs</option>
            {(unidades.datos ?? []).map((u) => <option key={u.id} value={u.id}>{u.codigo} · {u.nombre}</option>)}
          </select>
          <Buscador etiqueta="Buscar equipo" placeholder="Código, nombre o serie" alBuscar={setQ} />
          <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={soloContrato} onChange={(e) => setSoloContrato(e.target.checked)} /> Solo con contrato</label>
          {puedeEditar && <Boton onClick={() => setEditar('nuevo')}>Nuevo equipo</Boton>}
        </div>
      }
    >
      {error && <Aviso>{error}</Aviso>}
      <Tabla
        filas={datos ?? []}
        columnas={[
          { titulo: 'Código', celda: (e) => <span className="font-mono text-xs">{e.codigo}</span> },
          { titulo: 'Equipo', celda: (e) => <><p className="font-medium">{e.nombre}</p><p className="text-xs text-slate-500">{[e.marca, e.modelo, e.numero_serie].filter(Boolean).join(' · ')}</p></> },
          { titulo: 'UN', celda: (e) => nombreUn(e.un_id) },
          { titulo: 'Contrato', celda: (e) => (e.con_contrato_activo ? <Insignia tono="ok">Activo</Insignia> : <Insignia tono="alerta">Sin contrato</Insignia>) },
          { titulo: 'Garantía', celda: (e) => (e.en_garantia ? <Insignia tono="acento">Hasta {e.garantia_vigente_hasta}</Insignia> : <span className="text-xs text-slate-400">—</span>) },
          ...(puedeEditar ? [{ titulo: '', celda: (e: Equipo) => <Boton variante="fantasma" onClick={() => setEditar(e)}>Editar</Boton> }] : []),
        ]}
      />
      <Modal titulo={editar === 'nuevo' ? 'Nuevo equipo' : 'Editar equipo'} abierto={editar !== null} alCerrar={() => setEditar(null)}>
        {editar && <FormularioEquipo equipo={editar === 'nuevo' ? null : editar} unidades={unidades.datos ?? []} alGuardar={async () => { setEditar(null); await recargar() }} />}
      </Modal>
    </Tarjeta>
  )
}

function FormularioEquipo({ equipo, unidades, alGuardar }: { equipo: Equipo | null; unidades: UnidadNegocio[]; alGuardar: () => Promise<void> }) {
  const ambito = useAmbito()
  const familias = useRecurso<FamiliaEquipo[]>('/catalogos/familias-equipo', ambito.params)
  const contratos = useRecurso<Contrato[]>('/contratos', { tenant_id: ambito.params.tenant_id })
  const [familiaId, setFamiliaId] = useState(equipo?.familia_id ?? '')
  const tipos = useRecurso<TipoEquipo[]>(familiaId ? '/catalogos/tipos-equipo' : null, { ...ambito.params, familia_id: familiaId || undefined })
  const [f, setF] = useState({
    un_id: equipo?.un_id ?? unidades[0]?.id ?? '', tipo_equipo_id: equipo?.tipo_equipo_id ?? '', codigo: equipo?.codigo ?? '', nombre: equipo?.nombre ?? '',
    marca: equipo?.marca ?? '', modelo: equipo?.modelo ?? '', numero_serie: equipo?.numero_serie ?? '', fecha_instalacion: equipo?.fecha_instalacion ?? '',
    valor_reposicion: equipo?.valor_reposicion ?? '', garantia_vigente_hasta: equipo?.garantia_vigente_hasta ?? '', contrato_id: equipo?.contrato_id ?? '',
    estado: equipo?.estado ?? 'activo', notas: equipo?.notas ?? '',
  })
  const [error, setError] = useState<string | null>(null)
  const campo = (k: keyof typeof f) => ({ name: k, value: f[k], onChange: (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value }) })

  async function guardar() {
    setError(null)
    const cuerpo = {
      ...f, marca: f.marca || null, modelo: f.modelo || null, numero_serie: f.numero_serie || null, fecha_instalacion: f.fecha_instalacion || null,
      valor_reposicion: f.valor_reposicion || null, garantia_vigente_hasta: f.garantia_vigente_hasta || null, contrato_id: f.contrato_id || null,
    }
    try {
      if (equipo) await api(`/catalogos/equipos/${equipo.id}`, { metodo: 'PATCH', cuerpo })
      else await api('/catalogos/equipos', { metodo: 'POST', params: ambito.params, cuerpo: { ...cuerpo, estado: undefined } })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void guardar() }}>
      {error && <Aviso>{error}</Aviso>}
      <Selector etiqueta="Unidad de negocio" name="un_id" value={f.un_id} onChange={(e) => setF({ ...f, un_id: e.target.value })}
                opciones={unidades.map((u) => ({ valor: u.id, texto: `${u.codigo} · ${u.nombre}` }))} />
      <div className="grid grid-cols-2 gap-3">
        <Selector etiqueta="Familia" name="familia" value={familiaId} onChange={(e) => { setFamiliaId(e.target.value); setF({ ...f, tipo_equipo_id: '' }) }}
                  opciones={[{ valor: '', texto: 'Selecciona…' }, ...(familias.datos ?? []).map((x) => ({ valor: x.id, texto: x.nombre }))]} />
        <Selector etiqueta="Tipo de equipo" name="tipo_equipo_id" value={f.tipo_equipo_id} onChange={(e) => setF({ ...f, tipo_equipo_id: e.target.value })}
                  opciones={[{ valor: '', texto: familiaId ? 'Selecciona…' : 'Elige familia' }, ...(tipos.datos ?? []).map((x) => ({ valor: x.id, texto: x.nombre }))]} />
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Campo etiqueta="Código" required {...campo('codigo')} />
        <div className="col-span-2"><Campo etiqueta="Nombre" required {...campo('nombre')} /></div>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Campo etiqueta="Marca" {...campo('marca')} />
        <Campo etiqueta="Modelo" {...campo('modelo')} />
        <Campo etiqueta="Serie" {...campo('numero_serie')} />
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Campo etiqueta="Instalación" type="date" {...campo('fecha_instalacion')} />
        <Campo etiqueta="Valor de reposición" type="number" min={0} {...campo('valor_reposicion')} />
        <Campo etiqueta="Garantía hasta" type="date" {...campo('garantia_vigente_hasta')} />
      </div>
      <Selector etiqueta="Contrato específico (vacío = cobertura de todas las UN)" name="contrato_id" value={f.contrato_id} onChange={(e) => setF({ ...f, contrato_id: e.target.value })}
                opciones={[{ valor: '', texto: 'Cobertura general del tenant' }, ...(contratos.datos ?? []).map((c) => ({ valor: c.id, texto: `${c.nombre} (${c.fecha_inicio} → ${c.fecha_fin})` }))]} />
      {equipo && (
        <Selector etiqueta="Estado" name="estado" value={f.estado} onChange={(e) => setF({ ...f, estado: e.target.value as Equipo['estado'] })}
                  opciones={[{ valor: 'activo', texto: 'Activo' }, { valor: 'inactivo', texto: 'Inactivo' }, { valor: 'baja', texto: 'Baja' }]} />
      )}
      <Boton type="submit" className="w-full">Guardar equipo</Boton>
    </form>
  )
}
