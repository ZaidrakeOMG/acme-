import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { mensajeDeError } from '../../services/api'
import {
  crearLlaveApi, crearTipoMedidor, editarTipoMedidor, lecturasPorRevisar, llavesApi, revisarLectura, revocarLlaveApi,
  tiposMedidor,
} from '../../services/medidores'
import type { CategoriaMedidor, LlaveApi, PendienteRevision, TipoMedidor } from '../../types/medidores'
import { CATEGORIAS, NOMBRE_METODO, ROLES_LLAVES_API, ROLES_REVISAN_LECTURAS, formatoValor } from '../../types/medidores'
import { fecha as fmtFecha } from '../folios/comunes'

type Vista = 'revisar' | 'tipos' | 'llaves'

/**
 * Módulo de medidores de activos (§6.9.2). Tres cosas que no caben en la ficha del equipo:
 * - **Lecturas por revisar**: las anómalas (retroceso o salto) esperando al Despachador o al Admin prestador.
 *   Mientras no se resuelvan no disparan planes de mantenimiento.
 * - **Catálogo de tipos**: los seis de §6.9.2 vienen como catálogo global; aquí se ven y se agregan los propios.
 * - **Llaves de API**: para que el SCADA o el ERP del cliente manden lecturas sin usuario humano.
 */
