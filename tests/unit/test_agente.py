import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from cloudcr_backup.agent import latido
from cloudcr_backup.agent.bucle import MOTIVO_INTERRUMPIDA, Agente, ConfiguracionAgente, ParametrosAgente
from cloudcr_backup.alerts.instantanea import Instantanea
from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.alertas import Condicion, VistaAlerta
from cloudcr_backup.domain.enums import EstadoEjecucion, ModoRespaldo
from cloudcr_backup.domain.errores import PipelineNoDisponible, RepositorioNoDisponible
from cloudcr_backup.domain.monitoreo import EstadoLatido
from cloudcr_backup.domain.planificacion import EjecucionEnCurso
from cloudcr_backup.scheduling.reloj import RelojFijo
from cloudcr_backup.services import agente as servicio_agente
from tests.unit.alertas_falsas import FuenteAlertasMemoria, instantanea
from tests.unit.fuentes_falsas import EjecucionMemoria, FuenteMemoria, tarea_programable

INICIO = datetime(2026, 10, 3, 16, 0, 10, tzinfo=UTC)


class SesionFalsa(FuenteMemoria):
    def __init__(self, eventos: list[str]) -> None:
        super().__init__(tareas=[tarea_programable(intervalo=5)])
        self.eventos = eventos
        self.valores: dict[str, str] = {"agente.tick_segundos": "30", "alertas.eval_minutos": "5"}
        self.alertas = FuenteAlertasMemoria(instantanea(None))
        self.en_curso: list[EjecucionEnCurso] = []
        self.interrumpidas: list[int] = []

    def parametros(self) -> dict[str, str]:
        self.eventos.append("parametros")
        return dict(self.valores)

    def reclamar(self, tarea_id: int, programada_para: datetime) -> int | None:
        self.eventos.append("reclamar")
        return super().reclamar(tarea_id, programada_para)

    def instantanea(self, ahora: datetime) -> Instantanea:
        self.eventos.append("evaluar")
        return self.alertas.instantanea(ahora)

    def vigentes(self) -> list[VistaAlerta]:
        return self.alertas.vigentes()

    def abrir(self, condicion: Condicion) -> tuple[VistaAlerta, bool]:
        return self.alertas.abrir(condicion)

    def resolver(self, alerta_id: int) -> bool:
        return self.alertas.resolver(alerta_id)

    def en_curso_de_agente(self, agente: str) -> list[EjecucionEnCurso]:
        return list(self.en_curso)

    def marcar_interrumpida(self, ejecucion_id: int, motivo: str) -> bool:
        assert motivo == MOTIVO_INTERRUMPIDA
        self.interrumpidas.append(ejecucion_id)
        return True


class EjecutorFalso:
    def __init__(self, eventos: list[str], fallar: bool = False) -> None:
        self.eventos = eventos
        self.fallar = fallar
        self.ejecutadas: list[int] = []
        self.aperturas: list[int] = []
        self.liberar = threading.Event()
        self.liberar.set()

    def ejecutar(self, ejecucion_id: int) -> None:
        self.liberar.wait(timeout=5)
        self.eventos.append("ejecutar")
        self.ejecutadas.append(ejecucion_id)
        if self.fallar:
            raise RuntimeError("RMAN no respondió")

    def asegurar_apertura(self, ejecucion_id: int) -> None:
        self.aperturas.append(ejecucion_id)


class Escenario:
    def __init__(self, carpeta: Path, fallar_ejecutor: bool = False) -> None:
        self.eventos: list[str] = []
        self.sesion = SesionFalsa(self.eventos)
        self.sesion.ejecuciones.append(
            EjecucionMemoria(99, 3, datetime(2026, 10, 3, 15, 55, tzinfo=UTC), EstadoEjecucion.EXITOSA)
        )
        self.ejecutor = EjecutorFalso(self.eventos, fallar_ejecutor)
        self.reloj = RelojFijo(INICIO)
        self.fallos_pendientes = 0
        self.avisos: list[str] = []
        self.carpeta = carpeta
        self.agente = Agente(
            fabrica_sesion=self.fabrica,
            ejecutor=self.ejecutor,
            configuracion=ConfiguracionAgente(hostname="SERVIDOR", carpeta_latido=carpeta, version="0.1.0"),
            reloj=self.reloj,
            sincronizar_buzon=lambda: self.eventos.append("buzon"),
            avisar=self.avisos.append,
        )

    @contextmanager
    def fabrica(self) -> Iterator[Any]:
        if self.fallos_pendientes:
            self.fallos_pendientes -= 1
            raise RepositorioNoDisponible("ORA-12541: no listener")
        yield self.sesion


