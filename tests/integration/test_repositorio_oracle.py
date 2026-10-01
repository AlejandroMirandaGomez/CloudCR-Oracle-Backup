from collections.abc import Iterator
from datetime import datetime, time

import oracledb
import pytest

from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.domain.enums import (
    EstadoAlerta,
    EstadoEjecucion,
    EstadoEstrategia,
    EstadoScript,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.repository import alertas, bases_datos, ejecuciones, esquema, estrategias, parametros, scripts
from cloudcr_backup.repository.bases_datos import Ambiente
from cloudcr_backup.repository.conexion import abrir_repositorio

pytestmark = pytest.mark.oracle


@pytest.fixture(scope="module")
def conexion() -> Iterator[oracledb.Connection]:
    conexion = abrir_repositorio(cargar_ajustes())
    esquema.instalar(conexion)
    yield conexion
    esquema.desinstalar(conexion)
    conexion.close()


def _estrategia(bd_id: int, codigo: str) -> Estrategia:
    return Estrategia(
        bd_id=bd_id,
        codigo=codigo,
        nombre="Estrategia de prueba",
        prioridad=Prioridad.ALTA,
        creada_por="pytest",
        alcance=[ObjetoAlcance(tipo=TipoObjeto.BASE_DATOS, identificador="", prioridad=Prioridad.ALTA)],
        tareas=[
            Tarea(
                codigo="T1",
                como=Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=ModoRespaldo.AUTO),
                programacion=Programacion(tipo_frecuencia=TipoFrecuencia.DIARIA, horas=[time(2, 0)]),
                destino=Destino(ruta=r"C:\backups\XE"),
            )
        ],
    )


def test_esquema_instalar_es_idempotente(conexion: oracledb.Connection) -> None:
    esquema.instalar(conexion)
    info = esquema.estado(conexion)
    assert info.instalado
    assert set(info.tablas) == set(esquema.TABLAS)


def test_parametros_asignar_obtener_y_listar(conexion: oracledb.Connection) -> None:
    parametros.asignar(conexion, "clave.prueba", "1")
    assert parametros.obtener(conexion, "clave.prueba") == "1"
    parametros.asignar(conexion, "clave.prueba", "2")
    assert parametros.obtener(conexion, "clave.prueba") == "2"
    assert parametros.listar(conexion)["clave.prueba"] == "2"
    assert parametros.obtener(conexion, "no.existe") is None


def test_bases_datos_registrar_listar_obtener_y_desactivar(conexion: oracledb.Connection) -> None:
    registrada = bases_datos.registrar(conexion, "XETEST", r"C:\oracle", Ambiente.PRUEBAS)
    assert registrada.id > 0
    assert bases_datos.obtener(conexion, "XETEST") == registrada
    assert registrada in bases_datos.listar(conexion)
    with pytest.raises(bases_datos.BaseDatosYaRegistrada):
        bases_datos.registrar(conexion, "XETEST", r"C:\oracle", Ambiente.PRUEBAS)
    bases_datos.desactivar(conexion, "XETEST")
    nueva = bases_datos.obtener(conexion, "XETEST")
    assert nueva is not None
    assert nueva.activa is False


def test_bases_datos_guardar_perfil(conexion: oracledb.Connection) -> None:
    registrada = bases_datos.registrar(conexion, "PERFILTEST", r"C:\oracle", Ambiente.PRUEBAS)
    perfil = PerfilBD(
        nombre="XE",
        nombre_instancia="XE",
        dbid=1,
        host="localhost",
        version="21.3.0.0.0",
        edicion="XE",
        es_cdb=False,
        log_mode="ARCHIVELOG",  # type: ignore[arg-type]
        open_mode="READ WRITE",
        estado_instancia="OPEN",
        oracle_home=None,
        diagnostic_dest=None,
        capturado_en=datetime.now(),
        contenedores=[],
        tablespaces=[],
        datafiles=[],
        tempfiles=[],
        controlfiles=[],
        redo_grupos=[],
        archivos_parametros=[],
        destinos_archivado=[],
        destino_archivado_configurado=False,
        area_recuperacion=None,
        archivelogs_sin_respaldo=0,
    )
    bases_datos.guardar_perfil(conexion, registrada.id, perfil)


@pytest.fixture(scope="module")
def estrategia_bd_id(conexion: oracledb.Connection) -> int:
    return bases_datos.registrar(conexion, "BD_ESTRATEGIA", r"C:\oracle", Ambiente.PRUEBAS).id


def test_estrategias_crear_listar_y_obtener(conexion: oracledb.Connection, estrategia_bd_id: int) -> None:
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, "ESTX1"))
    obtenida = estrategias.obtener(conexion, estrategia_bd_id, "ESTX1")
    assert obtenida is not None
    assert len(obtenida.alcance) == 1
    assert obtenida.alcance[0].identificador == ""
    assert len(obtenida.tareas) == 1
    assert obtenida.tareas[0].programacion.horas == [time(2, 0)]
    assert any(e.codigo == "ESTX1" for e in estrategias.listar(conexion, estrategia_bd_id))


