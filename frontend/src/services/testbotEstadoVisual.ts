/** Indicadores honestos de la ÚLTIMA prueba del ACMA TestBot.
 * No son monitoreo en vivo ni certificación de que todo el módulo opera al 100%.
 */
import { useEffect, useState } from 'react'
import type { EstadoModulo, EstadoRecorrido } from './testbotSecuencia'

export const EVENTO_RECORRIDO_TESTBOT = 'acma:testbot-recorrido-actualizado'
export const EVENTO_FORMULARIOS_TESTBOT = 'acma:testbot-formularios-actualizado'

export type TipoIndicador = 'edicion' | 'alta' | 'consulta' | 'pendiente' | 'error' | 'sin_prueba'
export type EstadoIndicador = { tipo: TipoIndicador; etiqueta: string; explicacion: string; comprobadoEn?: string }

export const CLASE_ESTADO: Record<TipoIndicador, string> = {
  edicion: 'border-emerald-300 bg-emerald-100 text-emerald-800',
  alta: 'border-teal-300 bg-teal-100 text-teal-800',
  consulta: 'border-sky-300 bg-sky-100 text-sky-800',
  pendiente: 'border-amber-300 bg-amber-100 text-amber-900',
  error: 'border-rose-300 bg-rose-100 text-rose-800',
  sin_prueba: 'border-slate-300 bg-slate-100 text-slate-600',
}

export function estadoDePrueba(estado?: EstadoModulo | null, comprobadoEn?: string): EstadoIndicador {
  const comun = comprobadoEn ? { comprobadoEn } : {}
  switch (estado) {
    case 'alta_cambio_demo_verificados':
      return { tipo: 'edicion', etiqueta: 'Alta y edición DEMO', explicacion: 'Alta, modificación y relectura de prueba verificadas. Puede haber otros flujos pendientes.', ...comun }
    case 'alta_demo_verificada':
      return { tipo: 'alta', etiqueta: 'Alta DEMO', explicacion: 'Se comprobó el alta de prueba. Otros pasos y permisos pueden quedar pendientes.', ...comun }
    case 'consulta_verificada':
      return { tipo: 'consulta', etiqueta: 'Solo consulta', explicacion: 'El servidor respondió a consultas de prueba; altas, cambios y permisos no están verificados.', ...comun }
    case 'pendiente_funcional':
      return { tipo: 'pendiente', etiqueta: 'Pendiente', explicacion: 'El TestBot necesita una configuración o prueba funcional adicional.', ...comun }
    case 'requiere_otro_rol':
      return { tipo: 'pendiente', etiqueta: 'Requiere otro rol', explicacion: 'Se necesita una cuenta del rol correspondiente; Superadmin no sustituye al Técnico, Operador o Admin prestador.', ...comun }
    case 'error':
      return { tipo: 'error', etiqueta: 'Error de prueba', explicacion: 'Falló la última comprobación del módulo. Revisa el diagnóstico TXT.', ...comun }
    default:
      return { tipo: 'sin_prueba', etiqueta: 'Sin probar', explicacion: 'El recorrido del TestBot no contiene todavía una prueba específica de este apartado.' }
  }
}

export interface IndicadoresTestBot {
  modulos: Record<string, EstadoIndicador>
  formularios: EstadoIndicador
  tieneResultados: boolean
}

const VACIO: IndicadoresTestBot = {
  modulos: {},
  formularios: estadoDePrueba(),
  tieneResultados: false,
}

function datosLocales(usuarioId: string): IndicadoresTestBot {
  if (!usuarioId || typeof localStorage === 'undefined') return VACIO
  const modulos: Record<string, EstadoIndicador> = {}
  let tieneResultados = false
  try {
    const item = JSON.parse(localStorage.getItem('acma.testbot.secuencia.v1.' + usuarioId) || 'null') as Partial<EstadoRecorrido> | null
    for (const r of item?.resultados ?? []) {
      if (!r || typeof r.id !== 'string' || typeof r.estado !== 'string') continue
      modulos[r.id] = estadoDePrueba(r.estado, r.comprobadoEn)
      tieneResultados = true
    }
  } catch {
    // El almacenamiento es local y puede borrarse. No declarar éxito sin información válida.
  }

  let formularios = estadoDePrueba()
  try {
    const p = JSON.parse(localStorage.getItem('acma.testbot.formularios.v2.' + usuarioId) || 'null') as { paso?: unknown } | null
    if (p?.paso === 7) {
      formularios = { tipo: 'edicion', etiqueta: 'Formularios DEMO 7/7',
        explicacion: 'Los siete pasos del formulario DEMO quedaron completados en esta sesión. No implica que todos los formularios y roles estén probados.' }
      tieneResultados = true
    }
  } catch { /* sin resultado demostrado */ }

  return { modulos, formularios, tieneResultados }
}

/** Superadmin: se actualiza en la misma pestaña y en otras pestañas al guardar un resultado. */
export function useIndicadoresTestBot(usuarioId: string, esSuperadmin: boolean): IndicadoresTestBot {
  const [datos, setDatos] = useState<IndicadoresTestBot>(VACIO)

  useEffect(() => {
    if (!esSuperadmin || !usuarioId) {
      setDatos(VACIO)
      return
    }
    const actualizar = () => setDatos(datosLocales(usuarioId))
    actualizar()
    window.addEventListener('storage', actualizar)
    window.addEventListener(EVENTO_RECORRIDO_TESTBOT, actualizar)
    window.addEventListener(EVENTO_FORMULARIOS_TESTBOT, actualizar)
    return () => {
      window.removeEventListener('storage', actualizar)
      window.removeEventListener(EVENTO_RECORRIDO_TESTBOT, actualizar)
      window.removeEventListener(EVENTO_FORMULARIOS_TESTBOT, actualizar)
    }
  }, [usuarioId, esSuperadmin])

  return datos
}
