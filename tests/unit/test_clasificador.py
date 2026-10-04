from pathlib import Path

from cloudcr_backup.domain.enums import EstadoEjecucion
from cloudcr_backup.execution.clasificador import EntradaClasificacion, PiezaVerificada, clasificar
from cloudcr_backup.execution.parser import LogAnalizado, PiezaLog, analizar

LOGS = Path(__file__).resolve().parents[1] / "fixtures" / "rman_logs"
PIEZA = "C:\\backups\\XE\\XE_EST001_T1_20261004_01_1_1.BKP"


def log_limpio(advertencias: bool = False) -> LogAnalizado:
    texto = f"connected to target database: XE\npiece handle={PIEZA} tag=EST001_T1_2610041300 comment=NONE\n"
    if advertencias:
        texto += "RMAN-08137: WARNING: archived log not deleted\n"
    return analizar(texto + "Recovery Manager complete.\n")


def entrada(**cambios: object) -> EntradaClasificacion:
    base: dict[str, object] = {
        "codigo_salida": 0,
        "agotado": False,
        "log": log_limpio(),
        "estado_job": "COMPLETED",
        "catalogo_consultado": True,
        "piezas": [PiezaVerificada(ruta=PIEZA, existe=True, tamano_bytes=1024)],
    }
    base.update(cambios)
    return EntradaClasificacion(**base)  # type: ignore[arg-type]


def test_fixture_rman06817_es_fallida_aunque_diga_recovery_manager_complete() -> None:
    log = analizar((LOGS / "fallo_rman06817_noarchivelog.log").read_text(encoding="utf-8"))
    resultado = clasificar(entrada(codigo_salida=0, log=log, estado_job="FAILED", piezas=[], catalogo_consultado=True))
    assert resultado.estado is EstadoEjecucion.FALLIDA
    assert any("RMAN-06817" in m for m in resultado.motivos)
    assert any("no bastan" in m for m in resultado.motivos)


def test_todo_correcto_es_exitosa() -> None:
    resultado = clasificar(entrada())
    assert resultado.estado is EstadoEjecucion.EXITOSA
    assert resultado.correcta


def test_codigo_de_salida_distinto_de_cero_es_fallida() -> None:
    assert clasificar(entrada(codigo_salida=1)).estado is EstadoEjecucion.FALLIDA


def test_tiempo_agotado_es_fallida() -> None:
    resultado = clasificar(entrada(codigo_salida=None, agotado=True, log=LogAnalizado()))
    assert resultado.estado is EstadoEjecucion.FALLIDA
    assert any("tiempo" in m for m in resultado.motivos)


def test_pieza_inexistente_o_vacia_es_fallida() -> None:
    resultado = clasificar(entrada(piezas=[PiezaVerificada(ruta=PIEZA, existe=True, tamano_bytes=0)]))
    assert resultado.estado is EstadoEjecucion.FALLIDA
    assert any(PIEZA in m for m in resultado.motivos)


def test_sin_piezas_es_fallida() -> None:
    log = analizar("connected to target database: XE\nRecovery Manager complete.\n")
    assert clasificar(entrada(log=log, piezas=[])).estado is EstadoEjecucion.FALLIDA


def test_log_truncado_es_fallido() -> None:
    log = LogAnalizado(piezas=[PiezaLog(handle=PIEZA, tag=None)], conectado=True)
    assert clasificar(entrada(log=log)).estado is EstadoEjecucion.FALLIDA


def test_job_fallido_en_el_catalogo_es_fallida() -> None:
    assert clasificar(entrada(estado_job="COMPLETED WITH ERRORS")).estado is EstadoEjecucion.FALLIDA


def test_advertencias_del_log_dan_con_advertencias() -> None:
    resultado = clasificar(entrada(log=log_limpio(advertencias=True)))
    assert resultado.estado is EstadoEjecucion.CON_ADVERTENCIAS


def test_job_con_advertencias_da_con_advertencias() -> None:
    assert clasificar(entrada(estado_job="COMPLETED WITH WARNINGS")).estado is EstadoEjecucion.CON_ADVERTENCIAS


def test_sin_confirmacion_del_catalogo_da_con_advertencias() -> None:
    resultado = clasificar(entrada(estado_job=None, catalogo_consultado=False))
    assert resultado.estado is EstadoEjecucion.CON_ADVERTENCIAS


def test_base_no_reabierta_da_con_advertencias() -> None:
    resultado = clasificar(entrada(reapertura_correcta=False))
    assert resultado.estado is EstadoEjecucion.CON_ADVERTENCIAS
    assert any("no quedó abierta" in m for m in resultado.motivos)


def test_error_al_lanzar_rman_es_fallida() -> None:
    resultado = clasificar(
        entrada(codigo_salida=None, log=LogAnalizado(), piezas=[], error_lanzamiento="No se pudo iniciar RMAN")
    )
    assert resultado.estado is EstadoEjecucion.FALLIDA
    assert resultado.motivos[0] == "No se pudo iniciar RMAN"


def test_log_real_del_respaldo_consistente_es_exitoso() -> None:
    log = analizar((LOGS / "exito_est002_consistente.log").read_text(encoding="utf-8"))
    piezas = [PiezaVerificada(ruta=p.handle, existe=True, tamano_bytes=1) for p in log.piezas]
    resultado = clasificar(entrada(log=log, piezas=piezas, estado_job="COMPLETED", reapertura_correcta=True))
    assert resultado.estado is EstadoEjecucion.EXITOSA
