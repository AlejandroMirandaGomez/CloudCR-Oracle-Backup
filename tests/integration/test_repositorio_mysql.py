from collections.abc import Iterator
from datetime import datetime, time

import pytest

from cloudcr_backup.domain.alertas import Condicion, SeveridadAlerta
from cloudcr_backup.domain.enums import (
    EstadoAlerta,
    EstadoEjecucion,
    EstadoEstrategia,
    EstadoPrueba,
    EstadoScript,
    ModoRespaldo,
    Prioridad,
    TipoFrecuencia,
    TipoObjeto,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Como, Destino, Estrategia, ObjetoAlcance, Programacion, Tarea
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.domain.recuperacion import Escenario as EscenarioRecuperacion
from cloudcr_backup.domain.recuperacion import ResultadoRecuperacion
from cloudcr_backup.repository import (
    alertas,
    bases_datos,
    ejecuciones,
    esquema,
    estrategias,
    parametros,
    piezas,
    recuperaciones,
    scripts,
)
from cloudcr_backup.repository.bases_datos import Ambiente
from cloudcr_backup.repository.conexion import Conexion
from cloudcr_backup.repository.ejecuciones import FiltrosHistorial
from cloudcr_backup.repository.piezas import PiezaNueva, VerificacionNueva
from tests.integration.repositorio_de_prueba import abrir_repositorio_de_prueba

pytestmark = pytest.mark.mysql


@pytest.fixture(scope="module")
def conexion() -> Iterator[Conexion]:
    conexion = abrir_repositorio_de_prueba()
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


def test_esquema_instalar_es_idempotente(conexion: Conexion) -> None:
    esquema.instalar(conexion)
    info = esquema.estado(conexion)
    assert info.instalado
    assert set(info.tablas) == set(esquema.TABLAS)


def test_parametros_asignar_obtener_y_listar(conexion: Conexion) -> None:
    parametros.asignar(conexion, "clave.prueba", "1")
    assert parametros.obtener(conexion, "clave.prueba") == "1"
    parametros.asignar(conexion, "clave.prueba", "2")
    assert parametros.obtener(conexion, "clave.prueba") == "2"
    assert parametros.listar(conexion)["clave.prueba"] == "2"
    assert parametros.obtener(conexion, "no.existe") is None


def test_bases_datos_registrar_listar_obtener_y_desactivar(conexion: Conexion) -> None:
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


def test_bases_datos_guardar_perfil(conexion: Conexion) -> None:
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
def estrategia_bd_id(conexion: Conexion) -> int:
    return bases_datos.registrar(conexion, "BD_ESTRATEGIA", r"C:\oracle", Ambiente.PRUEBAS).id


def test_estrategias_crear_listar_y_obtener(conexion: Conexion, estrategia_bd_id: int) -> None:
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, "ESTX1"))
    obtenida = estrategias.obtener(conexion, estrategia_bd_id, "ESTX1")
    assert obtenida is not None
    assert len(obtenida.alcance) == 1
    assert obtenida.alcance[0].identificador == ""
    assert len(obtenida.tareas) == 1
    assert obtenida.tareas[0].programacion.horas == [time(2, 0)]
    assert any(e.codigo == "ESTX1" for e in estrategias.listar(conexion, estrategia_bd_id))


def test_estrategias_actualizar_reemplaza_el_alcance_y_sube_version(
    conexion: Conexion, estrategia_bd_id: int
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


def test_estrategias_activar_y_desactivar(conexion: Conexion, estrategia_bd_id: int) -> None:
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, "ESTX3"))
    estrategias.activar(conexion, estrategia_bd_id, "ESTX3")
    activa = estrategias.obtener(conexion, estrategia_bd_id, "ESTX3")
    assert activa is not None and activa.estado is EstadoEstrategia.ACTIVA
    estrategias.desactivar(conexion, estrategia_bd_id, "ESTX3")
    inactiva = estrategias.obtener(conexion, estrategia_bd_id, "ESTX3")
    assert inactiva is not None and inactiva.estado is EstadoEstrategia.INACTIVA


