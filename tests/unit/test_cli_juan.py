from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from cloudcr_backup.cli.app import app
from cloudcr_backup.domain.ejecucion import PiezaEvidencia, ResultadoEjecucion
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, EstadoScript, LogMode, ModoRespaldo
from cloudcr_backup.domain.errores import OperacionNoPermitida
from cloudcr_backup.domain.recuperacion import ArchivoDanado, Diagnostico, Escenario, Procedimiento, PuntosRecuperacion
from cloudcr_backup.domain.retencion import InformeRetencion, RetencionEstrategia
from cloudcr_backup.domain.scripts import FilaExplicacion, SimulacionEjecucion, VistaScript
from cloudcr_backup.services import ejecucion, recuperacion, retencion, scripts

corredor = CliRunner()
AHORA = datetime(2026, 10, 4, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def entorno(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDCR_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("CLOUDCR_CONFIG", str(tmp_path / "no-existe.yaml"))
    monkeypatch.setenv("COLUMNS", "250")


def vista(**cambios: Any) -> VistaScript:
    base: dict[str, Any] = {
        "bd": "XE",
        "estrategia": "EST002",
        "tarea": "T1",
        "tarea_id": 3,
        "script_id": 9,
        "version": 1,
        "estado": EstadoScript.BORRADOR,
        "hash_sha256": "a" * 64,
        "contenido": "SHUTDOWN IMMEDIATE;\nSTARTUP MOUNT;\n",
        "modo": ModoRespaldo.CONSISTENTE,
        "archivo": "C:\\w\\T1_v1.rman",
        "archivo_intacto": True,
        "nueva": True,
        "explicacion": [FilaExplicacion(campo="Tipo de respaldo", clausula="BACKUP INCREMENTAL LEVEL 0")],
    }
    base.update(cambios)
    return VistaScript(**base)


def resultado(estado: EstadoEjecucion, prueba: EstadoPrueba) -> ResultadoEjecucion:
    return ResultadoEjecucion(
        ejecucion_id=41,
        estado=estado,
        estado_prueba=prueba,
        motivos=["RMAN terminó sin errores."],
        evidencia="C:\\w\\ejecuciones\\41\\evidencia.json",
        piezas=[PiezaEvidencia(ruta="C:\\backups\\XE\\a.bkp", tamano_bytes=2048, existe=True)],
    )


def test_script_generar_muestra_script_y_explicacion(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas: list[tuple[Any, ...]] = []

    def generar(a: Any, bd: Any, codigo: str, tarea: Any) -> list[VistaScript]:
        llamadas.append((bd, codigo, tarea))
        return [vista()]

    monkeypatch.setattr(scripts, "generar", generar)
    salida = corredor.invoke(app, ["script", "generar", "EST002", "--tarea", "T1", "--bd", "XE"])
    assert salida.exit_code == 0, salida.output
    assert llamadas == [("XE", "EST002", "T1")]
    assert "SHUTDOWN IMMEDIATE" in salida.output
    assert "CONSISTENTE: apaga la base" in salida.output
    assert "BACKUP INCREMENTAL LEVEL 0" in salida.output
    assert "cloudcr script aprobar EST002 T1" in salida.output


def test_script_aprobar_sin_aceptar_caida_falla_con_mensaje_claro(monkeypatch: pytest.MonkeyPatch) -> None:
    def aprobar(*argumentos: Any) -> VistaScript:
        assert argumentos[5] is False
        raise OperacionNoPermitida("El script hace un respaldo CONSISTENTE.", "Apruebe con --acepto-caida.")

    monkeypatch.setattr(scripts, "aprobar", aprobar)
    salida = corredor.invoke(app, ["script", "aprobar", "EST002", "T1"])
    assert salida.exit_code == 2
    assert "CONSISTENTE" in salida.output
    assert "--acepto-caida" in salida.output


def test_script_aprobar_con_caida_aceptada(monkeypatch: pytest.MonkeyPatch) -> None:
    def aprobar(a: Any, bd: Any, codigo: str, tarea: str, por: str, acepto: bool, version: Any) -> VistaScript:
        assert acepto is True
        assert por == "juan"
        return vista(estado=EstadoScript.APROBADO, aprobado_por=por, acepto_caida=True)

    monkeypatch.setattr(scripts, "aprobar", aprobar)
    salida = corredor.invoke(app, ["script", "aprobar", "EST002", "T1", "--acepto-caida", "--por", "juan"])
    assert salida.exit_code == 0, salida.output
    assert "Script aprobado" in salida.output
    assert "caída aceptada" in salida.output


def test_script_ver_json_y_listar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scripts, "ver", lambda *a: vista(archivo_intacto=False))
    monkeypatch.setattr(scripts, "listar", lambda *a: [vista(), vista(version=2, estado=EstadoScript.APROBADO)])
    assert '"version": 1' in corredor.invoke(app, ["script", "ver", "EST002", "T1", "--json"]).output
    assert "MODIFICADO" in corredor.invoke(app, ["script", "ver", "EST002", "T1"]).output
    listado = corredor.invoke(app, ["script", "listar", "EST002"])
    assert "APROBADO" in listado.output
    assert "BORRADOR" in listado.output


def test_script_rechazar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        scripts, "rechazar", lambda *a: vista(estado=EstadoScript.RECHAZADO, motivo_rechazo="falta SPFILE")
    )
    salida = corredor.invoke(app, ["script", "rechazar", "EST002", "T1", "--motivo", "falta SPFILE"])
    assert "Rechazado: falta SPFILE" in salida.output


def test_ejecutar_sin_ahora_explica_como_usarlo() -> None:
    salida = corredor.invoke(app, ["ejecutar", "EST001", "T1"])
    assert salida.exit_code == 2
    assert "--ahora" in salida.output


def test_ejecutar_ahora_exitoso(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ejecucion, "ejecutar_ahora", lambda *a: resultado(EstadoEjecucion.EXITOSA, EstadoPrueba.OK))
    salida = corredor.invoke(app, ["ejecutar", "EST001", "T1", "--ahora"])
    assert salida.exit_code == 0, salida.output
    assert "EXITOSA" in salida.output
    assert "Pruebas: OK" in salida.output
    assert "evidencia.json" in salida.output


def test_ejecutar_bloqueada_sale_con_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ejecucion, "ejecutar_ahora", lambda *a: resultado(EstadoEjecucion.BLOQUEADA, EstadoPrueba.NO_APLICA)
    )
    salida = corredor.invoke(app, ["ejecutar", "EST001", "T1", "--ahora"])
    assert salida.exit_code == 1
    assert "BLOQUEADA" in salida.output


