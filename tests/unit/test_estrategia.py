from datetime import time

from cloudcr_backup.domain.enums import (
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import (
    Como,
    Destino,
    Estrategia,
    ObjetoAlcance,
    Programacion,
    Tarea,
    Ventana,
)


def _estrategia_est001() -> Estrategia:
    return Estrategia(
        bd_id=1,
        codigo="EST001",
        nombre="Producción diaria",
        prioridad=Prioridad.ALTA,
        creada_por="luis",
        alcance=[
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA),
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:FINANZAS", prioridad=Prioridad.ALTA),
        ],
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO, modo_respaldo=ModoRespaldo.EN_LINEA),
                programacion=Programacion(
                    tipo_frecuencia=TipoFrecuencia.DIARIA,
                    horas=[time(13, 0), time(15, 0), time(18, 0), time(21, 0)],
                    ventana=Ventana(inicio=time(12, 30), fin=time(22, 0)),
                ),
                destino=Destino(ruta=r"C:\backups\XE"),
            )
        ],
    )


def test_estrategia_guarda_el_alcance_y_las_tareas() -> None:
    estrategia = _estrategia_est001()
    assert len(estrategia.alcance) == 2
    assert estrategia.tarea("T1") is not None
    assert estrategia.tarea("T9") is None


def test_tarea_conserva_su_horario() -> None:
    tarea = _estrategia_est001().tarea("T1")
    assert tarea is not None
    assert tarea.programacion.horas == [time(13, 0), time(15, 0), time(18, 0), time(21, 0)]


def test_ventana_normal_contiene_horas_dentro_del_rango() -> None:
    ventana = Ventana(inicio=time(12, 30), fin=time(22, 0))
    assert ventana.contiene(time(13, 0))
    assert not ventana.contiene(time(23, 0))
    assert not ventana.cruza_medianoche


def test_ventana_que_cruza_medianoche_acepta_horas_de_ambos_lados() -> None:
    ventana = Ventana(inicio=time(22, 30), fin=time(2, 0))
    assert ventana.cruza_medianoche
    assert ventana.contiene(time(23, 45))
    assert ventana.contiene(time(1, 0))
    assert not ventana.contiene(time(3, 0))


def test_retencion_por_defecto_no_purga_automaticamente() -> None:
    estrategia = _estrategia_est001()
    assert estrategia.retencion.purga_automatica is False
