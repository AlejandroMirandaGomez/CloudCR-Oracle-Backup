from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from cloudcr_backup.domain.alertas import ResumenEvaluacion, SeveridadAlerta, VistaAlerta
from cloudcr_backup.domain.enums import (
    EstadoAlerta,
    EstadoEjecucion,
    EstadoEstrategia,
    EstadoPrueba,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.errores import ErrorServicio, OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea
from cloudcr_backup.domain.historial import (
    ArchivoExportado,
    ConsultaHistorial,
    DetalleEjecucion,
    FilaHistorial,
    PaginaHistorial,
)
from cloudcr_backup.domain.monitoreo import (
    ColorSemaforo,
    DetalleEstrategia,
    EstadoAgente,
    EstadoGeneral,
    EstadoLatido,
    Latido,
    ResumenEstrategia,
    ScriptResumen,
    SemaforoEstrategia,
    TareaDetalle,
)

AHORA = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)
NOMBRE_PELIGROSO = "Producción <script>alert(1)</script>"


def fila_historial(ejecucion_id: int = 40, estado: EstadoEjecucion = EstadoEjecucion.EXITOSA) -> FilaHistorial:
    programada = datetime(2026, 10, 3, 19, 0, tzinfo=UTC) - timedelta(hours=ejecucion_id - 40)
    return FilaHistorial(
        ejecucion_id=ejecucion_id,
        bd="XE",
        bd_id=1,
        estrategia="EST001",
        estrategia_id=2,
        estrategia_nombre=NOMBRE_PELIGROSO,
        tarea="T1",
        tarea_id=3,
        tipo_respaldo=TipoRespaldo.INCREMENTAL_N0,
        modo_respaldo=ModoRespaldo.EN_LINEA,
        estado=estado,
        estado_prueba=EstadoPrueba.OK if estado is EstadoEjecucion.EXITOSA else EstadoPrueba.NO_APLICA,
        programada_para=programada,
        inicio=programada + timedelta(seconds=4),
        fin=programada + timedelta(minutes=2),
        duracion_segundos=116,
        tamano_bytes=1024 * 1024 * 300,
        zona_horaria="America/Costa_Rica",
        mensaje="RMAN-03009 <b>fallo</b>" if estado is EstadoEjecucion.FALLIDA else None,
        agente="SERVIDOR",
    )


def alerta(alerta_id: int = 7, estado: EstadoAlerta = EstadoAlerta.ABIERTA) -> VistaAlerta:
    return VistaAlerta(
        id=alerta_id,
        codigo="EJECUCION_FALLIDA",
        clave_dedup="EJECUCION_FALLIDA:XE/EST001/T1",
        severidad=SeveridadAlerta.ALERTA,
        estado=estado,
        mensaje="La ejecución 41 de XE/EST001/T1 falló.",
        accion_sugerida="Revise el log de RMAN.",
        bd="XE",
        estrategia="EST001",
        tarea="T1",
        bd_id=1,
        estrategia_id=2,
        tarea_id=3,
        ejecucion_id=41,
        abierta_en=AHORA,
    )


def _estrategia(estado: EstadoEstrategia) -> Estrategia:
    return Estrategia(
        id=2,
        bd_id=1,
        codigo="EST001",
        nombre=NOMBRE_PELIGROSO,
        prioridad=Prioridad.ALTA,
        estado=estado,
        creada_por="luis",
        alcance=[ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA)],
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N0, modo_respaldo=ModoRespaldo.EN_LINEA),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
                destino=Destino(ruta=r"C:\backups\XE"),
            )
        ],
    )