def test_estrategias_actualizar_reemplaza_el_alcance_y_sube_version(
    conexion: oracledb.Connection, estrategia_bd_id: int
) -> None:
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, "ESTX2"))
    actual = estrategias.obtener(conexion, estrategia_bd_id, "ESTX2")
    assert actual is not None
    nuevo_alcance = [
        *actual.alcance,
        ObjetoAlcance(tipo=TipoObjeto.ARCHIVELOG, identificador="", prioridad=Prioridad.ALTA),
    ]
    actualizada = actual.model_copy(update={"alcance": nuevo_alcance, "version": actual.version + 1})
    resultado = estrategias.actualizar(conexion, actualizada)
    assert resultado.version == 2
    releida = estrategias.obtener(conexion, estrategia_bd_id, "ESTX2")
    assert releida is not None
    assert len(releida.alcance) == 2


def test_estrategias_activar_y_desactivar(conexion: oracledb.Connection, estrategia_bd_id: int) -> None:
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, "ESTX3"))
    estrategias.activar(conexion, estrategia_bd_id, "ESTX3")
    activa = estrategias.obtener(conexion, estrategia_bd_id, "ESTX3")
    assert activa is not None and activa.estado is EstadoEstrategia.ACTIVA
    estrategias.desactivar(conexion, estrategia_bd_id, "ESTX3")
    inactiva = estrategias.obtener(conexion, estrategia_bd_id, "ESTX3")
    assert inactiva is not None and inactiva.estado is EstadoEstrategia.INACTIVA


def test_obtener_tarea_id(conexion: oracledb.Connection, estrategia_bd_id: int) -> None:
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, "ESTX4"))
    tarea_id = estrategias.obtener_tarea_id(conexion, estrategia_bd_id, "ESTX4", "T1")
    assert tarea_id is not None
    assert estrategias.obtener_tarea_id(conexion, estrategia_bd_id, "ESTX4", "NOPE") is None


@pytest.fixture
def tarea_id(conexion: oracledb.Connection, estrategia_bd_id: int) -> int:
    codigo = f"ESX{datetime.now().strftime('%H%M%S%f')[:11]}"
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, codigo))
    identificador = estrategias.obtener_tarea_id(conexion, estrategia_bd_id, codigo, "T1")
    assert identificador is not None
    return identificador


def test_scripts_ciclo_completo(conexion: oracledb.Connection, tarea_id: int) -> None:
    borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
    assert borrador.version == 1
    assert borrador.estado is EstadoScript.BORRADOR
    assert scripts.obtener_vigente(conexion, tarea_id) is None

    aprobado = scripts.aprobar(conexion, borrador.id, "pytest")
    assert aprobado.estado is EstadoScript.APROBADO
    vigente = scripts.obtener_vigente(conexion, tarea_id)
    assert vigente is not None and vigente.id == borrador.id

    scripts.marcar_obsoleto(conexion, borrador.id)
    assert scripts.obtener_vigente(conexion, tarea_id) is None


def test_scripts_rechazar_guarda_el_motivo(conexion: oracledb.Connection, tarea_id: int) -> None:
    borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
    rechazado = scripts.rechazar(conexion, borrador.id, "No acepta la caída del servicio.")
    assert rechazado.estado is EstadoScript.RECHAZADO


def test_ejecuciones_reclamar_evita_duplicados(conexion: oracledb.Connection, tarea_id: int) -> None:
    borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
    scripts.aprobar(conexion, borrador.id, "pytest")
    momento = datetime(2026, 1, 1, 13, 0)
    primera = ejecuciones.reclamar(conexion, tarea_id, momento)
    assert primera is not None
    assert ejecuciones.reclamar(conexion, tarea_id, momento) is None


def test_ejecuciones_marcar_en_curso_y_registrar_resultado(conexion: oracledb.Connection, tarea_id: int) -> None:
    borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
    scripts.aprobar(conexion, borrador.id, "pytest")
    ejecucion = ejecuciones.reclamar(conexion, tarea_id, datetime(2026, 1, 2, 13, 0))
    assert ejecucion is not None
    ejecuciones.marcar_en_curso(conexion, ejecucion.id, "agente-pytest")
    ejecuciones.registrar_resultado(
        conexion, ejecucion.id, {"estado": EstadoEjecucion.EXITOSA, "estado_prueba": "OK"}
    )
    ultimas = ejecuciones.ultimas(conexion, tarea_id, 10)
    coincidencias = [e for e in ultimas if e.id == ejecucion.id]
    assert coincidencias and coincidencias[0].estado is EstadoEjecucion.EXITOSA

    historial = ejecuciones.historial(conexion, ejecuciones.FiltrosHistorial(estado=EstadoEjecucion.EXITOSA))
    assert any(e.id == ejecucion.id for e in historial)


def test_alertas_ciclo_completo(conexion: oracledb.Connection) -> None:
    alerta = alertas.upsert_abierta(conexion, "COD_PRUEBA", "clave-prueba", "mensaje inicial")
    assert alerta.estado is EstadoAlerta.ABIERTA

    repetida = alertas.upsert_abierta(conexion, "COD_PRUEBA", "clave-prueba", "mensaje actualizado")
    assert repetida.id == alerta.id

    assert len(alertas.abiertas(conexion, ["COD_PRUEBA"])) == 1
    alertas.reconocer(conexion, alerta.id)
    alertas.resolver(conexion, alerta.id)
    assert alertas.abiertas(conexion, ["COD_PRUEBA"]) == []
