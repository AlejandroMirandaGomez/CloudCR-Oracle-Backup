from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from typing import Any

from cloudcr_backup.alerts.instantanea import (
    BaseMonitoreada,
    EstrategiaMonitoreada,
    Instantanea,
    ScriptVigente,
    TareaMonitoreada,
    UsoDisco,
)
from cloudcr_backup.domain.alertas import Condicion, SeveridadAlerta, VistaAlerta
from cloudcr_backup.domain.enums import (
    EstadoAlerta,
    EstadoEjecucion,
    EstadoPrueba,
    LogMode,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Programacion
from cloudcr_backup.domain.historial import FilaHistorial
from cloudcr_backup.domain.perfil_bd import PerfilBD

AHORA = datetime(2026, 10, 3, 18, 0, tzinfo=UTC)
APROBADO = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
DESTINO = r"C:\backups\XE"


def fila(
    ejecucion_id: int = 40,
    estado: EstadoEjecucion = EstadoEjecucion.EXITOSA,
    prueba: EstadoPrueba = EstadoPrueba.OK,
    programada: datetime = datetime(2026, 10, 3, 17, 0, tzinfo=UTC),
    mensaje: str | None = None,
    tamano: int | None = None,
) -> FilaHistorial:
    return FilaHistorial(
        ejecucion_id=ejecucion_id,
        bd="XE",
        bd_id=1,
        estrategia="EST001",
        estrategia_id=2,
        estrategia_nombre="Producción diaria",
        tarea="T1",
        tarea_id=3,
        tipo_respaldo=TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO,
        modo_respaldo=ModoRespaldo.EN_LINEA,
        estado=estado,
        estado_prueba=prueba,
        programada_para=programada,
        inicio=programada,
        fin=programada,
        duracion_segundos=60,
        tamano_bytes=tamano,
        zona_horaria="America/Costa_Rica",
        mensaje=mensaje,
    )


def tarea(**cambios: Any) -> TareaMonitoreada:
    datos: dict[str, Any] = {
        "tarea_id": 3,
        "codigo": "T1",
        "tipo_respaldo": TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO,
        "modo_respaldo": ModoRespaldo.EN_LINEA,
        "programacion": Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
        "destino_ruta": DESTINO,
        "script": ScriptVigente(script_id=9, aprobado_en=APROBADO, log_mode_al_crear=LogMode.ARCHIVELOG),
        "ultimas": [fila()],
    }
    datos.update(cambios)
    return TareaMonitoreada(**datos)


def estrategia(*tareas: TareaMonitoreada, **cambios: Any) -> EstrategiaMonitoreada:
    datos: dict[str, Any] = {
        "estrategia_id": 2,
        "bd_id": 1,
        "bd_nombre": "XE",
        "codigo": "EST001",
        "nombre": "Producción diaria",
        "prioridad": Prioridad.ALTA,
        "alcance": ["XEPDB1:VENTAS", "XEPDB1:FINANZAS"],
        "purga_automatica": False,
        "tareas": list(tareas) if tareas else [tarea()],
        "ultimo_exito": datetime(2026, 10, 3, 17, 5, tzinfo=UTC),
    }
    datos.update(cambios)
    return EstrategiaMonitoreada(**datos)


def instantanea(
    perfil: PerfilBD | None,
    *estrategias: EstrategiaMonitoreada,
    parametros: dict[str, str] | None = None,
    uso: dict[str, UsoDisco | None] | None = None,
    ahora: datetime = AHORA,
) -> Instantanea:
    return Instantanea(
        ahora=ahora,
        bases=[BaseMonitoreada(bd_id=1, nombre="XE", perfil=perfil)],
        estrategias=list(estrategias) if estrategias else [estrategia()],
        parametros=parametros or {},
        uso_disco=uso or {},
    )


@dataclass
class FuenteAlertasMemoria:
    actual: Instantanea
    alertas: list[VistaAlerta] = field(default_factory=list)
    resueltas: list[int] = field(default_factory=list)

    def instantanea(self, ahora: datetime) -> Instantanea:
        return self.actual

    def vigentes(self) -> list[VistaAlerta]:
        return [a for a in self.alertas if a.estado in (EstadoAlerta.ABIERTA, EstadoAlerta.RECONOCIDA)]

    def abrir(self, condicion: Condicion) -> tuple[VistaAlerta, bool]:
        for indice, alerta in enumerate(self.alertas):
            if alerta.clave_dedup == condicion.clave_dedup and alerta.vigente:
                actualizada = alerta.model_copy(update={"mensaje": condicion.mensaje})
                self.alertas[indice] = actualizada
                return actualizada, False
        nueva = VistaAlerta(
            id=len(self.alertas) + 1,
            codigo=condicion.codigo_regla,
            clave_dedup=condicion.clave_dedup,
            severidad=condicion.severidad,
            estado=EstadoAlerta.ABIERTA,
            mensaje=condicion.mensaje,
            bd="XE",
            estrategia="EST001",
            tarea="T1",
            abierta_en=AHORA,
        )
        self.alertas.append(nueva)
        return nueva, True

    def resolver(self, alerta_id: int) -> bool:
        for indice, alerta in enumerate(self.alertas):
            if alerta.id == alerta_id and alerta.vigente:
                self.alertas[indice] = alerta.model_copy(update={"estado": EstadoAlerta.RESUELTA})
                self.resueltas.append(alerta_id)
                return True
        return False

    def reconocer(self, alerta_id: int) -> None:
        for indice, alerta in enumerate(self.alertas):
            if alerta.id == alerta_id:
                self.alertas[indice] = alerta.model_copy(update={"estado": EstadoAlerta.RECONOCIDA})


@dataclass
class NotificadorMemoria:
    nombre: str = "memoria"
    recibidas: list[tuple[VistaAlerta, Condicion]] = field(default_factory=list)
    fallar: bool = False

    def notificar(self, alerta: VistaAlerta, condicion: Condicion) -> None:
        if self.fallar:
            raise ConnectionError("SMTP caído")
        self.recibidas.append((alerta, condicion))


def severidades(condiciones: list[Condicion]) -> list[SeveridadAlerta]:
    return [c.severidad for c in condiciones]
