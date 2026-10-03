from datetime import datetime, time
from typing import Any

import pytest

from cloudcr_backup.domain.enums import (
    EstadoEjecucion,
    EstadoEstrategia,
    EstadoPrueba,
    EstadoScript,
    LogMode,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.repository import alertas as repositorio_alertas
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import conexion as repositorio_conexion
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import scripts as repositorio_scripts
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.repository.ejecuciones import (
    DetalleEjecucionRepositorio,
    Ejecucion,
    EjecucionDetallada,
    EjecucionInterrumpida,
)
from cloudcr_backup.repository.scripts import ScriptRman
from tests.unit.oracle_falso import ConexionFalsa

APROBADO = datetime(2026, 10, 1, 18, 0)
PROGRAMADA = datetime(2026, 10, 3, 19, 0)


def estrategia_registrada(estado: EstadoEstrategia = EstadoEstrategia.ACTIVA) -> Estrategia:
    return Estrategia(
        id=2,
        bd_id=1,
        codigo="EST001",
        nombre="Producción diaria",
        prioridad=Prioridad.ALTA,
        estado=estado,
        creada_por="luis",
        alcance=[
            ObjetoAlcance(tipo=TipoObjeto.TABLESPACE, identificador="XEPDB1:VENTAS", prioridad=Prioridad.ALTA),
            ObjetoAlcance(tipo=TipoObjeto.CONTROLFILE, identificador="", prioridad=Prioridad.ALTA),
        ],
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.EN_LINEA),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(13, 0)]),
                destino=Destino(ruta=r"C:\backups\XE"),
            ),
            Tarea(
                codigo="T2",
                como=Como(tipo_respaldo=TipoRespaldo.ARCHIVELOG),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.INTERVALO, intervalo_minutos=60),
                destino=Destino(ruta=r"C:\backups\XE"),
            ),
        ],
    )


def detallada(estado: EstadoEjecucion = EstadoEjecucion.FALLIDA) -> EjecucionDetallada:
    return EjecucionDetallada(
        id=40, bd_id=1, bd_nombre="XE", estrategia_id=2, estrategia_codigo="EST001",
        estrategia_nombre="Producción diaria", tarea_id=3, tarea_codigo="T1", tipo_respaldo="COMPLETO",
        modo_respaldo="EN_LINEA", estado=estado, estado_prueba=EstadoPrueba.PENDIENTE, programada_para=PROGRAMADA,
        inicio=PROGRAMADA, fin=None, duracion_segundos=None, tamano_bytes=None, archivos_generados=None,
        ubicacion=None, zona_horaria="America/Costa_Rica", mensaje_rman="RMAN-03009", agente="SERVIDOR", script_id=9,
    )


@pytest.fixture
def repositorio_parcheado(monkeypatch: pytest.MonkeyPatch, perfil_xe: PerfilBD) -> dict[str, Any]:
    estado: dict[str, Any] = {"reclamadas": [], "estrategia": estrategia_registrada()}
    bd = BaseDatosRegistrada(id=1, nombre="XE", oracle_home=r"C:\oracle", ambiente=Ambiente.PRUEBAS, activa=True)
    script = ScriptRman(9, 3, 1, "", "abc", EstadoScript.APROBADO, "ale", APROBADO, APROBADO)
    monkeypatch.setattr(repositorio_parametros, "listar", lambda c: {"agente.gracia_omision_min": "15"})
    monkeypatch.setattr(repositorio_bases_datos, "listar", lambda c: [bd])
    monkeypatch.setattr(repositorio_bases_datos, "ultimo_perfil", lambda c, bd_id: perfil_xe)
    monkeypatch.setattr(repositorio_bases_datos, "log_mode_al_crear_script", lambda c, b, s: LogMode.ARCHIVELOG)
    monkeypatch.setattr(repositorio_estrategias, "listar", lambda c, bd_id: [estado["estrategia"]])
    monkeypatch.setattr(repositorio_estrategias, "ids_de_tareas", lambda c, e: {"T1": 3, "T2": 4})
    monkeypatch.setattr(repositorio_scripts, "vigentes_por_tarea", lambda c: {3: script})
    monkeypatch.setattr(repositorio_ejecuciones, "ultima_programada_por_tarea", lambda c: {3: PROGRAMADA})
    monkeypatch.setattr(repositorio_ejecuciones, "ultimas_por_tarea", lambda c, n: {3: [detallada()]})
    monkeypatch.setattr(repositorio_ejecuciones, "ultimo_exito_por_estrategia", lambda c: {})
    monkeypatch.setattr(repositorio_ejecuciones, "tamano_ultimo_exito_por_tarea", lambda c: {3: 1024})
    monkeypatch.setattr(repositorio_ejecuciones, "piezas_vencidas_por_estrategia", lambda c, a: {2: 1})

    def reclamar(c: Any, tarea_id: int, momento: datetime) -> Ejecucion:
        estado["reclamadas"].append(momento)
        return Ejecucion(41, tarea_id, 9, EstadoEjecucion.PROGRAMADA, momento, None, None)

    monkeypatch.setattr(repositorio_ejecuciones, "reclamar", reclamar)
    monkeypatch.setattr(repositorio_ejecuciones, "en_curso", lambda c: [])
    monkeypatch.setattr(repositorio_alertas, "vigentes", lambda c: [])
    monkeypatch.setattr(repositorio_bases_datos, "obtener", lambda c, nombre: bd if nombre == "XE" else None)

    def historial_detallado(c: Any, filtros: Any, limite: int, desplazamiento: int) -> list[EjecucionDetallada]:
        estado["filtros"] = filtros
        estado["paginacion"] = (limite, desplazamiento)
        return [detallada()]

    monkeypatch.setattr(repositorio_ejecuciones, "historial_detallado", historial_detallado)
    monkeypatch.setattr(repositorio_ejecuciones, "contar_historial", lambda c, f: 1)
    monkeypatch.setattr(
        repositorio_ejecuciones,
        "detalle",
        lambda c, i: DetalleEjecucionRepositorio(detallada(), "RMAN-03009", None, 1, "abc", "ale", APROBADO)
        if i == 40
        else None,
    )
    monkeypatch.setattr(repositorio_ejecuciones, "piezas", lambda c, i: [])
    monkeypatch.setattr(repositorio_ejecuciones, "verificaciones", lambda c, i: [])
    monkeypatch.setattr(repositorio_conexion, "abrir_repositorio", lambda a: ConexionFalsa())
    monkeypatch.setattr(
        repositorio_ejecuciones,
        "en_curso_de_agente",
        lambda c, a: [EjecucionInterrumpida(7, 3, PROGRAMADA, "CONSISTENTE")],
    )
    return estado
