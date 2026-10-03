from datetime import UTC, datetime, time
from pathlib import Path

from cloudcr_backup.domain.enums import TipoFrecuencia
from cloudcr_backup.domain.estrategia import Programacion
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml
from cloudcr_backup.validation import motor, reglas  # noqa: F401
from cloudcr_backup.validation.contexto import ContextoValidacion

RAIZ = Path(__file__).resolve().parents[2]
AHORA = datetime(2026, 10, 2, 14, 0, tzinfo=UTC)


def _contexto(perfil: PerfilBD, programacion: Programacion | None = None) -> ContextoValidacion:
    estrategia = cargar_estrategia_yaml(RAIZ / "config" / "estrategias" / "est001.yaml")
    if programacion is not None:
        tarea = estrategia.tareas[0].model_copy(update={"programacion": programacion})
        estrategia = estrategia.model_copy(update={"tareas": [tarea]})
    return ContextoValidacion(estrategia=estrategia, perfil=perfil, ahora=AHORA)


def test_prg_007_muestra_las_proximas_cinco_ejecuciones(perfil_xe: PerfilBD) -> None:
    hallazgos = [h for h in motor.validar(_contexto(perfil_xe)) if h.codigo == "PRG_007"]
    assert len(hallazgos) == 1
    assert hallazgos[0].severidad.value == "INFORMATIVA"
    assert hallazgos[0].sujeto == "T1"
    assert "vie 02/10 13:00, vie 02/10 15:00, vie 02/10 18:00, vie 02/10 21:00, sáb 03/10 13:00" in (
        hallazgos[0].mensaje
    )


def test_prg_007_no_aparece_si_la_programacion_esta_incompleta(perfil_xe: PerfilBD) -> None:
    incompleta = Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA)
    codigos = [h.codigo for h in motor.validar(_contexto(perfil_xe, incompleta))]
    assert "PRG_007" not in codigos
    assert "PRG_002" in codigos


def test_prg_007_no_aparece_si_ya_no_hay_ocurrencias(perfil_xe: PerfilBD) -> None:
    pasada = Programacion(
        tipo_frecuencia=TipoFrecuencia.UNA_VEZ, horas=[time(1, 0)], fecha_inicio=datetime(2026, 1, 1).date()
    )
    assert "PRG_007" not in [h.codigo for h in motor.validar(_contexto(perfil_xe, pasada))]