def test_obtener_tarea_id(conexion: Conexion, estrategia_bd_id: int) -> None:
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, "ESTX4"))
    tarea_id = estrategias.obtener_tarea_id(conexion, estrategia_bd_id, "ESTX4", "T1")
    assert tarea_id is not None
    assert estrategias.obtener_tarea_id(conexion, estrategia_bd_id, "ESTX4", "NOPE") is None


@pytest.fixture
def tarea_id(conexion: Conexion, estrategia_bd_id: int) -> int:
    codigo = f"ESX{datetime.now().strftime('%H%M%S%f')[:11]}"
    estrategias.crear(conexion, _estrategia(estrategia_bd_id, codigo))
    identificador = estrategias.obtener_tarea_id(conexion, estrategia_bd_id, codigo, "T1")
    assert identificador is not None
    return identificador


def test_scripts_ciclo_completo(conexion: Conexion, tarea_id: int) -> None:
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


def test_scripts_rechazar_guarda_el_motivo(conexion: Conexion, tarea_id: int) -> None:
    borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
    rechazado = scripts.rechazar(conexion, borrador.id, "No acepta la caída del servicio.")
    assert rechazado.estado is EstadoScript.RECHAZADO


def test_ejecuciones_reclamar_evita_duplicados(conexion: Conexion, tarea_id: int) -> None:
    borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
    scripts.aprobar(conexion, borrador.id, "pytest")
    momento = datetime(2026, 1, 1, 13, 0)
    primera = ejecuciones.reclamar(conexion, tarea_id, momento)
    assert primera is not None
    assert ejecuciones.reclamar(conexion, tarea_id, momento) is None


def test_ejecuciones_marcar_en_curso_y_registrar_resultado(conexion: Conexion, tarea_id: int) -> None:
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


def test_alertas_ciclo_completo(conexion: Conexion) -> None:
    alerta = alertas.upsert_abierta(conexion, "COD_PRUEBA", "clave-prueba", "mensaje inicial")
    assert alerta.estado is EstadoAlerta.ABIERTA

    repetida = alertas.upsert_abierta(conexion, "COD_PRUEBA", "clave-prueba", "mensaje actualizado")
    assert repetida.id == alerta.id

    assert len(alertas.abiertas(conexion, ["COD_PRUEBA"])) == 1
    alertas.reconocer(conexion, alerta.id)
    alertas.resolver(conexion, alerta.id)
    assert alertas.abiertas(conexion, ["COD_PRUEBA"]) == []


