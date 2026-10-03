import json
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import oracledb
import pytest

from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.domain.alertas import Condicion, SeveridadAlerta
from cloudcr_backup.domain.enums import (
    EstadoAlerta,
    EstadoEjecucion,
    EstadoEstrategia,
    LogMode,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.domain.planificacion import EjecucionPendiente, TareaProgramable
from cloudcr_backup.repository import alertas, bases_datos, ejecuciones, esquema, estrategias, scripts
from cloudcr_backup.repository.bases_datos import Ambiente
from cloudcr_backup.repository.conexion import abrir_repositorio
from cloudcr_backup.repository.ejecuciones import FiltrosHistorial
from cloudcr_backup.scheduling.planificador import Planificador
from cloudcr_backup.services.fuente_oracle import FuenteOracle

pytestmark = pytest.mark.oracle

RAIZ = Path(__file__).resolve().parents[2]
TOLERANCIA_RELOJ = timedelta(minutes=2)


class FuenteAcotada(FuenteOracle):
    def __init__(self, conexion: oracledb.Connection, tarea_id: int) -> None:
        super().__init__(conexion)
        self._tarea_id = tarea_id

    def tareas_programables(self) -> list[TareaProgramable]:
        return [t for t in super().tareas_programables() if t.tarea_id == self._tarea_id]

    def programadas_sin_iniciar(self, antes_de: datetime) -> list[EjecucionPendiente]:
        return [e for e in super().programadas_sin_iniciar(antes_de) if e.tarea_id == self._tarea_id]


@dataclass(frozen=True)
class Escenario:
    bd_id: int
    bd_nombre: str
    tarea_id: int
    script_id: int


@pytest.fixture(scope="module")
def conexion() -> Iterator[oracledb.Connection]:
    conexion = abrir_repositorio(cargar_ajustes())
    if not esquema.estado(conexion).instalado:
        esquema.instalar(conexion)
    yield conexion
    conexion.close()


def _borrar(conexion: oracledb.Connection, bd_id: int) -> None:
    sentencias = (
        "DELETE FROM alerta WHERE bd_id = :bd_id",
        "DELETE FROM ejecucion_pieza WHERE ejecucion_id IN (SELECT id FROM ejecucion WHERE bd_id = :bd_id)",
        "DELETE FROM verificacion WHERE ejecucion_id IN (SELECT id FROM ejecucion WHERE bd_id = :bd_id)",
        "DELETE FROM ejecucion WHERE bd_id = :bd_id",
        "DELETE FROM script_rman WHERE tarea_id IN (SELECT t.id FROM tarea t JOIN estrategia e "
        "ON e.id = t.estrategia_id WHERE e.bd_id = :bd_id)",
        "DELETE FROM programacion WHERE tarea_id IN (SELECT t.id FROM tarea t JOIN estrategia e "
        "ON e.id = t.estrategia_id WHERE e.bd_id = :bd_id)",
        "DELETE FROM tarea WHERE estrategia_id IN (SELECT id FROM estrategia WHERE bd_id = :bd_id)",
        "DELETE FROM estrategia_objeto WHERE estrategia_id IN (SELECT id FROM estrategia WHERE bd_id = :bd_id)",
        "DELETE FROM estrategia WHERE bd_id = :bd_id",
        "DELETE FROM perfil_bd WHERE bd_id = :bd_id",
        "DELETE FROM bd_registrada WHERE id = :bd_id",
    )
    cursor = conexion.cursor()
    try:
        for sentencia in sentencias:
            cursor.execute(sentencia, bd_id=bd_id)
        conexion.commit()
    finally:
        cursor.close()


@pytest.fixture
def escenario(conexion: oracledb.Connection) -> Iterator[Escenario]:
    nombre = f"PYT{datetime.now():%H%M%S%f}"[:30]
    bd = bases_datos.registrar(conexion, nombre, r"C:\oracle", Ambiente.PRUEBAS)
    try:
        estrategia = Estrategia(
            bd_id=bd.id,
            codigo="ESTAG",
            nombre="Estrategia de prueba del agente",
            prioridad=Prioridad.ALTA,
            estado=EstadoEstrategia.ACTIVA,
            creada_por="pytest",
            alcance=[ObjetoAlcance(tipo=TipoObjeto.BASE_DATOS, identificador="", prioridad=Prioridad.ALTA)],
            tareas=[
                Tarea(
                    codigo="T1",
                    como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.EN_LINEA),
                    programacion=Programacion(tipo_frecuencia=TipoFrecuencia.INTERVALO, intervalo_minutos=5),
                    destino=Destino(ruta=r"C:\backups\XE"),
                )
            ],
        )
        estrategias.crear(conexion, estrategia)
        tarea_id = estrategias.obtener_tarea_id(conexion, bd.id, "ESTAG", "T1")
        assert tarea_id is not None
        borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
        scripts.aprobar(conexion, borrador.id, "pytest")
        yield Escenario(bd.id, nombre, tarea_id, borrador.id)
    finally:
        _borrar(conexion, bd.id)