@pytest.fixture
def escenario(tmp_path: Path) -> Escenario:
    return Escenario(tmp_path / "agente")


def test_orden_del_tick(escenario: Escenario) -> None:
    resultado = escenario.agente.tick()
    escenario.agente.esperar_ejecuciones()
    assert [r.programada_para for r in resultado.reclamadas] == [datetime(2026, 10, 3, 16, 0, tzinfo=UTC)]
    eventos = escenario.eventos
    assert eventos.index("buzon") < eventos.index("parametros") < eventos.index("reclamar") < eventos.index("evaluar")
    assert "ejecutar" in eventos
    assert escenario.ejecutor.ejecutadas == [resultado.reclamadas[0].ejecucion_id]
    assert resultado.evaluacion is not None


def test_el_tick_escribe_el_latido(escenario: Escenario) -> None:
    escenario.agente.tick()
    [registro] = latido.leer_todos(escenario.carpeta)
    assert registro.hostname == "SERVIDOR"
    assert registro.estado is EstadoLatido.ACTIVO
    assert registro.ultimo_tick == INICIO


def test_los_parametros_se_releen_en_cada_tick(escenario: Escenario) -> None:
    escenario.agente.tick()
    assert escenario.agente.parametros.tick_segundos == 30
    escenario.sesion.valores["agente.tick_segundos"] = "10"
    escenario.sesion.valores["agente.gracia_omision_min"] = "1"
    escenario.reloj.fijar(INICIO + timedelta(minutes=5, seconds=5))
    escenario.agente.tick()
    assert escenario.agente.parametros.tick_segundos == 10
    assert escenario.agente.parametros.gracia == timedelta(minutes=1)
    escenario.agente.esperar_ejecuciones()


def test_parametros_invalidos_usan_los_valores_por_defecto() -> None:
    parametros = ParametrosAgente.desde({"agente.tick_segundos": "abc", "agente.max_paralelo_host": "0"})
    assert parametros.tick_segundos == 30
    assert parametros.max_paralelo == 1


def test_una_excepcion_en_un_tick_no_detiene_al_agente(escenario: Escenario) -> None:
    escenario.fallos_pendientes = 1
    primero = escenario.agente.tick()
    assert primero.errores and "RepositorioNoDisponible" in primero.errores[0]
    segundo = escenario.agente.tick()
    escenario.agente.esperar_ejecuciones()
    assert segundo.errores == []
    assert len(segundo.reclamadas) == 1


def test_al_arrancar_las_propias_en_curso_pasan_a_fallida(escenario: Escenario) -> None:
    momento = datetime(2026, 10, 3, 15, 0, tzinfo=UTC)
    escenario.sesion.en_curso = [
        EjecucionEnCurso(7, 3, momento, ModoRespaldo.EN_LINEA),
        EjecucionEnCurso(8, 4, momento, ModoRespaldo.CONSISTENTE),
    ]
    resultado = escenario.agente.tick()
    escenario.agente.esperar_ejecuciones()
    assert resultado.interrumpidas == [7, 8]
    assert escenario.sesion.interrumpidas == [7, 8]
    assert escenario.ejecutor.aperturas == [8]
    escenario.sesion.interrumpidas.clear()
    escenario.agente.tick()
    assert escenario.sesion.interrumpidas == []


def test_la_recuperacion_se_reintenta_si_el_repositorio_estaba_caido(escenario: Escenario) -> None:
    escenario.sesion.en_curso = [EjecucionEnCurso(7, 3, INICIO, ModoRespaldo.EN_LINEA)]
    escenario.fallos_pendientes = 1
    assert escenario.agente.tick().interrumpidas == []
    assert escenario.agente.tick().interrumpidas == [7]
    escenario.agente.esperar_ejecuciones()


def test_las_alertas_se_evaluan_cada_eval_minutos_o_tras_una_ejecucion(escenario: Escenario) -> None:
    escenario.sesion.tareas = []
    assert escenario.agente.tick().evaluacion is not None
    escenario.reloj.fijar(INICIO + timedelta(minutes=1))
    assert escenario.agente.tick().evaluacion is None
    escenario.reloj.fijar(INICIO + timedelta(minutes=5))
    assert escenario.agente.tick().evaluacion is not None