def test_ejecutar_simular(monkeypatch: pytest.MonkeyPatch) -> None:
    simulacion = SimulacionEjecucion(
        bd="XE",
        estrategia="EST001",
        tarea="T1",
        script_id=9,
        version=1,
        archivo="C:\\w\\T1_v1.rman",
        contenido="RUN {\n}\n",
        comando="rman target / cmdfile=EST001.XE.RMAN",
        tag="EST001_T1_X",
        command_id="CLOUDCR_0",
        aprobado=False,
        problemas=["SCRIPT_ALTERADO: el archivo fue modificado"],
    )
    monkeypatch.setattr(ejecucion, "simular", lambda *a: simulacion)
    salida = corredor.invoke(app, ["ejecutar", "EST001", "T1", "--simular"])
    assert salida.exit_code == 1
    assert "SCRIPT_ALTERADO" in salida.output
    assert "cmdfile=EST001.XE.RMAN" in salida.output


def test_verificar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ejecucion, "verificar", lambda *a: resultado(EstadoEjecucion.EXITOSA, EstadoPrueba.FALLIDA))
    salida = corredor.invoke(app, ["verificar", "41"])
    assert salida.exit_code == 1
    assert "Pruebas: FALLIDA" in salida.output


def test_retencion_informe(monkeypatch: pytest.MonkeyPatch) -> None:
    informe = InformeRetencion(
        bd="XE",
        generado_en=AHORA,
        estrategias=[
            RetencionEstrategia(
                estrategia="EST004",
                nombre="CDB",
                politica="RECOVERY WINDOW OF 30 DAYS",
                descripcion="Conservar 30 días",
                piezas_total=3,
                script="CROSSCHECK BACKUP;\nREPORT OBSOLETE RECOVERY WINDOW OF 30 DAYS;\n",
            )
        ],
        archivelogs_sin_respaldo=4,
    )
    monkeypatch.setattr(retencion, "informe", lambda a, bd, rman: informe)
    salida = corredor.invoke(app, ["retencion", "informe", "XE"])
    assert salida.exit_code == 0, salida.output
    assert "nada se borra" in salida.output
    assert "RECOVERY WINDOW OF 30 DAYS" in salida.output
    assert "Archived logs sin respaldar: 4" in salida.output


