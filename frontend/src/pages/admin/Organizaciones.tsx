import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Aviso, Boton, Campo, Encabezado, Insignia, Modal, Selector, Tabla, Tarjeta } from '../../components/ui'
import { useAuth } from '../../contexts/AuthContext'
import { useRecurso } from '../../hooks/useRecurso'
import { api, mensajeDeError } from '../../services/api'
import type { Prestador, Tenant } from '../../types/api'

const RFC = /^[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}$/
const COLOR = /^#[0-9A-Fa-f]{6}$/

// ----------------------------------------------------------------- tenants

const esquemaTenant = z.object({
  razon_social: z.string().trim().min(2, 'Mínimo 2 caracteres'),
  rfc: z.string().trim().toUpperCase().regex(RFC, 'RFC inválido'),
  moneda: z.string().length(3),
  zona_horaria: z.string().min(3),
})

export function Tenants() {
  const { usuario } = useAuth()
  const { datos, error, recargar } = useRecurso<Tenant[]>('/tenants')
  const prestadores = useRecurso<Prestador[]>(usuario?.rol === 'superadmin' ? '/prestadores' : null)
  const [abierto, setAbierto] = useState(false)
  const [vincular, setVincular] = useState<Tenant | null>(null)
  const esSuper = usuario?.rol === 'superadmin'

  return (
    <div>
      <Encabezado
        titulo="Clientes (tenants)"
        descripcion={esSuper ? 'Empresas cliente de la plataforma.' : 'Clientes que atiende tu prestador.'}
        acciones={esSuper && <Boton onClick={() => setAbierto(true)}>Nuevo cliente</Boton>}
      />
      <Tarjeta>
        {error && <Aviso>{error}</Aviso>}
        <Tabla
          filas={datos ?? []}
          columnas={[
            { titulo: 'Razón social', celda: (t) => <span className="font-medium">{t.razon_social}</span> },
            { titulo: 'RFC', celda: (t) => t.rfc },
            { titulo: 'País / moneda', celda: (t) => `${t.pais} · ${t.moneda}` },
            { titulo: 'Zona horaria', celda: (t) => t.zona_horaria },
            { titulo: 'Estado', celda: (t) => <Insignia tono={t.estado === 'activo' ? 'ok' : 'alerta'}>{t.estado}</Insignia> },
            ...(esSuper ? [{ titulo: 'Prestador', celda: (t: Tenant) => <Boton variante="fantasma" onClick={() => setVincular(t)}>Vincular</Boton> }] : []),
          ]}
        />
      </Tarjeta>
      <Modal titulo="Nuevo cliente" abierto={abierto} alCerrar={() => setAbierto(false)}>
        <FormularioTenant alGuardar={async () => { setAbierto(false); await recargar() }} />
      </Modal>
      <Modal titulo={`Vincular prestador a ${vincular?.razon_social ?? ''}`} abierto={vincular !== null} alCerrar={() => setVincular(null)}>
        {vincular && <FormularioVinculo tenant={vincular} prestadores={prestadores.datos ?? []} alGuardar={() => setVincular(null)} />}
      </Modal>
    </div>
  )
}