def test_terminar_una_ejecucion_adelanta_la_evaluacion(escenario: Escenario) -> None:
    escenario.ejecutor.liberar.clear()
    assert escenario.agente.tick().evaluacion is not None
    escenario.ejecutor.liberar.set()
    escenario.agente.esperar_ejecuciones()
    escenario.reloj.fijar(INICIO + timedelta(seconds=30))
    assert escenario.agente.tick().evaluacion is not None


def test_una_ejecucion_que_lanza_no_rompe_al_agente(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path, fallar_ejecutor=True)
    escenario.agente.tick()
    escenario.agente.esperar_ejecuciones()
    assert escenario.agente.en_cola == set()
    assert any("terminó con error" in aviso for aviso in escenario.avisos)
    escenario.reloj.fijar(INICIO + timedelta(seconds=30))
    assert escenario.agente.tick().errores == []


def test_una_vez_ejecuta_un_tick_espera_y_deja_latido_detenido(escenario: Escenario) -> None:
    assert escenario.agente.ejecutar(una_vez=True) == 0
    assert escenario.ejecutor.ejecutadas
    [registro] = latido.leer_todos(escenario.carpeta)
    assert registro.estado is EstadoLatido.DETENIDO


def test_detener_corta_el_bucle(escenario: Escenario) -> None:
    resultado: list[int] = []
    hilo = threading.Thread(target=lambda: resultado.append(escenario.agente.ejecutar()))
    hilo.start()
    time.sleep(0.2)
    escenario.agente.detener()
    hilo.join(timeout=5)
    assert resultado == [0]
    assert latido.leer_todos(escenario.carpeta)[0].estado is EstadoLatido.DETENIDO


def test_los_avisos_rotulan_la_simulacion(tmp_path: Path) -> None:
    escenario = Escenario(tmp_path)
    avisos: list[str] = []
    agente = Agente(
        fabrica_sesion=escenario.fabrica,
        ejecutor=escenario.ejecutor,
        configuracion=ConfiguracionAgente("SERVIDOR", tmp_path, "0.1.0", simulado=True),
        reloj=escenario.reloj,
        avisar=avisos.append,
    )
    agente.ejecutar(una_vez=True)
    assert any("[SIMULACIÓN]" in aviso for aviso in avisos)
    assert latido.leer_todos(tmp_path)[0].simulado


def test_sin_pipeline_real_el_agente_se_niega_a_correr(tmp_path: Path) -> None:
    ajustes = Ajustes(work_dir=tmp_path)
    assert servicio_agente.pipeline_disponible() is None
    with pytest.raises(PipelineNoDisponible) as error:
        servicio_agente.crear_ejecutor(ajustes, "SERVIDOR", simulado=False)
    assert "--simulado" in (error.value.sugerencia or "")
    simulado = servicio_agente.crear_ejecutor(ajustes, "SERVIDOR", simulado=True)
    assert isinstance(simulado, servicio_agente.EjecutorSimulado)


def test_latido_viejo_se_considera_detenido(tmp_path: Path) -> None:
    agente = Agente(
        fabrica_sesion=Escenario(tmp_path).fabrica,
        ejecutor=EjecutorFalso([]),
        configuracion=ConfiguracionAgente("SERVIDOR", tmp_path, "0.1.0"),
        reloj=RelojFijo(INICIO),
    )
    agente.escribir_latido(EstadoLatido.ACTIVO)
    [registro] = latido.leer_todos(tmp_path)
    assert latido.esta_vivo(registro, INICIO + timedelta(seconds=89), 30)
    assert not latido.esta_vivo(registro, INICIO + timedelta(seconds=91), 30)
    estado = latido.estado_de(registro, INICIO + timedelta(seconds=91), 30)
    assert estado.segundos_desde_tick == 91 and not estado.vivo


def test_latidos_ilegibles_se_ignoran(tmp_path: Path) -> None:
    (tmp_path / "latido_roto.json").write_text("{no es json", encoding="utf-8")
    assert latido.leer_todos(tmp_path) == []
    assert latido.leer_todos(tmp_path / "no-existe") == []
