from models.alertas import AlertaCatalogo, AlertaConfiguracion, AlertaHistorial, AlertaSupresion
from models.auditoria import AuditAccesoAPI, AuditLog, ConfiguracionPrestador, ConfiguracionTenant
from models.base import Base, Dominio, EstadoRegistro, NivelSeveridad, Rol
from models.catalogos import (
    CoberturaContrato, Equipo, EstadoActivo, EstadoImportacion, FamiliaEquipo, Habilidad, ImportacionCatalogo,
    NivelSeveridadCatalogo, Tecnico, TecnicoHabilidad, TecnicoTenantHabilitado, TipoEquipo, TipoFalla, TipoFallaSeveridad,
)
from models.chat import (
    CanalChat, Chat, ChatArchivo, ChatEventoSistema, ChatMensaje, ChatParticipante, EstadoChat, ReglaConflicto, ResultadoMutacion,
    SincronizacionConflicto, SincronizacionDispositivo, SincronizacionMutacion, SuscripcionPush, TipoMensaje,
)
from models.contratos import Contrato, ContratoSLA
from models.folios import (
    AprobacionAlertaTimeout, AprobacionDecision, AprobacionFlujo, AprobacionNivelConfig, AprobacionRegla, CanalAprobacion,
    ComportamientoTimeout, Criticidad, CriterioAprobacion, DecisionAprobacion, EstadoFlujo, EstadoFolio, Folio, FolioEncuesta,
    FolioEstadoHistorial, FolioEvidencia, FolioFormularioAtencion, FolioFormularioCaptura, FolioKeywordAlerta, FolioPoliticasTenant,
    FolioRefaccion, FolioSLA, ModuloDestino, OrigenRefaccion, RazonRechazo, RevisionManualTrigger, SeveridadOrigen,
    TipoEvidenciaFolio, TipoFolio, TriggerRevision,
)
from models.formularios import (
    CalidadFotoDefault, CatalogoPersonalizado, CatalogoPersonalizadoOpcion, EstadoFormulario, EstadoRespuesta, Formulario,
    FormularioAsignacion, FormularioEvidencia, FormularioPermisoMesa, FormularioRespuesta, FormularioVersion, OrigenRespuesta,
    TipoEvidencia, TipoFormulario,
)
from models.organizaciones import Prestador, RolCatalogo, Tenant, TenantPrestador
from models.permisos import (
    GrupoTecnicoPermiso, GrupoTecnicos, PermisoCatalogo, PermisoDespachador, PermisoDespachadorLog,
    PermisoTecnico, TecnicoGrupo, TecnicoPermisoOverride,
)
from models.preventivos import (
    AutorizacionPreventivo, CalendarioPublicacion, EquipoPlan, EstadoAutorizacion, EstadoEjecucionPlan, EstadoPlan, EstadoPreventivo,
    OrigenPreventivo, PlanEjecucion, PlanMantenimiento, PlanMaterial, PlanTarea, PlanTrigger, PreventivoCalendario, RazonReasignacion,
    Reasignacion, ReasignacionValidacion, TipoAutorizacionPreventivo, TipoReasignacion, TipoTrigger,
)
from models.unidades import GrupoUN, GrupoUNMiembro, UnidadNegocio, UsuarioGrupo, UsuarioUN
from models.usuarios import HistorialContrasena, Sesion, Usuario

from models.minutas import (
    CanalNotificacion, EstadoMinuta, EstadoNotificacion, EstadoRespuestaHallazgo, Hallazgo, Minuta, MinutaConfiguracion, MinutaDestinatario,
    MinutaRespuesta, MinutaSeccion, ModoMinuta, NivelUrgencia, Notificacion, NotificacionPreferencia, OpcionRespuesta, OrigenHallazgo,
    OrigenPeticion, PeticionCliente, TipoHallazgo, TipoMinuta,
)
from models.seguimiento import (
    AdminUNCalificacion, ClasificacionConfiguracion, Cotizacion, CotizacionEnvioExterno, EstadoCotizacion, EstadoPresupuesto,
    EstadoReprogramacion, EstadoSeguimientoInterno, FolioClasificacion, HallazgoPresupuesto, ModuloHistorial, OpcionClasificacion,
    PeriodoPresupuestal, Reprogramacion, SeguimientoInterno, TipoPeriodoPresupuestal, VarianteCoordinado,
)
from models.trabajos_especiales import (
    DecisionOCRechazo, DecisionTECliente, EstadoTrabajoEspecial, EstatusOCActivo, FolioActivoAutorizacion, FolioActivoHistorial, TEEvidencia,
    TEHistorial, TERespuestaCliente, TipoEvidenciaTE, TrabajoEspecial,
)
from models.inventario import (
    Articulo, EstadoCFDI, EstadoGastoCajaChica, EstadoOrdenCompra, EstadoPoliza, Existencia, FondoCajaChica, FormatoPoliza, GastoCajaChica,
    MovimientoInventario, OrdenCompra, OrdenCompraPartida, PolizaExportacion, TipoMovimientoInventario, TipoUbicacionInventario,
    UbicacionInventario, ValidacionCFDI,
)
from models.costos import (
    AdaptadorERP, ErpConfiguracion, ErpEventoPendiente, ErpExportacion, EstadoEventoERP, FolioCosto, OperacionERP, Presupuesto,
    PresupuestoConsumo, TarifaManoObra, TipoActividadPresupuesto,
)
from models.activos import ActivoDepreciacion, ActivoDepreciacionHistorial, ActivoReemplazoAlerta, ActivoTCOSnapshot, DecisionReemplazo, MetodoDepreciacion

