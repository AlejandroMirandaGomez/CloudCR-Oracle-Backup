from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from cloudcr_backup.cli import asistente_estrategia
from cloudcr_backup.domain.enums import ContenidoTablespace, LogMode
from cloudcr_backup.domain.enums import TipoObjeto as TO
from cloudcr_backup.domain.perfil_bd import ContenedorInfo, PerfilBD, TablespaceInfo
from cloudcr_backup.strategy.plantillas_esquema import todos_los_esquemas
from cloudcr_backup.strategy.yaml_io import cargar_estrategia_yaml


def test_siguiente_codigo_sugerido_sin_estrategias_previas() -> None:
    assert asistente_estrategia.siguiente_codigo_sugerido([]) == "EST001"


def test_siguiente_codigo_sugerido_continua_la_numeracion() -> None:
    assert asistente_estrategia.siguiente_codigo_sugerido(["EST001", "EST003"]) == "EST004"


def test_siguiente_codigo_sugerido_ignora_codigos_con_otro_formato() -> None:
    assert asistente_estrategia.siguiente_codigo_sugerido(["EST001", "OTRO"]) == "EST002"


def _perfil() -> PerfilBD:
    return PerfilBD(
        nombre="XE",
        nombre_instancia="XE",
        dbid=1,
        host="localhost",
        version="21.3.0.0.0",
        edicion="XE",
        es_cdb=True,
        log_mode=LogMode.ARCHIVELOG,
        open_mode="READ WRITE",
        estado_instancia="OPEN",
        oracle_home=None,
        diagnostic_dest=None,
        capturado_en=datetime.now(),
        contenedores=[
            ContenedorInfo(con_id=1, nombre="CDB$ROOT", open_mode="READ WRITE"),
            ContenedorInfo(con_id=3, nombre="XEPDB1", open_mode="READ WRITE"),
        ],
        tablespaces=[
            TablespaceInfo(
                con_id=3, nombre="VENTAS", contenido=ContenidoTablespace.PERMANENTE, estado="ONLINE", bigfile=False
            ),
            TablespaceInfo(
                con_id=3, nombre="TEMP", contenido=ContenidoTablespace.TEMPORAL, estado=None, bigfile=False
            ),
        ],
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


def test_construir_opciones_alcance_incluye_tablespace_controlfile_spfile_y_archivelog() -> None:
    opciones = asistente_estrategia.construir_opciones_alcance(_perfil())
    etiquetas = [etiqueta for etiqueta, _, _ in opciones]
    assert "Toda la base de datos" in etiquetas
    assert "Tablespace XEPDB1:VENTAS" in etiquetas
    assert "Control file" in etiquetas
    assert "SPFILE" in etiquetas
    assert "Archived logs" in etiquetas
    assert not any("TEMP" in etiqueta for etiqueta in etiquetas)


def test_construir_opciones_alcance_sin_archivelog_si_noarchivelog() -> None:
    perfil = _perfil().model_copy(update={"log_mode": LogMode.NOARCHIVELOG})
    opciones = asistente_estrategia.construir_opciones_alcance(perfil)
    assert not any(tipo is TO.ARCHIVELOG for _, tipo, _ in opciones)


def test_ejecutar_el_asistente_completo_con_el_esquema_completo_semanal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(asistente_estrategia, "descubrir_instancias", lambda: [])
    monkeypatch.setattr(asistente_estrategia, "resolver_instancia", lambda instancias, sid, home: object())
    monkeypatch.setattr(
        asistente_estrategia, "explorar_local", lambda instancia: SimpleNamespace(perfil=_perfil())
    )

    etiqueta_esquema = f"{todos_los_esquemas()[0].nombre} — {todos_los_esquemas()[0].descripcion}"
    archivo_destino = tmp_path / "est_asistente.yaml"

    textos = iter(
        [
            "XE",  # nombre de la base de datos
            "EST999",  # código
            "Prueba del asistente",  # nombre
            "",  # descripción (vacía -> None)
            "luis",  # responsable
            r"C:\backups\XE",  # destino
            "02:00",  # hora del nivel 0
            "15:00",  # hora del nivel 1
            str(archivo_destino),  # archivo donde guardar
        ]
    )
    selecciones = iter(
        [
            "BAJA",  # prioridad de la estrategia
            "BAJA",  # prioridad del objeto "Toda la base de datos"
            "Sin definir (no recomendado)",  # retención
            etiqueta_esquema,  # esquema
            "DOM",  # día del nivel 0
        ]
    )
    confirmaciones = iter(
        [
            True,  # usar esquema predefinido
            False,  # no guardar en el repositorio
        ]
    )

    monkeypatch.setattr(asistente_estrategia, "_preguntar_texto", lambda *a, **k: next(textos))
    monkeypatch.setattr(asistente_estrategia, "_preguntar_seleccion", lambda *a, **k: next(selecciones))
    monkeypatch.setattr(asistente_estrategia, "_preguntar_confirmacion", lambda *a, **k: next(confirmaciones))
    monkeypatch.setattr(asistente_estrategia, "_preguntar_multiple", lambda *a, **k: [0])

    asistente_estrategia.ejecutar()

    assert archivo_destino.exists()
    estrategia = cargar_estrategia_yaml(archivo_destino)
    assert estrategia.codigo == "EST999"
    assert estrategia.descripcion is None
    assert len(estrategia.alcance) == 1
    assert estrategia.alcance[0].tipo is TO.BASE_DATOS
    assert len(estrategia.tareas) == 1
    assert estrategia.retencion.ventana_dias is None
    assert estrategia.retencion.redundancia is None