def test_g8_hora_del_servidor_y_horas_guardadas_en_utc(
    conexion: oracledb.Connection, escenario: Escenario, capsys: pytest.CaptureFixture[str]
) -> None:
    cursor = conexion.cursor()
    cursor.execute("SELECT SYSTIMESTAMP, SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM dual")
    local, utc = cursor.fetchone()
    cursor.close()
    with capsys.disabled():
        print(f"\nG8: SYSTIMESTAMP={local} SYS_EXTRACT_UTC={utc}")
    reclamada = ejecuciones.reclamar(conexion, escenario.tarea_id, datetime(2026, 1, 1, 19, 0))
    assert reclamada is not None
    ejecuciones.marcar_en_curso(conexion, reclamada.id, "pytest")
    detalle = ejecuciones.detalle(conexion, reclamada.id)
    assert detalle is not None and detalle.ejecucion.inicio is not None
    ahora_utc = datetime.now(UTC).replace(tzinfo=None)
    assert abs(detalle.ejecucion.inicio - ahora_utc) < TOLERANCIA_RELOJ
    vigente = scripts.vigentes_por_tarea(conexion)[escenario.tarea_id]
    assert vigente.aprobado_en is not None
    assert abs(vigente.aprobado_en - ahora_utc) < TOLERANCIA_RELOJ


def test_reclamar_dos_veces_la_misma_ocurrencia(conexion: oracledb.Connection, escenario: Escenario) -> None:
    fuente = FuenteOracle(conexion)
    momento = datetime(2026, 1, 2, 19, 0, tzinfo=UTC)
    assert fuente.reclamar(escenario.tarea_id, momento) is not None
    assert fuente.reclamar(escenario.tarea_id, momento) is None
    assert not fuente.registrar_no_ejecutada(escenario.tarea_id, momento, "duplicada")


def test_registrar_y_marcar_no_ejecutadas(conexion: oracledb.Connection, escenario: Escenario) -> None:
    fuente = FuenteOracle(conexion)
    momento = datetime(2026, 1, 3, 19, 0, tzinfo=UTC)
    assert fuente.registrar_no_ejecutada(escenario.tarea_id, momento, "agente detenido")
    reclamada = fuente.reclamar(escenario.tarea_id, momento + timedelta(minutes=5))
    assert reclamada is not None
    sin_iniciar = fuente.programadas_sin_iniciar(momento + timedelta(hours=1))
    pendientes = [p for p in sin_iniciar if p.ejecucion_id == reclamada]
    assert len(pendientes) == 1
    assert fuente.marcar_no_ejecutada(reclamada, "huérfana")
    assert not fuente.marcar_no_ejecutada(reclamada, "otra vez")
    filas = ejecuciones.historial_detallado(conexion, FiltrosHistorial(bd_id=escenario.bd_id), 50, 0)
    assert {f.estado for f in filas} == {EstadoEjecucion.NO_EJECUTADA}
    assert ejecuciones.contar_historial(conexion, FiltrosHistorial(bd_id=escenario.bd_id)) == 2
    assert filas[0].bd_nombre == escenario.bd_nombre
    assert filas[0].zona_horaria == "America/Costa_Rica"


def test_interrumpidas_del_agente(conexion: oracledb.Connection, escenario: Escenario) -> None:
    fuente = FuenteOracle(conexion)
    reclamada = fuente.reclamar(escenario.tarea_id, datetime(2026, 1, 4, 19, 0, tzinfo=UTC))
    assert reclamada is not None
    ejecuciones.marcar_en_curso(conexion, reclamada, "agente-pytest")
    [en_curso] = [e for e in fuente.en_curso_de_agente("agente-pytest") if e.ejecucion_id == reclamada]
    assert en_curso.modo_respaldo is ModoRespaldo.EN_LINEA
    assert fuente.marcar_interrumpida(reclamada, "interrumpida")
    detalle = ejecuciones.detalle(conexion, reclamada)
    assert detalle is not None and detalle.ejecucion.estado is EstadoEjecucion.FALLIDA
    assert ejecuciones.ultimas_por_tarea(conexion, 5)[escenario.tarea_id][0].id == reclamada


