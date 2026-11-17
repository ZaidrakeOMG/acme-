import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

/** Campo de búsqueda con retardo; avisa con el texto cuando alcanza `minimo` caracteres (o queda vacío). */
export function Buscador({ etiqueta, placeholder, minimo = 1, retardo = 250, alBuscar }: {
  etiqueta: string
  placeholder?: string
  minimo?: number
  retardo?: number
  alBuscar: (q: string) => void
}) {
  const [texto, setTexto] = useState('')
  const ultimo = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (ultimo.current) clearTimeout(ultimo.current)
    ultimo.current = setTimeout(() => {
      if (texto.trim().length === 0 || texto.trim().length >= minimo) alBuscar(texto.trim())
    }, retardo)
    return () => {
      if (ultimo.current) clearTimeout(ultimo.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [texto])
  return (
    <input
      type="search"
      aria-label={etiqueta}
      placeholder={placeholder ?? etiqueta}
      value={texto}
      onChange={(e) => setTexto(e.target.value)}
      className="min-h-11 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-base outline-none sm:max-w-xs sm:text-sm focus:border-primario focus:ring-2 focus:ring-primario/20"
    />
  )
}

/**
 * Selector con búsqueda (§6.3: "escribe 3 letras y selecciona"). Reutilizable por la captura de folios (P04):
 * `buscar(q)` devuelve opciones; al elegir una se llama `alSeleccionar`.
 */
export function SelectorBusqueda<T extends { id: string }>({ etiqueta, buscar, mostrar, alSeleccionar, minimo = 3, valor, placeholder }: {
  etiqueta: string
  buscar: (q: string) => Promise<T[]>
  mostrar: (t: T) => ReactNode
  alSeleccionar: (t: T | null) => void
  minimo?: number
  valor?: T | null
  placeholder?: string
}) {
  const id = useId()
  const [texto, setTexto] = useState('')
  const [opciones, setOpciones] = useState<T[]>([])
  const [abierto, setAbierto] = useState(false)
  const [cargando, setCargando] = useState(false)
  const temporizador = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (temporizador.current) clearTimeout(temporizador.current)
    if (texto.trim().length < minimo) {
      setOpciones([])
      return
    }
    temporizador.current = setTimeout(async () => {
      setCargando(true)
      try {
        setOpciones(await buscar(texto.trim()))
        setAbierto(true)
      } finally {
        setCargando(false)
      }
    }, 250)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [texto])

  if (valor) {
    return (
      <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-300 bg-slate-50 px-3 py-2 text-sm">
        <span>{mostrar(valor)}</span>
        <button type="button" className="text-xs text-primario hover:underline" onClick={() => { alSeleccionar(null); setTexto('') }}>
          Cambiar
        </button>
      </div>
    )
  }
  return (
    <div className="relative">
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">{etiqueta}</label>
      <input
        id={id}
        role="combobox"
        aria-expanded={abierto}
        aria-controls={`${id}-lista`}
        autoComplete="off"
        placeholder={placeholder ?? `Escribe ${minimo} letras…`}
        value={texto}
        onChange={(e) => setTexto(e.target.value)}
        onFocus={() => opciones.length && setAbierto(true)}
        onBlur={() => setTimeout(() => setAbierto(false), 150)}
        className="min-h-11 w-full min-w-0 rounded-lg border border-slate-300 bg-white px-3 py-2 text-base outline-none sm:text-sm focus:border-primario focus:ring-2 focus:ring-primario/20"
      />
      {abierto && (
        <ul id={`${id}-lista`} role="listbox" className="absolute z-20 mt-1 max-h-60 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          {cargando && <li className="px-3 py-2 text-sm text-slate-500">Buscando…</li>}
          {!cargando && opciones.length === 0 && <li className="px-3 py-2 text-sm text-slate-500">Sin resultados</li>}
          {opciones.map((o) => (
            <li key={o.id} role="option" aria-selected={false}>
              <button type="button" className="w-full px-3 py-2 text-left text-sm hover:bg-primario/10" onMouseDown={(e) => e.preventDefault()}
                      onClick={() => { alSeleccionar(o); setAbierto(false) }}>
                {mostrar(o)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
