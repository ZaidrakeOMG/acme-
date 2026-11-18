/** Informe TXT de pruebas ACMA TestBot. No exportar tokens, cookies ni contraseñas. */
import { SECUENCIA_ACMA, type EstadoRecorrido } from './testbotSecuencia'

export interface DatosReporteFolio {
  numero: string
  id: string
  estado: string
  tecnicoId: string | null
  enJornada: boolean
  ultimaPosicion: string | null
  diagnosticoGPS: string
}
export function reporteTestBotTXT(recorrido: EstadoRecorrido, formulariosPaso: number,
                                  historial: string[] = [], folio?: DatosReporteFolio | null,
                                  momento = new Date()): string {
  const resultados = recorrido.resultados
  const conteo = (estado: string) => resultados.filter(r => r.estado === estado).length
  const lineas = [
    'ACMA TESTBOT — INFORME DE DIAGNÓSTICO',
    'Generado (UTC): ' + momento.toISOString(),
    'Ambito exclusivo: EMPRESA DEMO ACMA SA DE CV / MANTENIMIENTO DEMO ACMA SA DE CV',
    'NO contiene contraseñas, cookies, tokens ni cuerpos de las peticiones.',
    'NOTA: Una consulta OK no demuestra que el módulo funcione al 100%.',
    '',
    'RESUMEN',
    'Formularios (pasos completados): ' + formulariosPaso,
    'Módulos evaluados: ' + resultados.length + '/' + SECUENCIA_ACMA.length,
    'Alta y edición DEMO verificadas: ' + conteo('alta_cambio_demo_verificados'),
    'Altas DEMO verificadas: ' + conteo('alta_demo_verificada'),
    'Consultas GET verificadas (sin CRUD): ' + conteo('consulta_verificada'),
    'Errores: ' + conteo('error'),
    'Pendientes: ' + (conteo('pendiente_funcional') + conteo('requiere_otro_rol')),
    '',
    'RESULTADOS POR MÓDULO',
  ]
  for (const [i, m] of SECUENCIA_ACMA.entries()) {
    const r = resultados.find(x => x.id === m.id)
    lineas.push('--------------------------------------------------------------')
    lineas.push((i + 1) + '. ' + m.nombre + ' [' + (r?.estado ?? 'sin_ejecutar') + ']')
    if (!r) continue
    lineas.push('Comprobado (UTC): ' + r.comprobadoEn)
    lineas.push('Resultado: ' + r.mensaje)
    for (const detalle of r.detalles) lineas.push('  ' + detalle)
  }
  lineas.push('--------------------------------------------------------------', '', 'SEGUIMIENTO DE FOLIO DEMO')
  if (folio) {
    lineas.push('Folio: ' + folio.numero, 'ID: ' + folio.id,
      'Estado: ' + folio.estado,
      'Tecnico asignado: ' + (folio.tecnicoId ?? 'ninguno'),
      'Jornada abierta: ' + (folio.enJornada ? 'sí' : 'no'),
      'Ultima posicion registrada: ' + (folio.ultimaPosicion ?? 'sin datos'),
      'Diagnostico GPS: ' + folio.diagnosticoGPS)
  } else lineas.push('Aún no se realizó seguimiento desde esta sesión.')
  lineas.push('', 'ULTIMOS EVENTOS LOCALES DE LA PRUEBA')
  if (!historial.length) lineas.push('Sin eventos locales de esta sesión.')
  else historial.forEach((evento, i) => lineas.push((i + 1) + '. ' + evento))
  lineas.push('', 'FIN DEL INFORME', '')
  return lineas.join('\r\n')
}
