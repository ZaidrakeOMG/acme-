import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { mensajeDeError } from '../../services/api'
import { abrirBlob } from '../../services/minutas'
import {
  archivoReporte, borrarProgramado, crearProgramado, editarProgramado, generarReporte, reportesGenerados,
  reportesProgramados,
} from '../../services/sla'
import type { Usuario } from '../../types/api'
import type { FormatoReporte, PeriodicidadReporte, ReporteGenerado, ReporteProgramado } from '../../types/sla'
import { NOMBRE_PERIODICIDAD, PLANTILLAS_REPORTE } from '../../types/sla'
import { fecha as fmtFecha } from '../folios/comunes'

function primeroDelMes() {
  const h = new Date()
  return new Date(h.getFullYear(), h.getMonth(), 1).toISOString().slice(0, 10)
}

/** Reportes ejecutivos: generar ahora en PDF o Excel y programar el envío por correo (ACT-8.4). P10. */
export function Reportes() {
  const { usuario } = useAuth()
  const [tipo, setTipo] = useState('cliente')
  const [formato, setFormato] = useState<FormatoReporte>('pdf')
  const [desde, setDesde] = useState(primeroDelMes())
  const [hasta, setHasta] = useState(new Date().toISOString().slice(0, 10))
  const [generados, setGenerados] = useState<ReporteGenerado[]>([])
  const [programados, setProgramados] = useState<ReporteProgramado[]>([])
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [generando, setGenerando] = useState(false)
  const [nuevo, setNuevo] = useState(false)
  const usuarios = useRecurso<Usuario[]>('/usuarios')

  const cargar = useCallback(async () => {
    try {
      setGenerados(await reportesGenerados({ limite: 20 }))
      setProgramados(await reportesProgramados())
    } catch (e) { setError(mensajeDeError(e)) }
  }, [])
  useEffect(() => { void cargar() }, [cargar])

  async function generar() {
    setError(null)
    setGenerando(true)
    try {
      const blob = await generarReporte({ tipo_reporte: tipo, formato, desde, hasta })
      abrirBlob(blob, `${tipo}-${desde}-${hasta}.${formato === 'pdf' ? 'pdf' : 'xlsx'}`)
      setAviso('Reporte generado y descargado')
      await cargar()
    } catch (e) { setError(mensajeDeError(e)) } finally { setGenerando(false) }
  }

  async function ejecutar(fn: () => Promise<unknown>, texto: string) {
    setError(null)
    try { await fn(); setNuevo(false); setAviso(texto); await cargar() } catch (e) { setError(mensajeDeError(e)) }
  }
  if (!usuario) return null

  return (
    <div>
      <Encabezado titulo="Reportes ejecutivos"
        descripcion="Plantillas por destinatario, generadas en el servidor en PDF o Excel con el logo y los colores del prestador. Los programados se envían por correo según su periodicidad."
        acciones={<Link className="text-sm text-primario underline" to="/bi">Volver al tablero</Link>} />
      {error && <Aviso>{error}</Aviso>}
      {aviso && <Aviso tipo="exito">{aviso}</Aviso>}

      <Tarjeta titulo="Generar ahora">
        <div className="flex flex-wrap items-end gap-2" data-testid="generar-reporte">
          <Selector etiqueta="Plantilla" value={tipo} onChange={(e) => setTipo(e.target.value)}
            opciones={PLANTILLAS_REPORTE.map((p) => ({ valor: p.clave, texto: `${p.nombre} (${p.destinatario})` }))} />
          <Selector etiqueta="Formato" value={formato} onChange={(e) => setFormato(e.target.value as FormatoReporte)}
            opciones={[{ valor: 'pdf', texto: 'PDF' }, { valor: 'excel', texto: 'Excel' }]} />
          <Campo etiqueta="Desde" type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
          <Campo etiqueta="Hasta" type="date" value={hasta} onChange={(e) => setHasta(e.target.value)} />
          <Boton disabled={generando} onClick={() => void generar()}>{generando ? 'Generando…' : 'Generar y descargar'}</Boton>
        </div>
      </Tarjeta>

      <div className="mt-4">
        <Tarjeta titulo="Reportes programados" acciones={<Boton onClick={() => setNuevo(true)}>Programar</Boton>}>
          <div data-testid="programados">
            <Tabla filas={programados} vacio="Sin reportes programados" columnas={[
              { titulo: 'Nombre', celda: (p) => <span className="text-sm">{p.nombre}</span> },
              { titulo: 'Plantilla', celda: (p) => PLANTILLAS_REPORTE.find((x) => x.clave === p.tipo_reporte)?.nombre ?? p.tipo_reporte },
              { titulo: 'Formato', celda: (p) => p.formato === 'pdf' ? 'PDF' : 'Excel' },
              { titulo: 'Periodicidad', celda: (p) => `${NOMBRE_PERIODICIDAD[p.periodicidad]} · ${p.dia_hora}` },
              { titulo: 'Destinatarios', celda: (p) => p.destinatarios_json.length },
              { titulo: 'Último envío', celda: (p) => <span className="text-xs">{p.ultimo_envio_at ? fmtFecha(p.ultimo_envio_at) : 'pendiente'}</span> },
              { titulo: 'Estado', celda: (p) => p.activo ? <Insignia tono="ok">Activo</Insignia> : <Insignia>Pausado</Insignia> },
              { titulo: 'Acciones', celda: (p) => (
                <div className="flex flex-wrap gap-1">
                  <Boton variante="secundario" onClick={() => void ejecutar(() => editarProgramado(p.id, { activo: !p.activo }), p.activo ? 'Programación pausada' : 'Programación reactivada')}>
                    {p.activo ? 'Pausar' : 'Reactivar'}
                  </Boton>
                  <Boton variante="peligro" onClick={() => void ejecutar(() => borrarProgramado(p.id), 'Programación eliminada')}>Quitar</Boton>
                </div>
              ) },
            ]} />
          </div>
        </Tarjeta>
      </div>

      <div className="mt-4">
        <Tarjeta titulo="Historial de reportes generados">
          <div data-testid="generados">
            <Tabla filas={generados} vacio="Sin reportes generados" columnas={[
              { titulo: 'Plantilla', celda: (r) => PLANTILLAS_REPORTE.find((x) => x.clave === r.tipo_reporte)?.nombre ?? r.tipo_reporte },
              { titulo: 'Formato', celda: (r) => r.formato === 'pdf' ? 'PDF' : 'Excel' },
              { titulo: 'Período', celda: (r) => <span className="text-xs">{String((r as unknown as { filtros_json?: Record<string, string> }).filtros_json?.desde ?? '')} a {String((r as unknown as { filtros_json?: Record<string, string> }).filtros_json?.hasta ?? '')}</span> },
              { titulo: 'Filas', celda: (r) => r.filas },
              { titulo: 'Generación', celda: (r) => <span className="text-xs">{r.ms_generacion ?? '—'} ms</span> },
              { titulo: 'Fecha', celda: (r) => <span className="text-xs">{fmtFecha(r.generado_at)}</span> },
              { titulo: 'Origen', celda: (r) => r.programado_id ? <Insignia>programado</Insignia> : <Insignia tono="acento">manual</Insignia> },
              { titulo: '', celda: (r) => (
                <button className="text-xs text-primario underline"
                  onClick={() => void archivoReporte(r.id).then((b) => abrirBlob(b, r.archivo_key.split('/').pop() ?? 'reporte'))
                    .catch((e) => setError(mensajeDeError(e)))}>Descargar</button>
              ) },
            ]} />
          </div>
        </Tarjeta>
      </div>

      {nuevo && <FormProgramado usuarios={usuarios.datos ?? []} alCerrar={() => setNuevo(false)}
        alGuardar={(cuerpo) => ejecutar(() => crearProgramado(cuerpo), 'Reporte programado')} />}
    </div>
  )
}

