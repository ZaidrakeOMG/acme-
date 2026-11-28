import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ajustarBurbuja, inicioBurbuja, leerBurbuja, guardarBurbuja, posicionPanel } from '../src/services/asistenteBurbuja'
import { camposVisiblesPantalla, responderDudaModulo } from '../src/services/ayudaCampos'
import { MODULOS } from '../src/config/modulos'

beforeEach(() => localStorage.clear())

describe('Burbuja flotante del Asistente ACMA', () => {
  it('mantiene la burbuja en la ventana al arrastrar fuera de los límites', () => {
    const vista = { ancho: 360, alto: 690 }
    expect(ajustarBurbuja({ x: -100, y: -50 }, vista)).toEqual({ x: 12, y: 12 })
    expect(ajustarBurbuja({ x: 999, y: 999 }, vista)).toEqual({ x: 292, y: 622 })
    const inicio = inicioBurbuja(vista)
    expect(inicio.x).toBeGreaterThanOrEqual(12)
    expect(inicio.y).toBeLessThan(622)
  })

  it('ubica el panel dentro del viewport incluso con la burbuja en las esquinas', () => {
    const vistas = [{ ancho: 360, alto: 640 }, { ancho: 1440, alto: 900 }]
    for (const vista of vistas) {
      for (const punto of [{ x: 12, y: 12 }, { x: vista.ancho - 68, y: vista.alto - 68 }]) {
        const p = posicionPanel(punto, vista)
        expect(p.left).toBeGreaterThanOrEqual(12)
        expect(p.top).toBeGreaterThanOrEqual(12)
        expect(p.left + p.ancho).toBeLessThanOrEqual(vista.ancho - 12)
        expect(p.top + p.alto).toBeLessThanOrEqual(vista.alto - 12)
      }
    }
  })

  it('ajusta el panel cuando el teclado móvil reduce mucho el espacio', () => {
    const vista = { ancho: 320, alto: 160 }
    const p = posicionPanel({ x: 240, y: 70 }, vista)
    expect(p.top + p.alto).toBeLessThanOrEqual(148)
    expect(p.left + p.ancho).toBeLessThanOrEqual(308)
  })

  it('guarda posición por usuario, la recupera y descarta coordenadas inválidas', () => {
    const vista = { ancho: 390, alto: 780 }
    guardarBurbuja('cuenta-a', { x: 45, y: 175 })
    expect(leerBurbuja('cuenta-a', vista)).toEqual({ x: 45, y: 175 })
    expect(leerBurbuja('cuenta-b', vista)).not.toEqual({ x: 45, y: 175 })
    localStorage.setItem('acma.asistente.burbuja.v1.cuenta-a', '{"x":999999,"y":-500}')
    expect(leerBurbuja('cuenta-a', vista)).toEqual({ x: 322, y: 12 })
    localStorage.setItem('acma.asistente.burbuja.v1.cuenta-a', '{"x":"a","y":null}')
    expect(leerBurbuja('cuenta-a', vista)).toEqual(inicioBurbuja(vista))
  })
})

describe('Ayuda de preguntas y llenado por campos visibles, sin leer valores', () => {
  it('describe los campos y cuáles son obligatorios sin acceder al valor', () => {
    const formulario = document.createElement('form')
    formulario.innerHTML = '<label for="correo">Correo electrónico</label><input id="correo" required>' +
      '<label for="monto">Importe</label><input id="monto" type="number">' +
      '<label for="secret">Contraseña</label><input id="secret" type="password">' +
      '<label for="descripcion">Descripción</label><textarea id="descripcion"></textarea>'
    const campo = formulario.querySelector('#correo') as HTMLInputElement
    campo.value = 'privado@example.com'
    const spy = vi.spyOn(HTMLElement.prototype, 'getClientRects').mockImplementation(() =>
      ({ length: 1 }) as DOMRectList)
    try {
      const campos = camposVisiblesPantalla(formulario)
      expect(campos.map(c => c.etiqueta)).toEqual(['Correo electrónico', 'Importe', 'Descripción'])
      expect(campos[0]?.requerido).toBe(true)
      expect(JSON.stringify(campos)).not.toContain('privado@example.com')
      const modulo = MODULOS.find(m => m.id === 'presupuestos')!
      const respuesta = responderDudaModulo(modulo, '¿Cómo lleno estos campos?', campos)
      expect(respuesta.titulo).toContain('campo por campo')
      expect(respuesta.pasos.join(' ')).toContain('Correo electrónico (obligatorio)')
      expect(JSON.stringify(respuesta)).not.toContain('privado@example.com')
    } finally {
      spy.mockRestore()
    }
  })

  it('explica un campo concreto, errores y permisos sin inventar operaciones', () => {
    const m = MODULOS.find(x => x.id === 'folios')!
    const campos = [{ etiqueta: 'Prioridad', requerido: true, tipo: 'seleccion' as const }]
    const prioridad = responderDudaModulo(m, '¿Qué pongo en Prioridad?', campos)
    expect(prioridad.titulo).toContain('Prioridad')
    expect(prioridad.pasos.join(' ')).toContain('clasificación')
    expect(responderDudaModulo(m, 'no me deja guardar', campos).pasos.join(' ')).toContain('obligatorios')
    expect(responderDudaModulo(m, '¿Quién puede cambiar este folio?', campos).titulo).toContain('Permisos')
    const desconocido = responderDudaModulo(m, 'xyzq blarg something', campos)
    expect(desconocido.titulo).toBe('Necesito un poco más de detalle')
  })
})