__all__ = [
    "Articulo", "EstadoCFDI", "EstadoGastoCajaChica", "EstadoOrdenCompra", "EstadoPoliza", "Existencia", "FondoCajaChica", "FormatoPoliza",
    "GastoCajaChica", "MovimientoInventario", "OrdenCompra", "OrdenCompraPartida", "PolizaExportacion", "TipoMovimientoInventario",
    "TipoUbicacionInventario", "UbicacionInventario", "ValidacionCFDI",
    "AdaptadorERP", "ErpConfiguracion", "ErpEventoPendiente", "ErpExportacion", "EstadoEventoERP", "FolioCosto", "OperacionERP",
    "Presupuesto", "PresupuestoConsumo", "TarifaManoObra", "TipoActividadPresupuesto",
    "ActivoDepreciacion", "ActivoDepreciacionHistorial", "ActivoReemplazoAlerta", "ActivoTCOSnapshot", "DecisionReemplazo", "MetodoDepreciacion",
    "DecisionOCRechazo", "DecisionTECliente", "EstadoTrabajoEspecial", "EstatusOCActivo", "FolioActivoAutorizacion", "FolioActivoHistorial",
    "TEEvidencia", "TEHistorial", "TERespuestaCliente", "TipoEvidenciaTE", "TrabajoEspecial",
    "CanalNotificacion", "EstadoMinuta", "EstadoNotificacion", "EstadoRespuestaHallazgo", "Hallazgo", "Minuta", "MinutaConfiguracion",
    "MinutaDestinatario", "MinutaRespuesta", "MinutaSeccion", "ModoMinuta", "NivelUrgencia", "Notificacion", "NotificacionPreferencia",
    "OpcionRespuesta", "OrigenHallazgo", "OrigenPeticion", "PeticionCliente", "TipoHallazgo", "TipoMinuta",
    "AdminUNCalificacion", "ClasificacionConfiguracion", "Cotizacion", "CotizacionEnvioExterno", "EstadoCotizacion", "EstadoPresupuesto",
    "EstadoReprogramacion", "EstadoSeguimientoInterno", "FolioClasificacion", "HallazgoPresupuesto", "ModuloHistorial", "OpcionClasificacion",
    "PeriodoPresupuestal", "Reprogramacion", "SeguimientoInterno", "TipoPeriodoPresupuestal", "VarianteCoordinado",
    "AutorizacionPreventivo", "CalendarioPublicacion", "EquipoPlan", "EstadoAutorizacion", "EstadoEjecucionPlan", "EstadoPlan", "EstadoPreventivo",
    "OrigenPreventivo", "PlanEjecucion", "PlanMantenimiento", "PlanMaterial", "PlanTarea", "PlanTrigger", "PreventivoCalendario", "RazonReasignacion",
    "Reasignacion", "ReasignacionValidacion", "TipoAutorizacionPreventivo", "TipoReasignacion", "TipoTrigger",
    "CanalChat", "Chat", "ChatArchivo", "ChatEventoSistema", "ChatMensaje", "ChatParticipante", "EstadoChat", "ReglaConflicto",
    "ResultadoMutacion", "SincronizacionConflicto", "SincronizacionDispositivo", "SincronizacionMutacion", "SuscripcionPush", "TipoMensaje",
    "AprobacionAlertaTimeout", "AprobacionDecision", "AprobacionFlujo", "AprobacionNivelConfig", "AprobacionRegla", "CanalAprobacion",
    "ComportamientoTimeout", "Criticidad", "CriterioAprobacion", "DecisionAprobacion", "EstadoFlujo", "EstadoFolio", "Folio", "FolioEncuesta",
    "FolioEstadoHistorial", "FolioEvidencia", "FolioFormularioAtencion", "FolioFormularioCaptura", "FolioKeywordAlerta", "FolioPoliticasTenant",
    "FolioRefaccion", "FolioSLA", "ModuloDestino", "OrigenRefaccion", "RazonRechazo", "RevisionManualTrigger", "SeveridadOrigen",
    "TipoEvidenciaFolio", "TipoFolio", "TriggerRevision",
    "CalidadFotoDefault", "CatalogoPersonalizado", "CatalogoPersonalizadoOpcion", "EstadoFormulario", "EstadoRespuesta",
    "Formulario", "FormularioAsignacion", "FormularioEvidencia", "FormularioPermisoMesa", "FormularioRespuesta",
    "FormularioVersion", "OrigenRespuesta", "TipoEvidencia", "TipoFormulario",
    "CoberturaContrato", "Equipo", "EstadoActivo", "EstadoImportacion", "FamiliaEquipo", "Habilidad", "ImportacionCatalogo",
    "NivelSeveridadCatalogo", "Tecnico", "TecnicoHabilidad", "TecnicoTenantHabilitado", "TipoEquipo", "TipoFalla",
    "TipoFallaSeveridad",
    "AlertaCatalogo", "AlertaConfiguracion", "AlertaHistorial", "AlertaSupresion", "AuditAccesoAPI", "AuditLog",
    "Base", "ConfiguracionPrestador", "ConfiguracionTenant", "Contrato", "ContratoSLA", "Dominio", "EstadoRegistro",
    "GrupoTecnicoPermiso", "GrupoTecnicos", "GrupoUN", "GrupoUNMiembro", "HistorialContrasena", "NivelSeveridad",
    "PermisoCatalogo", "PermisoDespachador", "PermisoDespachadorLog", "PermisoTecnico", "Prestador", "Rol",
    "RolCatalogo", "Sesion", "TecnicoGrupo", "TecnicoPermisoOverride", "Tenant", "TenantPrestador",
    "UnidadNegocio", "Usuario", "UsuarioGrupo", "UsuarioUN",
]