def test_alertas_vigentes_no_se_duplican_y_se_resuelven(conexion: oracledb.Connection, escenario: Escenario) -> None:
    condicion = Condicion(
        codigo_regla="EJECUCION_FALLIDA",
        sujeto=f"{escenario.bd_nombre}/ESTAG/T1",
        severidad=SeveridadAlerta.ALERTA,
        mensaje="Falló",
        bd_id=escenario.bd_id,
        tarea_id=escenario.tarea_id,
    )
    primera, nueva = alertas.abrir(conexion, condicion)
    assert nueva and primera.severidad == "ALERTA" and primera.bd_nombre == escenario.bd_nombre
    assert alertas.reconocer_abierta(conexion, primera.id)
    segunda, nueva = alertas.abrir(conexion, condicion.model_copy(update={"mensaje": "Sigue fallando"}))
    assert not nueva
    assert segunda.id == primera.id and segunda.estado is EstadoAlerta.RECONOCIDA
    assert alertas.resolver_vigente(conexion, primera.id)
    assert not alertas.resolver_vigente(conexion, primera.id)
    assert all(a.id != primera.id for a in alertas.vigentes(conexion))


def test_perfil_y_modo_de_archivado_del_script(
    conexion: oracledb.Connection, escenario: Escenario, perfil_xe: PerfilBD
) -> None:
    assert bases_datos.ultimo_perfil(conexion, escenario.bd_id) is None
    bases_datos.guardar_perfil(conexion, escenario.bd_id, perfil_xe)
    guardado = bases_datos.ultimo_perfil(conexion, escenario.bd_id)
    assert guardado is not None and guardado.log_mode is LogMode.NOARCHIVELOG
    assert bases_datos.log_mode_al_crear_script(conexion, escenario.bd_id, escenario.script_id) is None
    borrador = scripts.guardar_borrador(conexion, escenario.tarea_id, "RUN { BACKUP DATABASE; }")
    assert bases_datos.log_mode_al_crear_script(conexion, escenario.bd_id, borrador.id) is LogMode.NOARCHIVELOG


PROGRAMA_AGENTE = """
import json, sys
from datetime import datetime
from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.repository.conexion import abrir_repositorio
from cloudcr_backup.scheduling.planificador import Planificador
from tests.integration.test_agente_oracle import FuenteAcotada

tarea_id, momento = int(sys.argv[1]), datetime.fromisoformat(sys.argv[2])
conexion = abrir_repositorio(cargar_ajustes())
resultado = Planificador(FuenteAcotada(conexion, tarea_id)).reclamar_vencidas(momento)
print(json.dumps({"reclamadas": len(resultado.reclamadas), "no_ejecutadas": len(resultado.no_ejecutadas)}))
"""


def test_dos_agentes_contra_el_mismo_repositorio_no_duplican(
    conexion: oracledb.Connection, escenario: Escenario
) -> None:
    aprobado = scripts.vigentes_por_tarea(conexion)[escenario.tarea_id].aprobado_en
    assert aprobado is not None
    momento = (aprobado + timedelta(hours=1)).replace(tzinfo=UTC)
    procesos = [
        subprocess.Popen(
            [sys.executable, "-c", PROGRAMA_AGENTE, str(escenario.tarea_id), momento.isoformat()],
            cwd=RAIZ,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    salidas = []
    for proceso in procesos:
        salida, error = proceso.communicate(timeout=120)
        assert proceso.returncode == 0, error
        salidas.append(json.loads(salida.strip().splitlines()[-1]))
    filas = ejecuciones.historial_detallado(conexion, FiltrosHistorial(bd_id=escenario.bd_id), 500, 0)
    momentos = [f.programada_para for f in filas]
    assert len(momentos) == len(set(momentos))
    assert sum(s["reclamadas"] for s in salidas) == 1
    assert [f.estado for f in filas].count(EstadoEjecucion.PROGRAMADA) == 1
    assert sum(s["no_ejecutadas"] for s in salidas) == len(filas) - 1


def test_proxima_ejecucion_de_una_tarea_del_repositorio(conexion: oracledb.Connection, escenario: Escenario) -> None:
    tareas = [t for t in FuenteOracle(conexion).tareas_programables() if t.tarea_id == escenario.tarea_id]
    assert len(tareas) == 1
    planificador = Planificador(FuenteAcotada(conexion, escenario.tarea_id))
    proxima = planificador.proxima_ejecucion(tareas[0], datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    assert proxima == datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
