import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { Aviso } from '../components/ui'
import { mensajeDeError } from '../services/api'
import { destinoDeEnlace } from '../services/mensajeria'

/**
 * Enlace corto propio de ACMA: `/l/{codigo}` (F2-02). En un SMS de 160 caracteres no cabe una URL larga, así que el
 * mensaje lleva este código y aquí se resuelve a dónde va. No hace falta sesión para resolverlo —solo devuelve una
 * ruta— pero el destino sí la exige, salvo el PDF de la minuta, que viaja con su propio enlace firmado.
 */
export function EnlaceCorto() {
  const { codigo } = useParams<{ codigo: string }>()
  const navegar = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!codigo) return
    let cancelado = false
    void destinoDeEnlace(codigo)
      .then(({ destino }) => {
        if (cancelado) return
        if (destino.startsWith('/api/')) window.location.replace(destino)
        else navegar(destino, { replace: true })
      })
      .catch((e) => { if (!cancelado) setError(mensajeDeError(e)) })
    return () => { cancelado = true }
  }, [codigo, navegar])

  return (
    <div className="mx-auto max-w-md p-6">
      {error
        ? <Aviso>Este enlace ya no sirve: {error}</Aviso>
        : <p className="text-sm text-slate-600">Abriendo ACMA…</p>}
    </div>
  )
}
