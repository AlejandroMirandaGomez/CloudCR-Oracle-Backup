from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cloudcr_backup.domain.ejecucion import Evidencia, PiezaEvidencia, PruebaEvidencia
from cloudcr_backup.domain.enums import EstadoEjecucion, EstadoPrueba, ModoRespaldo, TipoRespaldo
from cloudcr_backup.domain.errores import RepositorioNoDisponible
from cloudcr_backup.execution import buzon, correlator, evidencia
from cloudcr_backup.execution.persistencia import persistir
from cloudcr_backup.repository import piezas as repositorio_piezas
from cloudcr_backup.repository.piezas import PiezaNueva
from tests.unit.oracle_falso import ConexionFalsa

FIN = datetime(2026, 10, 4, 19, 30, tzinfo=UTC)


def ejemplo(ejecucion_id: int = 7, **cambios: Any) -> Evidencia:
    base: dict[str, Any] = {
        "ejecucion_id": ejecucion_id,
        "bd": "XE",
        "bd_id": 1,
        "estrategia": "EST001",
        "estrategia_nombre": "Producción diaria",
        "tarea": "T1",
        "tarea_id": 3,
        "tipo_respaldo": TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO,
        "modo_respaldo": ModoRespaldo.EN_LINEA,
        "estado": EstadoEjecucion.EXITOSA,
        "estado_prueba": EstadoPrueba.OK,
        "fin": FIN,
        "duracion_segundos": 42,
        "mensaje_rman": "RMAN terminó sin errores.",
        "errores": [],
        "advertencias": ["RMAN-08137: WARNING"],
        "piezas": [
            PiezaEvidencia(ruta="C:\\backups\\XE\\a.bkp", tamano_bytes=100, existe=True, tag="EST001_T1_X"),
            PiezaEvidencia(ruta="C:\\backups\\XE\\b.bkp", tamano_bytes=50, existe=True),
        ],
        "pruebas": [PruebaEvidencia(tipo="CROSSCHECK", resultado=EstadoPrueba.OK)],
    }
    base.update(cambios)
    return Evidencia(**base)


def test_resultado_para_el_repositorio_usa_utc_ingenuo_y_totales() -> None:
    resultado = ejemplo().resultado_repositorio()
    assert resultado["fin"] == datetime(2026, 10, 4, 19, 30)
    assert resultado["archivos_generados"] == 2
    assert resultado["tamano_bytes"] == 150
    assert resultado["errores"] is None
    assert resultado["advertencias"] == "RMAN-08137: WARNING"


def test_evidencia_se_escribe_y_se_lee_igual(tmp_path: Path) -> None:
    carpeta = evidencia.carpeta_ejecucion(tmp_path / "ejecuciones", 7)
    ruta = evidencia.escribir(carpeta, ejemplo())
    assert ruta == tmp_path / "ejecuciones" / "7" / "evidencia.json"
    assert evidencia.leer(ruta) == ejemplo()
    assert not list(carpeta.glob("*.tmp"))


def test_buzon_deposita_una_sola_copia_por_ejecucion(tmp_path: Path) -> None:
    buzon.depositar(tmp_path, ejemplo(), datetime(2026, 10, 4, 1, tzinfo=UTC))
    buzon.depositar(tmp_path, ejemplo(estado=EstadoEjecucion.FALLIDA), datetime(2026, 10, 4, 2, tzinfo=UTC))
    archivos = buzon.pendientes(tmp_path)
    assert len(archivos) == 1
    assert archivos[0].name.endswith("_7.json")


def test_buzon_sincroniza_en_orden_y_borra_lo_sincronizado(tmp_path: Path) -> None:
    buzon.depositar(tmp_path, ejemplo(8), datetime(2026, 10, 4, 2, tzinfo=UTC))
    buzon.depositar(tmp_path, ejemplo(7), datetime(2026, 10, 4, 1, tzinfo=UTC))
    vistos: list[int] = []
    assert buzon.vaciar(tmp_path, lambda e: vistos.append(e.ejecucion_id)) == 2
    assert vistos == [7, 8]
    assert buzon.pendientes(tmp_path) == []


def test_buzon_se_detiene_si_el_repositorio_sigue_caido(tmp_path: Path) -> None:
    buzon.depositar(tmp_path, ejemplo(7))

    def caido(_: Evidencia) -> None:
        raise RepositorioNoDisponible("sin repositorio")

    assert buzon.vaciar(tmp_path, caido) == 0
    assert len(buzon.pendientes(tmp_path)) == 1


def test_buzon_aparta_archivos_danados(tmp_path: Path) -> None:
    (tmp_path / "20261004_9.json").write_text("{no es json", encoding="utf-8")
    assert buzon.vaciar(tmp_path, lambda e: None) == 0
    assert (tmp_path / "20261004_9.danado").exists()


def test_sincronizar_sin_pendientes_no_abre_el_repositorio(tmp_path: Path) -> None:
    from cloudcr_backup.config.ajustes import Ajustes

    assert buzon.sincronizar(Ajustes(work_dir=tmp_path)) == 0


def test_persistir_registra_resultado_piezas_y_verificaciones() -> None:
    conexion = ConexionFalsa()
    persistir(conexion, ejemplo())  # type: ignore[arg-type]
    sentencias = [sql for sql, _ in conexion.ejecutados]
    assert sentencias[0].startswith("UPDATE ejecucion SET")
    assert sum(s.startswith("INSERT INTO ejecucion_pieza") for s in sentencias) == 2
    assert any(s.startswith("DELETE FROM verificacion") for s in sentencias)
    assert any(s.startswith("INSERT INTO verificacion") for s in sentencias)


def test_reemplazar_piezas_es_idempotente() -> None:
    conexion = ConexionFalsa()
    pieza = PiezaNueva(nombre_archivo="x" * 500, tamano_bytes=1, tag="T" * 40, vence_en=None)
    repositorio_piezas.reemplazar(conexion, 7, [pieza])  # type: ignore[arg-type]
    (borrado, _), (_, insertado) = conexion.ejecutados
    assert borrado.startswith("DELETE FROM ejecucion_pieza")
    assert len(insertado["nombre_archivo"]) == 400
    assert len(insertado["tag"]) == 30
    assert conexion.commits == 1


def test_correlacionar_lee_trabajo_y_piezas() -> None:
    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        if "v$rman_backup_job_details" in sql:
            assert parametros == {"command_id": "CLOUDCR_7"}
            return [("COMPLETED", 10, 5, None, None, "DATAFILE INCR")]
        assert parametros == {"tag": "EST001_T1_X"}
        return [("C:\\a.bkp", 5, "EST001_T1_X", "A", 3, None), ("C:\\b.bkp", 6, "EST001_T1_X", "X", 4, None)]

    resultado = correlator.correlacionar(consulta, "EST001_T1_X", "CLOUDCR_7")
    assert resultado.consultado
    assert resultado.estado_job == "COMPLETED"
    assert resultado.conjuntos == [3, 4]
    assert [p.disponible for p in resultado.piezas] == [True, False]
    assert resultado.piezas[1].expirada


def test_correlacionar_tolera_errores_del_catalogo() -> None:
    def consulta(sql: str, parametros: dict[str, Any]) -> list[tuple[Any, ...]]:
        raise RuntimeError("ORA-01034")

    resultado = correlator.correlacionar(consulta, "T", "C")
    assert not resultado.consultado
    assert resultado.error is not None
    assert "ORA-01034" in resultado.error
