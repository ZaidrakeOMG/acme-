import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { AppShell } from './components/AppShell'
import { MODULOS } from './config/modulos'
import { useAuth } from './contexts/AuthContext'
import { Alertas } from './pages/admin/Alertas'
import { Auditoria } from './pages/admin/Auditoria'
import { Contratos } from './pages/admin/Contratos'
import { Prestadores, Tenants } from './pages/admin/Organizaciones'
import { Unidades } from './pages/admin/Unidades'
import { Usuarios } from './pages/admin/Usuarios'
import { Campo } from './pages/campo/Campo'
import { CierreOperador } from './pages/campo/operador/CierreOperador'
import { DetalleOperador } from './pages/campo/operador/DetalleOperador'
import { AtencionTecnico } from './pages/campo/tecnico/AtencionTecnico'
import { Catalogos } from './pages/catalogos/Catalogos'
import { Aprobaciones } from './pages/folios/Aprobaciones'
import { CapturaFolio } from './pages/folios/CapturaFolio'
import { FolioDetalle } from './pages/folios/FolioDetalle'
import { Folios } from './pages/folios/Folios'
import { ROLES_APROBADOR, ROLES_CAPTURA } from './pages/folios/comunes'
import { Constructor } from './pages/formularios/Constructor'
import { Formularios } from './pages/formularios/Formularios'
import { Llenar } from './pages/formularios/Llenar'
import { MisFormularios } from './pages/formularios/MisFormularios'
import { Plantillas } from './pages/formularios/Plantillas'
import { Autorizaciones } from './pages/preventivos/Autorizaciones'
import { Calendario } from './pages/preventivos/Calendario'
import { Planes } from './pages/preventivos/Planes'
import { Reporte as ReporteReasignaciones } from './pages/reasignaciones/Reporte'
import { Login } from './pages/Login'
import { Clasificacion } from './pages/clasificacion/Clasificacion'
import { Minutas } from './pages/minutas/Minutas'
import { ResponderMinuta } from './pages/minutas/ResponderMinuta'
import { Notificaciones } from './pages/Notificaciones'
import { Activos } from './pages/activos/Activos'
import { Dashboard } from './pages/bi/Dashboard'
import { Reportes } from './pages/bi/Reportes'
import { FichaEquipo } from './pages/activos/FichaEquipo'
import { CajaChica } from './pages/caja_chica/CajaChica'
import { Erp } from './pages/erp/Erp'
import { Inventario } from './pages/inventario/Inventario'
import { Presupuestos } from './pages/presupuestos/Presupuestos'
import { OcActivos } from './pages/oc_activos/OcActivos'
import { TrabajosEspeciales } from './pages/trabajos_especiales/TrabajosEspeciales'
import { Seguimiento } from './pages/seguimiento/Seguimiento'
import { RoleHub } from './pages/RoleHub'
import { Seguridad } from './pages/Seguridad'
import { Sincronizacion } from './pages/Sincronizacion'
import { ROLES_CALENDARIO, ROLES_PLANES } from './types/preventivos'

const PAGINAS: Record<string, ReactNode> = {
  usuarios: <Usuarios />,
  tenants: <Tenants />,
  prestadores: <Prestadores />,
  unidades: <Unidades />,
  contratos: <Contratos />,
  alertas: <Alertas />,
  auditoria: <Auditoria />,
  catalogos: <Catalogos />,
  formularios: <Formularios />,
  mis_formularios: <MisFormularios />,
  folios: <Folios />,
  app_campo: <Campo />,
  preventivos: <Calendario />,
  reasignaciones: <ReporteReasignaciones />,
  minuta: <Minutas />,
  seguimiento: <Seguimiento />,
  clasificacion: <Clasificacion />,
  notificaciones: <Notificaciones />,
  trabajos_especiales: <TrabajosEspeciales />,
  oc_activos: <OcActivos />,
  inventario: <Inventario />,
  caja_chica: <CajaChica />,
  presupuestos: <Presupuestos />,
  activos: <Activos />,
  erp: <Erp />,
  bi: <Dashboard />,
  sla: <Dashboard />,
}

function SinPermiso() {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-8 text-center">
      <h1 className="text-lg font-semibold text-slate-900">Sin acceso</h1>
      <p className="mt-2 text-sm text-slate-600">Tu rol no tiene acceso a este módulo.</p>
    </div>
  )
}

export function App() {
  const { usuario, cargando } = useAuth()
  if (cargando) {
    return <div className="flex min-h-screen items-center justify-center text-slate-500">Cargando…</div>
  }
  if (!usuario) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<RoleHub />} />
        <Route path="seguridad" element={<Seguridad />} />
        <Route path="formularios/plantillas" element={['superadmin', 'admin_prestador', 'mesa_control'].includes(usuario.rol) ? <Plantillas /> : <SinPermiso />} />
        <Route path="formularios/constructor/:formularioId?" element={['superadmin', 'admin_prestador', 'mesa_control'].includes(usuario.rol) ? <Constructor /> : <SinPermiso />} />
        <Route path="formularios/llenar/:formularioId" element={<Llenar />} />
        <Route path="folios/nuevo" element={ROLES_CAPTURA.includes(usuario.rol) ? <CapturaFolio /> : <SinPermiso />} />
        <Route path="folios/aprobaciones" element={ROLES_APROBADOR.includes(usuario.rol) ? <Aprobaciones /> : <SinPermiso />} />
        <Route path="folios/:folioId" element={<FolioDetalle />} />
        <Route path="sincronizacion" element={<Sincronizacion />} />
        <Route path="minutas/:minutaId" element={<ResponderMinuta />} />
        <Route path="activos/:equipoId" element={<FichaEquipo />} />
        <Route path="bi/reportes" element={<Reportes />} />
        <Route path="preventivos/planes" element={ROLES_PLANES.includes(usuario.rol) || ['admin_empresa', 'admin_un', 'mesa_control'].includes(usuario.rol) ? <Planes /> : <SinPermiso />} />
        <Route path="preventivos/autorizaciones" element={ROLES_CALENDARIO.includes(usuario.rol) ? <Autorizaciones /> : <SinPermiso />} />
        <Route path="campo/nuevo" element={ROLES_CAPTURA.includes(usuario.rol) ? <CapturaFolio modoCampo /> : <SinPermiso />} />
        <Route path="campo/folio/:folioId/cierre" element={['operador', 'admin_un', 'superadmin'].includes(usuario.rol) ? <CierreOperador /> : <SinPermiso />} />
        <Route path="campo/folio/:folioId" element={usuario.rol === 'tecnico' ? <AtencionTecnico /> : <DetalleOperador />} />
        {MODULOS.filter((m) => m.ruta).map((m) => (
          <Route
            key={m.id}
            path={m.ruta!.slice(1)}
            element={usuario.rol === 'superadmin' || m.roles.includes(usuario.rol) ? PAGINAS[m.id] : <SinPermiso />}
          />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