def test_historial_detallado_y_consultas_de_monitoreo(
    conexion: Conexion, estrategia_bd_id: int, tarea_id: int
) -> None:
    borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
    scripts.aprobar(conexion, borrador.id, "pytest")
    ejecucion = ejecuciones.reclamar(conexion, tarea_id, datetime(2026, 3, 1, 13, 0))
    assert ejecucion is not None
    ejecuciones.marcar_en_curso(conexion, ejecucion.id, "agente-pytest")
    assert ejecucion.id in {e.id for e in ejecuciones.en_curso(conexion)}
    assert ejecuciones.contar_en_curso(conexion) >= 1
    assert [e.id for e in ejecuciones.en_curso_de_agente(conexion, "agente-pytest")] == [ejecucion.id]
    piezas.reemplazar(
        conexion,
        ejecucion.id,
        [
            PiezaNueva("C:\\b\\p1.bkp", 1024, "TAG1", datetime(2026, 1, 1)),
            PiezaNueva("C:\\b\\p2.bkp", None, None, None),
        ],
    )
    piezas.reemplazar_verificaciones(
        conexion, ejecucion.id, [VerificacionNueva("RESTORE_VALIDATE", EstadoPrueba.OK, "sin errores")]
    )
    ejecuciones.registrar_resultado(
        conexion,
        ejecucion.id,
        {
            "estado": EstadoEjecucion.EXITOSA,
            "estado_prueba": "OK",
            "tamano_bytes": 2048,
            "archivos_generados": 2,
            "duracion_segundos": 300,
            "fin": datetime(2026, 3, 1, 13, 5),
            "errores": "x" * 20000,
        },
    )
    filtros = FiltrosHistorial(bd_id=estrategia_bd_id)
    detalladas = ejecuciones.historial_detallado(conexion, filtros, 50, 0)
    mia = next(e for e in detalladas if e.id == ejecucion.id)
    assert mia.tamano_bytes == 2048 and mia.zona_horaria == "America/Costa_Rica"
    assert ejecuciones.contar_historial(conexion, filtros) == len(detalladas)
    primera_pagina = ejecuciones.historial_detallado(conexion, filtros, 1, 0)
    segunda_pagina = ejecuciones.historial_detallado(conexion, filtros, 1, 1)
    assert len(primera_pagina) == 1
    assert {e.id for e in primera_pagina}.isdisjoint({e.id for e in segunda_pagina})
    assert ejecucion.id in {e.id for lista in ejecuciones.ultimas_por_tarea(conexion, 5).values() for e in lista}
    assert ejecuciones.tamano_ultimo_exito_por_tarea(conexion)[tarea_id] == 2048
    assert ejecuciones.ultima_programada_por_tarea(conexion)[tarea_id] == datetime(2026, 3, 1, 13, 0)
    assert ejecuciones.ultimo_exito_por_estrategia(conexion)
    detalle = ejecuciones.detalle(conexion, ejecucion.id)
    assert detalle is not None and detalle.script_hash == borrador.hash_sha256
    assert detalle.errores is not None and len(detalle.errores) == 20000
    registradas = ejecuciones.piezas(conexion, ejecucion.id)
    assert [p.nombre_archivo for p in registradas] == ["C:\\b\\p1.bkp", "C:\\b\\p2.bkp"]
    assert ejecuciones.verificaciones(conexion, ejecucion.id)[0].resultado is EstadoPrueba.OK
    assert ejecuciones.piezas_vencidas_por_estrategia(conexion, datetime(2026, 6, 1))
    de_base = piezas.de_base(conexion, estrategia_bd_id)
    assert [p.nombre_archivo for p in de_base] == ["C:\\b\\p1.bkp", "C:\\b\\p2.bkp"]
    assert piezas.marcar_obsoletas(conexion, [p.id for p in de_base]) == 2
    assert piezas.marcar_obsoletas(conexion, [p.id for p in de_base]) == 2
    assert not ejecuciones.piezas_vencidas_por_estrategia(conexion, datetime(2026, 6, 1))


def test_ejecuciones_no_ejecutada_e_interrumpida(conexion: Conexion, tarea_id: int) -> None:
    borrador = scripts.guardar_borrador(conexion, tarea_id, "RUN { BACKUP DATABASE; }")
    scripts.aprobar(conexion, borrador.id, "pytest")
    omitida = ejecuciones.registrar_no_ejecutada(conexion, tarea_id, datetime(2026, 4, 1, 13, 0), "agente detenido")
    assert omitida is not None and omitida.estado is EstadoEjecucion.NO_EJECUTADA
    assert ejecuciones.registrar_no_ejecutada(conexion, tarea_id, datetime(2026, 4, 1, 13, 0), "otra vez") is None
    pendiente = ejecuciones.reclamar(conexion, tarea_id, datetime(2026, 4, 2, 13, 0))
    assert pendiente is not None
    assert pendiente.id in {e.id for e in ejecuciones.programadas_sin_iniciar(conexion, datetime(2026, 5, 1))}
    assert ejecuciones.marcar_no_ejecutada(conexion, pendiente.id, "venció la gracia")
    assert not ejecuciones.marcar_no_ejecutada(conexion, pendiente.id, "venció la gracia")
    corriendo = ejecuciones.reclamar(conexion, tarea_id, datetime(2026, 4, 3, 13, 0))
    assert corriendo is not None
    ejecuciones.marcar_en_curso(conexion, corriendo.id, "agente-pytest")
    assert ejecuciones.marcar_interrumpida(conexion, corriendo.id, "se cortó la luz")
    assert not ejecuciones.marcar_interrumpida(conexion, corriendo.id, "se cortó la luz")