def test_retencion_purgar_sin_confirmar(monkeypatch: pytest.MonkeyPatch) -> None:
    def purgar(a: Any, bd: str, codigo: str, confirmado: bool) -> Any:
        assert confirmado is False
        raise OperacionNoPermitida("La purga borra respaldos obsoletos y no se puede deshacer.")

    monkeypatch.setattr(retencion, "purgar", purgar)
    salida = corredor.invoke(app, ["retencion", "purgar", "XE", "EST004"])
    assert salida.exit_code == 2
    assert "no se puede deshacer" in salida.output


def test_recuperacion_plan_datafile(monkeypatch: pytest.MonkeyPatch) -> None:
    procedimiento = Procedimiento(
        bd="XE",
        escenario=Escenario.DATAFILE,
        posible=True,
        motivo="ok",
        objetivo="12 (C:\\X\\USERS01.DBF)",
        pasos=["Identificar con V$RECOVER_FILE"],
        script="RESTORE DATAFILE 12;\n",
        archivo="C:\\w\\datafile.rman",
    )
    recibidos: list[Any] = []

    def plan(a: Any, bd: str, escenario: str, objetivo: Any, hasta: Any) -> Procedimiento:
        recibidos.append((bd, escenario, objetivo, hasta))
        return procedimiento

    monkeypatch.setattr(recuperacion, "plan", plan)
    salida = corredor.invoke(app, ["recuperacion", "plan", "XE", "datafile"])
    assert salida.exit_code == 0, salida.output
    assert recibidos == [("XE", "datafile", None, None)]
    assert "Objetivo: 12" in salida.output
    assert "RESTORE DATAFILE 12" in salida.output
    assert "no se ejecutó" in salida.output


def test_recuperacion_plan_imposible_y_fecha_invalida(monkeypatch: pytest.MonkeyPatch) -> None:
    imposible = Procedimiento(bd="XE", escenario=Escenario.PDB, posible=False, motivo="necesita ARCHIVELOG")
    monkeypatch.setattr(recuperacion, "plan", lambda *a: imposible)
    assert corredor.invoke(app, ["recuperacion", "plan", "XE", "pdb"]).exit_code == 1
    malo = corredor.invoke(app, ["recuperacion", "plan", "XE", "punto-en-tiempo", "--hasta", "ayer"])
    assert malo.exit_code == 2


def test_recuperacion_diagnostico_y_puntos(monkeypatch: pytest.MonkeyPatch) -> None:
    diagnostico = Diagnostico(
        bd="XE",
        generado_en=AHORA,
        log_mode=LogMode.ARCHIVELOG,
        open_mode="READ WRITE",
        archivos=[
            ArchivoDanado(
                file_id=12,
                ruta="C:\\X\\USERS01.DBF",
                tablespace="USERS",
                contenedor="XEPDB1",
                estado="OFFLINE",
                error="FILE NOT FOUND",
                origen="V$RECOVER_FILE",
            )
        ],
    )
    monkeypatch.setattr(recuperacion, "diagnostico", lambda a, bd: diagnostico)
    monkeypatch.setattr(recuperacion, "puntos", lambda a, bd: PuntosRecuperacion(bd="XE", avisos=["sin puntos"]))
    salida = corredor.invoke(app, ["recuperacion", "diagnostico", "XE"])
    assert "XEPDB1:USERS" in salida.output
    assert "FILE NOT FOUND" in salida.output
    assert "sin puntos" in corredor.invoke(app, ["recuperacion", "puntos", "XE"]).output