function FormularioTenant({ alGuardar }: { alGuardar: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null)
  const { register, handleSubmit, formState } = useForm<z.infer<typeof esquemaTenant>>({
    resolver: zodResolver(esquemaTenant),
    defaultValues: { moneda: 'MXN', zona_horaria: 'America/Mexico_City' },
  })
  const enviar = handleSubmit(async (d) => {
    try {
      await api('/tenants', { metodo: 'POST', cuerpo: d })
      await alGuardar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  })
  return (
    <form onSubmit={enviar} className="space-y-3" noValidate>
      {error && <Aviso>{error}</Aviso>}
      <Campo etiqueta="Razón social" error={formState.errors.razon_social?.message} {...register('razon_social')} />
      <Campo etiqueta="RFC" error={formState.errors.rfc?.message} {...register('rfc')} />
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Moneda" {...register('moneda')} />
        <Campo etiqueta="Zona horaria" {...register('zona_horaria')} />
      </div>
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>Crear cliente</Boton>
    </form>
  )
}

function FormularioVinculo({ tenant, prestadores, alGuardar }: { tenant: Tenant; prestadores: Prestador[]; alGuardar: () => void }) {
  const [prestadorId, setPrestadorId] = useState(prestadores[0]?.id ?? '')
  const [estado, setEstado] = useState<{ tipo: 'error' | 'exito'; texto: string } | null>(null)
  async function guardar() {
    try {
      await api(`/tenants/${tenant.id}/prestadores`, { metodo: 'POST', cuerpo: { prestador_id: prestadorId } })
      setEstado({ tipo: 'exito', texto: 'Prestador vinculado' })
      setTimeout(alGuardar, 800)
    } catch (e) {
      setEstado({ tipo: 'error', texto: mensajeDeError(e) })
    }
  }
  return (
    <div className="space-y-3">
      {estado && <Aviso tipo={estado.tipo}>{estado.texto}</Aviso>}
      <Selector etiqueta="Prestador" value={prestadorId} onChange={(e) => setPrestadorId(e.target.value)} opciones={prestadores.map((p) => ({ valor: p.id, texto: p.razon_social }))} />
      <Boton className="w-full" onClick={() => void guardar()} disabled={!prestadorId}>Vincular</Boton>
    </div>
  )
}

// ------------------------------------------------------------- prestadores

const esquemaPrestador = z.object({
  razon_social: z.string().trim().min(2, 'Mínimo 2 caracteres'),
  rfc: z.string().trim().toUpperCase().regex(RFC, 'RFC inválido'),
  color_primario: z.string().regex(COLOR, 'Color #RRGGBB'),
  color_acento: z.string().regex(COLOR, 'Color #RRGGBB'),
  regimen_fiscal: z.string().max(10).optional(),
  codigo_postal: z.string().max(10).optional(),
})

export function Prestadores() {
  const { usuario, recargarPerfil } = useAuth()
  const { datos, error, recargar } = useRecurso<Prestador[]>('/prestadores')
  const [editar, setEditar] = useState<Prestador | 'nuevo' | null>(null)

  return (
    <div>
      <Encabezado
        titulo="Prestadores"
        descripcion="Datos fiscales (cifrados en reposo), logo y colores de la interfaz."
        acciones={usuario?.rol === 'superadmin' && <Boton onClick={() => setEditar('nuevo')}>Nuevo prestador</Boton>}
      />
      <Tarjeta>
        {error && <Aviso>{error}</Aviso>}
        <Tabla
          filas={datos ?? []}
          columnas={[
            { titulo: 'Razón social', celda: (p) => <span className="font-medium">{p.razon_social}</span> },
            { titulo: 'RFC', celda: (p) => p.rfc },
            {
              titulo: 'Colores',
              celda: (p) => (
                <span className="flex gap-1">
                  <span className="h-5 w-5 rounded" style={{ background: p.color_primario }} title={p.color_primario} />
                  <span className="h-5 w-5 rounded" style={{ background: p.color_acento }} title={p.color_acento} />
                </span>
              ),
            },
            { titulo: 'Logo', celda: (p) => (p.logo_key ? <Insignia tono="ok">Cargado</Insignia> : <Insignia>Sin logo</Insignia>) },
            { titulo: '', celda: (p) => <Boton variante="fantasma" onClick={() => setEditar(p)}>Editar</Boton> },
          ]}
        />
      </Tarjeta>
      <Modal titulo={editar === 'nuevo' ? 'Nuevo prestador' : 'Editar prestador'} abierto={editar !== null} alCerrar={() => setEditar(null)}>
        {editar && (
          <FormularioPrestador
            prestador={editar === 'nuevo' ? null : editar}
            alGuardar={async () => {
              setEditar(null)
              await recargar()
              await recargarPerfil()
            }}
          />
        )}
      </Modal>
    </div>
  )
}

function FormularioPrestador({ prestador, alGuardar }: { prestador: Prestador | null; alGuardar: () => Promise<void> }) {
  const [error, setError] = useState<string | null>(null)
  const [logo, setLogo] = useState<File | null>(null)
  // Si el POST funcionó, conservar el id aunque la subida del logo falle.
  // Así, un reintento no vuelve a crear el mismo prestador.
  const [prestadorCreado, setPrestadorCreado] = useState<Prestador | null>(null)
  const prestadorGuardado = prestador ?? prestadorCreado
  const { register, handleSubmit, formState } = useForm<z.infer<typeof esquemaPrestador>>({
    resolver: zodResolver(esquemaPrestador),
    defaultValues: {
      razon_social: prestador?.razon_social ?? '',
      rfc: prestador?.rfc ?? '',
      color_primario: prestador?.color_primario ?? '#1C3D8F',
      color_acento: prestador?.color_acento ?? '#A2C62B',
    },
  })

  const enviar = handleSubmit(async (d) => {
    setError(null)
    let creadoAhora = false
    const datos_fiscales = d.regimen_fiscal || d.codigo_postal ? { regimen_fiscal: d.regimen_fiscal || null, codigo_postal: d.codigo_postal || null } : undefined
    try {
      const guardado = prestadorGuardado
        ? await api<Prestador>(`/prestadores/${prestadorGuardado.id}`, {
            metodo: 'PATCH',
            cuerpo: { razon_social: d.razon_social, color_primario: d.color_primario, color_acento: d.color_acento, datos_fiscales },
          })
        : await api<Prestador>('/prestadores', {
            metodo: 'POST',
            cuerpo: { razon_social: d.razon_social, rfc: d.rfc, color_primario: d.color_primario, color_acento: d.color_acento, datos_fiscales },
          })
      if (!prestadorGuardado) {
        setPrestadorCreado(guardado)
        creadoAhora = true
      }
      if (logo) {
        const formulario = new FormData()
        formulario.append('archivo', logo)
        await api(`/prestadores/${guardado.id}/logo`, { metodo: 'POST', formulario })
      }
      await alGuardar()
    } catch (e) {
      const detalle = mensajeDeError(e)
      setError(creadoAhora || prestadorCreado
        ? `El prestador ya quedó registrado, pero no se completó el proceso: ${detalle}. Corrige el problema y vuelve a guardar; no se creará otro prestador.`
        : detalle)
    }
  })

  return (
    <form onSubmit={enviar} className="space-y-3" noValidate>
      {error && <Aviso>{error}</Aviso>}
      <Campo etiqueta="Razón social" error={formState.errors.razon_social?.message} {...register('razon_social')} />
      <Campo etiqueta="RFC" disabled={prestadorGuardado !== null} error={formState.errors.rfc?.message} {...register('rfc')} />
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Color primario" type="color" {...register('color_primario')} />
        <Campo etiqueta="Color de acento" type="color" {...register('color_acento')} />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Campo etiqueta="Régimen fiscal" placeholder={prestador?.datos_fiscales?.regimen_fiscal ?? '601'} {...register('regimen_fiscal')} />
        <Campo etiqueta="C.P. fiscal" placeholder={prestador?.datos_fiscales?.codigo_postal ?? ''} {...register('codigo_postal')} />
      </div>
      <label className="block text-sm">
        <span className="mb-1 block font-medium text-slate-700">Logo (PNG, JPG, SVG o WebP, máx. 1 MB)</span>
        <input type="file" accept="image/png,image/jpeg,image/svg+xml,image/webp" onChange={(e) => setLogo(e.target.files?.[0] ?? null)} />
      </label>
      <Boton type="submit" className="w-full" disabled={formState.isSubmitting}>Guardar</Boton>
    </form>
  )
}