@dataclass
class MonitoreoFalso:
    filas: list[FilaHistorial] = field(
        default_factory=lambda: [fila_historial(40), fila_historial(41, EstadoEjecucion.FALLIDA)]
    )
    lista_alertas: list[VistaAlerta] = field(default_factory=lambda: [alerta()])
    activa: bool = True
    error: ErrorServicio | None = None
    consultas: list[ConsultaHistorial] = field(default_factory=list)
    acciones: list[str] = field(default_factory=list)

    @property
    def zona_horaria(self) -> str:
        return "America/Costa_Rica"

    def _fallar(self) -> None:
        if self.error is not None:
            raise self.error

    def estado(self, bd: str | None) -> EstadoGeneral:
        self._fallar()
        semaforo = SemaforoEstrategia(
            bd="XE",
            bd_id=1,
            estrategia="EST001",
            estrategia_id=2,
            nombre=NOMBRE_PELIGROSO,
            prioridad=Prioridad.ALTA,
            estado=EstadoEstrategia.ACTIVA,
            color=ColorSemaforo.ROJO,
            motivos=["Última ejecución de T1: Error."],
            ultimas=self.filas,
            proxima_ejecucion=AHORA + timedelta(hours=17),
            alertas_vigentes=1,
        )
        return EstadoGeneral(
            generado_en=AHORA,
            semaforos=[] if bd == "ORCL" else [semaforo],
            en_curso=[fila_historial(42, EstadoEjecucion.EN_CURSO)],
            alertas=self.lista_alertas,
            agentes=self.agentes(),
            tick_segundos=30,
        )

    def agentes(self) -> list[EstadoAgente]:
        self._fallar()
        latido = Latido(
            hostname="SERVIDOR",
            pid=4321,
            iniciado_en=AHORA,
            ultimo_tick=AHORA,
            estado=EstadoLatido.ACTIVO,
            version="0.1.0",
            simulado=True,
        )
        return [EstadoAgente(latido=latido, vivo=True, segundos_desde_tick=5)]

    def _resumen(self) -> ResumenEstrategia:
        return ResumenEstrategia(
            bd="XE",
            bd_id=1,
            estrategia_id=2,
            codigo="EST001",
            nombre=NOMBRE_PELIGROSO,
            prioridad=Prioridad.ALTA,
            estado=EstadoEstrategia.ACTIVA if self.activa else EstadoEstrategia.INACTIVA,
            version=2,
            tareas=1,
            tareas_con_script=1,
            color=ColorSemaforo.ROJO if self.activa else ColorSemaforo.SIN_DATOS,
            proxima_ejecucion=AHORA + timedelta(hours=17) if self.activa else None,
        )

    def estrategias(self) -> list[ResumenEstrategia]:
        self._fallar()
        return [self._resumen()]

    def estrategia(self, bd: str, codigo: str, cantidad: int) -> DetalleEstrategia:
        self._fallar()
        if codigo.upper() != "EST001":
            raise RecursoNoEncontrado(f"No existe la estrategia {codigo.upper()} en la base {bd.upper()}.")
        estrategia = _estrategia(EstadoEstrategia.ACTIVA if self.activa else EstadoEstrategia.INACTIVA)
        tarea = estrategia.tareas[0]
        return DetalleEstrategia(
            resumen=self._resumen(),
            estrategia=estrategia,
            rpo_horas=4,
            rto_horas=2,
            recencia_maxima_horas=24,
            tareas=[
                TareaDetalle(
                    codigo="T1",
                    tarea_id=3,
                    tipo_respaldo=tarea.como.tipo_respaldo,
                    etiqueta_tipo="Incremental nivel 0 (total+)",
                    termino_clase="total+",
                    modo_respaldo=tarea.como.modo_respaldo,
                    programacion=tarea.programacion,
                    descripcion_programacion="Diaria a las 13:00 (America/Costa_Rica)",
                    destino=tarea.destino.ruta,
                    script=ScriptResumen(script_id=9, version=1, aprobado_por="ale", aprobado_en=AHORA),
                    proximas=[AHORA + timedelta(hours=17 + 24 * i) for i in range(cantidad)],
                )
            ],
            retencion="ventana de recuperación de 7 días; purga manual",
            alcance=["XEPDB1:VENTAS"],
        )

    def proximas(self, bd: str, codigo: str, tarea: str, cantidad: int) -> list[datetime]:
        self._fallar()
        return [AHORA + timedelta(hours=17 + 24 * i) for i in range(cantidad)]

    def cambiar_estado_estrategia(self, bd: str, codigo: str, activa: bool) -> ResumenEstrategia:
        self._fallar()
        self.acciones.append(f"{'activar' if activa else 'desactivar'}:{bd}/{codigo}")
        self.activa = activa
        return self._resumen()

    def historial(self, consulta: ConsultaHistorial) -> PaginaHistorial:
        self._fallar()
        self.consultas.append(consulta)
        return PaginaHistorial(filas=self.filas, total=120, pagina=consulta.pagina, limite=consulta.limite)

    def detalle_ejecucion(self, ejecucion_id: int) -> DetalleEjecucion:
        self._fallar()
        fila = next((f for f in self.filas if f.ejecucion_id == ejecucion_id), None)
        if fila is None:
            raise RecursoNoEncontrado(f"No existe la ejecución {ejecucion_id}.")
        return DetalleEjecucion(
            fila=fila,
            script_id=9,
            script_version=1,
            script_hash="abc123",
            errores="RMAN-03009: failure of backup command",
            avisos=["Todavía no existe evidencia.json."],
        )

    def exportar_historial(self, consulta: ConsultaHistorial, formato: str) -> ArchivoExportado:
        self._fallar()
        if formato not in ("csv", "md", "html"):
            raise OperacionNoPermitida(f"El formato {formato!r} no existe.")
        tipos = {
            "csv": "text/csv; charset=utf-8",
            "md": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
        }
        return ArchivoExportado(nombre=f"historial-prueba.{formato}", tipo_contenido=tipos[formato], contenido=b"x")

    def alertas(self, estado: str | None, severidad: str | None) -> list[VistaAlerta]:
        self._fallar()
        return list(self.lista_alertas)

    def reconocer_alerta(self, alerta_id: int) -> VistaAlerta:
        self._fallar()
        self.acciones.append(f"reconocer:{alerta_id}")
        if alerta_id != 7:
            raise OperacionNoPermitida(f"La alerta {alerta_id} ya está RESUELTA.")
        self.lista_alertas = [alerta(7, EstadoAlerta.RECONOCIDA)]
        return self.lista_alertas[0]

    def resolver_alerta(self, alerta_id: int) -> VistaAlerta:
        self._fallar()
        self.acciones.append(f"resolver:{alerta_id}")
        self.lista_alertas = []
        return alerta(alerta_id, EstadoAlerta.RESUELTA)

    def evaluar_alertas(self) -> ResumenEvaluacion:
        self._fallar()
        self.acciones.append("evaluar")
        return ResumenEvaluacion(evaluada_en=AHORA, abiertas=["X:1"], resueltas=["Y:2"])
