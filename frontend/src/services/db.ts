/**
 * Base local IndexedDB (Dexie). P01 solo crea la tabla de metadatos; el modo offline completo
 * (catálogos, folios, cola de sincronización) se agrega en P05 con nuevas versiones del esquema.
 */
import Dexie, { type EntityTable } from 'dexie'

export interface Metadato {
  clave: string
  valor: unknown
  actualizado: string
}

class BaseLocal extends Dexie {
  metadatos!: EntityTable<Metadato, 'clave'>

  constructor() {
    super('acma')
    this.version(1).stores({ metadatos: '&clave' })
  }
}

export const baseLocal = new BaseLocal()