function FormProgramado({ usuarios, alCerrar, alGuardar }: {
  usuarios: Usuario[]
  alCerrar: () => void
  alGuardar: (cuerpo: Record<string, unknown>) => Promise<void>
}) {
  const [d, setD] = useState({
    nombre: '', tipo_reporte: 'cliente', formato: 'pdf' as FormatoReporte,
    periodicidad: 'mensual' as PeriodicidadReporte, dia_hora: '1 08:00',
  })
  const [destinatarios, setDestinatarios] = useState<Set<string>>(new Set())
  const ejemplos: Record<PeriodicidadReporte, string> = {
    diaria: '22:30', semanal: 'lunes 08:00', mensual: '1 08:00',
  }
  return (
    <Modal titulo="Programar un reporte" abierto alCerrar={alCerrar}>
      <div className="space-y-3" data-testid="form-programado">
        <Campo etiqueta="Nombre" value={d.nombre} onChange={(e) => setD({ ...d, nombre: e.target.value })} />
        <Selector etiqueta="Plantilla" value={d.tipo_reporte} onChange={(e) => setD({ ...d, tipo_reporte: e.target.value })}
          opciones={PLANTILLAS_REPORTE.map((p) => ({ valor: p.clave, texto: p.nombre }))} />
        <div className="grid gap-2 sm:grid-cols-2">
          <Selector etiqueta="Formato" value={d.formato} onChange={(e) => setD({ ...d, formato: e.target.value as FormatoReporte })}
            opciones={[{ valor: 'pdf', texto: 'PDF' }, { valor: 'excel', texto: 'Excel' }]} />
          <Selector etiqueta="Periodicidad" value={d.periodicidad}
            onChange={(e) => {
              const p = e.target.value as PeriodicidadReporte
              setD({ ...d, periodicidad: p, dia_hora: ejemplos[p] })
            }}
            opciones={(Object.keys(NOMBRE_PERIODICIDAD) as PeriodicidadReporte[]).map((p) => ({ valor: p, texto: NOMBRE_PERIODICIDAD[p] }))} />
        </div>
        <Campo etiqueta={`Día y hora (p. ej. «${ejemplos[d.periodicidad]}»)`} value={d.dia_hora}
          onChange={(e) => setD({ ...d, dia_hora: e.target.value })} />
        <fieldset className="text-sm">
          <legend className="mb-1 font-medium text-slate-700">Destinatarios</legend>
          <div className="max-h-40 overflow-y-auto">
            {usuarios.map((u) => (
              <label key={u.id} className="flex items-center gap-2 text-xs">
                <input type="checkbox" checked={destinatarios.has(u.id)}
                  onChange={(e) => { const s = new Set(destinatarios); if (e.target.checked) s.add(u.id); else s.delete(u.id); setDestinatarios(s) }} />
                {u.nombre} · {u.rol}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex gap-2">
          <Boton disabled={d.nombre.trim().length < 2} onClick={() => void alGuardar({
            nombre: d.nombre, tipo_reporte: d.tipo_reporte, formato: d.formato, periodicidad: d.periodicidad,
            dia_hora: d.dia_hora, destinatarios_json: [...destinatarios], filtros_json: {},
          })}>Programar</Boton>
          <Boton variante="secundario" onClick={alCerrar}>Cancelar</Boton>
        </div>
      </div>
    </Modal>
  )
}