export function Medidores() {
  const { usuario } = useAuth()
  const puedeRevisar = !!usuario && ROLES_REVISAN_LECTURAS.includes(usuario.rol)
  const puedeLlaves = !!usuario && ROLES_LLAVES_API.includes(usuario.rol)
  const [vista, setVista] = useState<Vista>(puedeRevisar ? 'revisar' : 'tipos')
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)

  const [pendientes, setPendientes] = useState<PendienteRevision[] | null>(null)
  const [tipos, setTipos] = useState<TipoMedidor[] | null>(null)
  const [llaves, setLlaves] = useState<LlaveApi[] | null>(null)
  const [revisando, setRevisando] = useState<PendienteRevision | null>(null)
  const [razon, setRazon] = useState('')
  const [nuevoTipo, setNuevoTipo] = useState(false)
  const [tipoNuevo, setTipoNuevo] = useState<{ nombre: string; unidad: string; categoria: CategoriaMedidor; decimales: string; factor: string; requiere_foto: boolean; permite_estimacion: boolean }>(
    { nombre: '', unidad: '', categoria: 'horas', decimales: '0', factor: '3', requiere_foto: false, permite_estimacion: true },
  )
  const [nombreLlave, setNombreLlave] = useState('')
  const [secreto, setSecreto] = useState<string | null>(null)

  const cargar = useCallback(async () => {
    try {
      if (vista === 'revisar' && puedeRevisar) setPendientes(await lecturasPorRevisar())
      if (vista === 'tipos') setTipos(await tiposMedidor())
      if (vista === 'llaves' && puedeLlaves) setLlaves(await llavesApi())
    } catch (e) { setError(mensajeDeError(e)) }
  }, [vista, puedeRevisar, puedeLlaves])
  useEffect(() => { void cargar() }, [cargar])

  async function resolver(aprobar: boolean) {
    if (!revisando) return
    try {
      const r = await revisarLectura(revisando.id, aprobar, razon)
      const generados = r.folios_generados.length
      setAviso(aprobar
        ? `Lectura aprobada: el medidor de ${revisando.equipo} quedó en ${formatoValor(r.lectura.valor, 2, revisando.unidad)}`
          + (generados ? `, y generó ${generados} folio(s) preventivo(s)` : '')
        : `Lectura rechazada: el medidor de ${revisando.equipo} no se movió`)
      setRevisando(null)
      setRazon('')
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) }
  }

  async function guardarTipo() {
    try {
      await crearTipoMedidor({
        nombre: tipoNuevo.nombre, unidad: tipoNuevo.unidad, categoria: tipoNuevo.categoria,
        decimales: Number(tipoNuevo.decimales), factor_salto_maximo: tipoNuevo.factor,
        requiere_foto: tipoNuevo.requiere_foto, permite_estimacion: tipoNuevo.permite_estimacion,
      })
      setAviso(`Tipo de medidor «${tipoNuevo.nombre}» creado`)
      setNuevoTipo(false)
      setTipoNuevo({ ...tipoNuevo, nombre: '', unidad: '' })
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) }
  }

  async function nuevaLlave() {
    try {
      const r = await crearLlaveApi(nombreLlave)
      setSecreto(r.secreto)
      setNombreLlave('')
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) }
  }

  if (!usuario) return null
  const vistas: Vista[] = [...(puedeRevisar ? ['revisar' as const] : []), 'tipos', ...(puedeLlaves ? ['llaves' as const] : [])]
  const titulos: Record<Vista, string> = { revisar: 'Lecturas por revisar', tipos: 'Tipos de medidor', llaves: 'Llaves de API' }

  return (
    <div>
      <Encabezado
        titulo="Medidores de activos"
        descripcion="Los planes de mantenimiento por uso se apoyan en lo que marcan los medidores. Una lectura que retrocede o que salta más de lo esperado queda aquí, en revisión, y no dispara nada hasta que alguien la resuelve."
        acciones={<div className="flex gap-1">{vistas.map((v) => (
          <button key={v} className={`rounded-lg px-3 py-1.5 text-sm ${vista === v ? 'bg-primario text-white' : 'border border-slate-300'}`} onClick={() => setVista(v)}>{titulos[v]}</button>
        ))}</div>}
      />
      {error && <div className="mb-3"><Aviso>{error}</Aviso></div>}
      {aviso && <div className="mb-3"><Aviso tipo="exito">{aviso}</Aviso></div>}

      {vista === 'revisar' && (
        <Tarjeta titulo={`Lecturas anómalas (${pendientes?.length ?? 0})`}>
          <Tabla
            vacio="No hay lecturas por revisar: todas las que entraron son coherentes con el uso del equipo."
            filas={pendientes ?? []}
            columnas={[
              { titulo: 'Equipo', celda: (p) => <Link to={`/activos/${p.equipo_id}?vista=medidores`} className="text-primario underline">{p.equipo_codigo} {p.equipo}</Link> },
              { titulo: 'Medidor', celda: (p) => <span>{p.medidor}<span className="block text-xs text-slate-500">{NOMBRE_METODO[p.metodo]}</span></span> },
              { titulo: 'Lectura', celda: (p) => <span className="font-medium">{formatoValor(p.valor, 2, p.unidad)}</span> },
              { titulo: 'Anterior', celda: (p) => <span>{formatoValor(p.valor_anterior, 2, p.unidad)}<span className="block text-xs text-slate-500">{p.fecha_anterior ? fmtFecha(p.fecha_anterior) : ''}</span></span> },
              { titulo: 'Por qué', celda: (p) => <span className="text-xs text-slate-600">{p.motivo}</span> },
              { titulo: 'Capturada', celda: (p) => fmtFecha(p.timestamp) },
              { titulo: '', celda: (p) => <Boton variante="secundario" onClick={() => { setRevisando(p); setRazon('') }}>Revisar</Boton> },
            ]}
          />
        </Tarjeta>
      )}

      {vista === 'tipos' && (
        <Tarjeta titulo="Catálogo de tipos de medidor" acciones={<Boton onClick={() => setNuevoTipo(true)}>Nuevo tipo</Boton>}>
          <Tabla
            filas={tipos ?? []}
            columnas={[
              { titulo: 'Nombre', celda: (t) => <span>{t.nombre}<span className="block text-xs text-slate-500">{t.descripcion}</span></span> },
              { titulo: 'Unidad', celda: (t) => t.unidad },
              { titulo: 'Categoría', celda: (t) => CATEGORIAS.find((c) => c.valor === t.categoria)?.texto ?? t.categoria },
              { titulo: 'Dueño', celda: (t) => (t.prestador_id === null && t.tenant_id === null ? <Insignia tono="acento">Global</Insignia> : t.tenant_id ? <Insignia>Del cliente</Insignia> : <Insignia>Del prestador</Insignia>) },
              { titulo: 'Foto del marcador', celda: (t) => (t.requiere_foto ? 'Obligatoria' : 'Opcional') },
              { titulo: 'Tolerancia de salto', celda: (t) => `${Number(t.factor_salto_maximo)}× el uso diario` },
              { titulo: 'Estimación', celda: (t) => (t.permite_estimacion ? 'Permitida' : 'No permitida') },
              {
                titulo: '', celda: (t) => (t.prestador_id === null && t.tenant_id === null && usuario.rol !== 'superadmin' ? null : (
                  <Boton variante="secundario" onClick={() => void editarTipoMedidor(t.id, { activo: !t.activo }).then(cargar).catch((e) => setError(mensajeDeError(e)))}>
                    {t.activo ? 'Desactivar' : 'Activar'}
                  </Boton>
                )),
              },
            ]}
          />
        </Tarjeta>
      )}

      {vista === 'llaves' && (
        <div className="space-y-3">
          <Tarjeta titulo="Llaves de API para lecturas de medidor">
            <p className="mb-3 text-sm text-slate-600">
              Una llave sirve <strong>solo</strong> para registrar lecturas de medidor de este cliente: con ella no se
              consulta ni se cambia nada más. Se muestra completa una sola vez, porque ACMA solo guarda su huella.
              El formato de las peticiones está en <code>docs/integracion/lecturas_medidor.md</code>.
            </p>
            <div className="flex flex-wrap items-end gap-2">
              <Campo etiqueta="Nombre del sistema que la va a usar" value={nombreLlave} onChange={(e) => setNombreLlave(e.target.value)} placeholder="SCADA planta Torreón" />
              <Boton disabled={nombreLlave.trim().length < 3} onClick={() => void nuevaLlave()}>Crear llave</Boton>
            </div>
            {secreto && (
              <div className="mt-3" data-testid="llave-secreto">
                <Aviso tipo="exito">
                  Cópiala ahora, no se vuelve a mostrar:
                  <code className="mt-1 block break-all rounded bg-white p-2 font-mono text-xs">{secreto}</code>
                </Aviso>
              </div>
            )}
          </Tarjeta>
          <Tarjeta titulo="Llaves emitidas">
            <Tabla
              filas={llaves ?? []}
              columnas={[
                { titulo: 'Nombre', celda: (l) => l.nombre },
                { titulo: 'Prefijo', celda: (l) => <code className="font-mono text-xs">{l.prefijo}…</code> },
                { titulo: 'Permisos', celda: (l) => l.permisos_json.join(', ') },
                { titulo: 'Estado', celda: (l) => (l.activa ? <Insignia tono="ok">Activa</Insignia> : <Insignia tono="alerta">Revocada {l.revocada_at ? fmtFecha(l.revocada_at) : ''}</Insignia>) },
                { titulo: 'Último uso', celda: (l) => (l.ultimo_uso_at ? `${fmtFecha(l.ultimo_uso_at)} (${l.usos} usos)` : 'Nunca') },
                { titulo: '', celda: (l) => (l.activa ? <Boton variante="peligro" onClick={() => void revocarLlaveApi(l.id).then(cargar).catch((e) => setError(mensajeDeError(e)))}>Revocar</Boton> : null) },
              ]}
            />
          </Tarjeta>
        </div>
      )}

      <Modal titulo="Revisar la lectura" abierto={!!revisando} alCerrar={() => setRevisando(null)}>
        {revisando && (
          <div className="space-y-3 text-sm">
            <p>
              <strong>{revisando.equipo_codigo} {revisando.equipo}</strong> · {revisando.medidor}
              <span className="block text-slate-600">
                Se capturó {formatoValor(revisando.valor, 2, revisando.unidad)} y la anterior era {formatoValor(revisando.valor_anterior, 2, revisando.unidad)}.
              </span>
            </p>
            <Aviso tipo="info">{revisando.motivo}</Aviso>
            <p className="text-slate-600">
              Si el marcador se reinició o se cambió el medidor, regístralo primero en la pestaña «Medidores» del
              equipo: al aprobar, el acumulado se recalcula con el estado actual del medidor.
            </p>
            <Campo etiqueta="Razón (obligatoria para rechazar)" value={razon} onChange={(e) => setRazon(e.target.value)} />
            <div className="flex gap-2">
              <Boton onClick={() => void resolver(true)}>Aprobar la lectura</Boton>
              <Boton variante="peligro" disabled={!razon.trim()} onClick={() => void resolver(false)}>Rechazar</Boton>
            </div>
          </div>
        )}
      </Modal>

      <Modal titulo="Nuevo tipo de medidor" abierto={nuevoTipo} alCerrar={() => setNuevoTipo(false)}>
        <div className="space-y-3">
          <Campo etiqueta="Nombre" value={tipoNuevo.nombre} onChange={(e) => setTipoNuevo({ ...tipoNuevo, nombre: e.target.value })} />
          <Campo etiqueta="Unidad (h, ciclos, km, kWh, piezas…)" value={tipoNuevo.unidad} onChange={(e) => setTipoNuevo({ ...tipoNuevo, unidad: e.target.value })} />
          <Selector etiqueta="Categoría" value={tipoNuevo.categoria} opciones={CATEGORIAS.map((c) => ({ valor: c.valor, texto: `${c.texto} — ${c.ejemplo}` }))}
                    onChange={(e) => setTipoNuevo({ ...tipoNuevo, categoria: e.target.value as CategoriaMedidor })} />
          <div className="grid gap-3 sm:grid-cols-2">
            <Campo etiqueta="Decimales" type="number" min={0} max={4} value={tipoNuevo.decimales} onChange={(e) => setTipoNuevo({ ...tipoNuevo, decimales: e.target.value })} />
            <Campo etiqueta="Tolerancia de salto (veces el uso diario)" type="number" min={1} max={100} value={tipoNuevo.factor}
                   onChange={(e) => setTipoNuevo({ ...tipoNuevo, factor: e.target.value })} />
          </div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={tipoNuevo.requiere_foto} onChange={(e) => setTipoNuevo({ ...tipoNuevo, requiere_foto: e.target.checked })} /> Exigir foto del marcador al operador</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={tipoNuevo.permite_estimacion} onChange={(e) => setTipoNuevo({ ...tipoNuevo, permite_estimacion: e.target.checked })} /> Permitir lecturas estimadas</label>
          <Boton disabled={tipoNuevo.nombre.trim().length < 2 || !tipoNuevo.unidad.trim()} onClick={() => void guardarTipo()}>Guardar</Boton>
        </div>
      </Modal>
    </div>
  )
}
