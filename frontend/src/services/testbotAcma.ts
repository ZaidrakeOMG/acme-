/** Eventos locales entre el asistente visual y el constructor; nunca exponen permisos ni credenciales. */
export type AccionTestBot = 'preparar' | 'guardar' | 'vista_previa' | 'publicar'
export interface ResultadoTestBot {
  accion: AccionTestBot
  exito: boolean
  mensaje: string
  formularioId?: string
}
export const EVENTO_ACCION_TESTBOT = 'acma:testbot:accion'
export const EVENTO_RESULTADO_TESTBOT = 'acma:testbot:resultado'

export function notificarTestBot(resultado: ResultadoTestBot) {
  window.dispatchEvent(new CustomEvent<ResultadoTestBot>(EVENTO_RESULTADO_TESTBOT, { detail: resultado }))
}