def test_alertas_con_condicion_listado_y_cambios_de_estado(
    conexion: Conexion, estrategia_bd_id: int
) -> None:
    condicion = Condicion(
        codigo_regla="EJECUCION_FALLIDA",
        sujeto="XETEST/EST/T1",
        severidad=SeveridadAlerta.ALERTA,
        mensaje="Falló el respaldo",
        bd_id=estrategia_bd_id,
        estrategia_id=None,
        tarea_id=None,
        ejecucion_id=None,
    )
    alerta, es_nueva = alertas.abrir(conexion, condicion)
    assert es_nueva and alerta.bd_nombre == "BD_ESTRATEGIA"
    repetida, es_nueva = alertas.abrir(conexion, condicion.model_copy(update={"mensaje": "Sigue fallando"}))
    assert not es_nueva and repetida.id == alerta.id and repetida.mensaje == "Sigue fallando"
    assert alerta.id in {a.id for a in alertas.vigentes(conexion)}
    assert alerta.id in {a.id for a in alertas.listar(conexion, [EstadoAlerta.ABIERTA], "ALERTA", 10)}
    assert alertas.reconocer_abierta(conexion, alerta.id)
    assert not alertas.reconocer_abierta(conexion, alerta.id)
    assert alertas.resolver_vigente(conexion, alerta.id)
    assert not alertas.resolver_vigente(conexion, alerta.id)
    final = alertas.obtener(conexion, alerta.id)
    assert final is not None and final.estado is EstadoAlerta.RESUELTA and final.resuelta_en is not None


def test_recuperaciones_ciclo_completo(conexion: Conexion, estrategia_bd_id: int) -> None:
    recuperaciones.asegurar_tabla(conexion)
    registro = recuperaciones.registrar(
        conexion,
        estrategia_bd_id,
        EscenarioRecuperacion.SPFILE,
        "ñ" * 300,
        "C:\\w\\spfile.rman",
        "STARTUP NOMOUNT;\nRESTORE SPFILE FROM AUTOBACKUP;\n",
        "a" * 64,
        datetime(2026, 10, 11, 12, 0),
    )
    assert registro.estado is EstadoScript.BORRADOR
    reutilizable = recuperaciones.borrador_sin_usar(conexion, estrategia_bd_id, EscenarioRecuperacion.SPFILE, "a" * 64)
    assert reutilizable is not None and reutilizable.id == registro.id
    assert recuperaciones.aprobar(conexion, registro.id, "pytest")
    assert not recuperaciones.aprobar(conexion, registro.id, "pytest")
    assert recuperaciones.marcar_en_curso(conexion, registro.id, "C:\\w\\spfile.log")
    assert not recuperaciones.marcar_en_curso(conexion, registro.id, "C:\\w\\spfile.log")
    recuperaciones.registrar_resultado(conexion, registro.id, ResultadoRecuperacion.EJECUTADO_OK, "x" * 5000)
    final = recuperaciones.obtener(conexion, registro.id)
    assert final is not None and final.resultado is ResultadoRecuperacion.EJECUTADO_OK
    assert final.contenido.startswith("STARTUP NOMOUNT")
    assert recuperaciones.borrador_sin_usar(conexion, estrategia_bd_id, EscenarioRecuperacion.SPFILE, "a" * 64) is None


def test_el_esquema_conserva_mayusculas_y_acentos(conexion: Conexion) -> None:
    primera = bases_datos.registrar(conexion, "MayusMinus", r"C:\oracle", Ambiente.PRUEBAS)
    segunda = bases_datos.registrar(conexion, "MAYUSMINUS", r"C:\oracle", Ambiente.PRUEBAS)
    assert primera.id != segunda.id
    parametros.asignar(conexion, "texto.acentuado", "Producción diaria 100% ñandú")
    assert parametros.obtener(conexion, "texto.acentuado") == "Producción diaria 100% ñandú"
