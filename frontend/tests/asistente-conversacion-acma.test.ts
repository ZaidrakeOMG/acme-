import { describe, expect, it } from 'vitest'
import { MODULOS, modulosDe } from '../src/config/modulos'
import { CONOCIMIENTO_ACMA } from '../src/services/ayudaConocimientoAcma'
import { responderConversacionAcma } from '../src/services/ayudaConversacionalAcma'

const admin = modulosDe('superadmin')
const modulo = (id: string) => MODULOS.find(m => m.id === id) ?? null
const hablar = (pregunta: string, id: string | null = null,
  contexto: { ultimoArticuloId?: string; ultimoModuloId?: string } = {}) =>
  responderConversacionAcma({ pregunta, moduloActual: id ? modulo(id) : null, permitidos: admin, contexto })

describe('Conocimiento del Asistente ACMA', () => {
  it('tiene artículos curados, originales y etiquetados para los 34 módulos', () => {
    expect(CONOCIMIENTO_ACMA.length).toBeGreaterThanOrEqual(80)
    expect(new Set(CONOCIMIENTO_ACMA.map(a => a.id)).size).toBe(CONOCIMIENTO_ACMA.length)
    for (const m of MODULOS) {
      expect(CONOCIMIENTO_ACMA.some(x => x.moduloId === m.id), 'sin conocimiento de ' + m.id).toBe(true)
    }
    for (const articulo of CONOCIMIENTO_ACMA) {
      expect(articulo.claves.length).toBeGreaterThan(0)
      expect(articulo.pasos.length).toBeGreaterThanOrEqual(3)
      expect(articulo.resumen.length).toBeGreaterThan(20)
      expect(articulo.moduloId === 'general' || MODULOS.some(m => m.id === articulo.moduloId)).toBe(true)
    }
  })

  it('responde dudas específicas de módulos aunque el usuario esté en otro', () => {
    const resultado = hablar('¿Cómo registrar una entrada de inventario?', 'folios')
    expect(resultado.articuloId).toBe('inv-entrada')
    expect(resultado.moduloId).toBe('inventario')
    expect(resultado.respuesta.pasos.join(' ')).toContain('almacén')
    expect(resultado.respuesta.ruta).toBe('/inventario')
  })

  it('responde al no poder cerrar un folio con la lista de comprobaciones reales', () => {
    const r = hablar('No puedo cerrar el folio', 'folios')
    expect(r.articuloId).toBe('folio-cierre')
    expect(r.respuesta.pasos.join(' ')).toContain('formulario')
    expect(r.respuesta.pasos.join(' ')).toContain('firma')
  })

  it('mantiene el contexto en preguntas de seguimiento sin repetir otra pregunta completa', () => {
    const r1 = hablar('No aparece la ubicación del técnico', 'operaciones')
    expect(r1.articuloId).toBe('operacion-gps')
    const r2 = hablar('¿Y si sigue igual y no funciona?', 'operaciones',
      { ultimoArticuloId: r1.articuloId ?? undefined, ultimoModuloId: r1.moduloId ?? undefined })
    expect(r2.articuloId).toBe(r1.articuloId)
    expect(r2.respuesta.titulo).toContain('Si todavía no funciona')
    expect(r2.respuesta.pasos.join(' ')).toContain('GPS')
  })

  it('contesta preguntas de la plataforma desde Inicio y reconoce un módulo explícito', () => {
    expect(hablar('¿Qué es ACMA?').articuloId).toBe('acma-descripcion')
    const r = hablar('¿Cómo uso Inteligencia de negocio?')
    expect(r.moduloId).toBe('bi')
    expect(r.respuesta.ruta).toBe('/bi')
  })

  it('no explica pasos de módulos inaccesibles para el rol', () => {
    const r = responderConversacionAcma({
      pregunta: 'Cómo crear usuario',
      moduloActual: modulo('folios'),
      permitidos: modulosDe('tecnico'),
    })
    expect(r.origen).toBe('sin_permiso')
    expect(r.respuesta.pasos.join(' ')).toContain('administrador')
    expect(r.respuesta.ruta).toBeUndefined()
  })

  it('rechaza consultas ajenas a ACMA y no presume ser IA generativa', () => {
    const r = hablar('Dime una receta de cocina', 'folios')
    expect(r.origen).toBe('limite')
    expect(r.respuesta.introduccion).toContain('ACMA')
    expect(r.respuesta.pasos.join(' ')).not.toContain('cocina')
    expect(hablar('hola').respuesta.consejo).toContain('no ejecuto')
  })

  it('prioriza explicaciones por campos actuales sin leer valores privados', () => {
    const r = responderConversacionAcma({
      pregunta: '¿Cómo lleno estos campos?',
      moduloActual: modulo('folios'),
      permitidos: admin,
      campos: [{ etiqueta: 'Prioridad', tipo: 'seleccion', requerido: true }],
    })
    expect(r.origen).toBe('campos')
    expect(r.respuesta.pasos.join(' ')).toContain('Prioridad (obligatorio)')
  })

  it('permite preguntar por títulos de recomendaciones y reconoce códigos 409', () => {
    const r = hablar('No puedo cerrar el folio', 'folios')
    const seguimiento = hablar('No puedo cerrar un folio', 'folios')
    expect(r.articuloId).toBe(seguimiento.articuloId)
    const e = hablar('Qué significa error 409')
    expect(e.articuloId).toBe('errores-http')
  })

  it('separa falla de mensajería del chat interno del folio', () => {
    expect(hablar('whatsapp no llega', 'mensajeria').articuloId).toBe('mensaje-no-llega')
    expect(hablar('chat folio no funciona', 'app_campo').articuloId).toBe('campo-chat')
  })
})
