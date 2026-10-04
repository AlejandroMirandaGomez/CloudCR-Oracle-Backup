from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import LogMode
from cloudcr_backup.domain.errores import FiltroInvalido
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.domain.recuperacion import Diagnostico, Escenario, Procedimiento, PuntosRecuperacion
from cloudcr_backup.execution.correlator import Consulta
from cloudcr_backup.execution.destino import BaseDestino, consulta_destino
from cloudcr_backup.recovery import diagnostico as diagnostico_rman
from cloudcr_backup.recovery import puntos as puntos_recuperacion
from cloudcr_backup.recovery.procedimientos import SolicitudProcedimiento, generar
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import ejecuciones as repositorio_ejecuciones
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import piezas as repositorio_piezas
from cloudcr_backup.repository.bases_datos import Ambiente, BaseDatosRegistrada
from cloudcr_backup.repository.ejecuciones import FiltrosHistorial
from cloudcr_backup.rman import nombres
from cloudcr_backup.rman.render import bytes_ascii
from cloudcr_backup.scheduling.reloj import RelojSistema
from cloudcr_backup.services import resolucion
from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle
from cloudcr_backup.services.sesion import conexion_repositorio

SQL_ESTADO = "SELECT log_mode, open_mode, dbid FROM v$database"
LIMITE_EJECUCIONES = 500
AVISO_AMBIENTE = (
    "La base no está registrada en ambiente PRUEBAS: el procedimiento es informativo y no debe aplicarse sin la "
    "aprobación del DBA."
)

AbrirConsulta = Callable[[BaseDestino], AbstractContextManager[Consulta]]


def escenario_de(texto: str) -> Escenario:
    try:
        return Escenario(texto.strip().lower())
    except ValueError as error:
        opciones = ", ".join(e.value for e in Escenario)
        raise FiltroInvalido(f"El escenario {texto!r} no existe.", f"Use uno de: {opciones}.") from error


def _base(base: BaseDatosRegistrada) -> BaseDestino:
    return BaseDestino(oracle_home=Path(base.oracle_home), sid=base.nombre)


def _diagnosticar(base: BaseDatosRegistrada, abrir: AbrirConsulta) -> Diagnostico:
    momento = RelojSistema().ahora()
    try:
        with abrir(_base(base)) as consulta:
            filas = consulta(SQL_ESTADO, {})
            archivos = diagnostico_rman.archivos_danados(consulta)
    except Exception as error:
        return Diagnostico(
            bd=base.nombre,
            generado_en=momento,
            avisos=[f"No se pudo consultar V$RECOVER_FILE en {base.nombre}: {type(error).__name__}: {error}"],
        )
    log_mode, open_mode, _ = filas[0] if filas else (None, None, None)
    avisos = [] if archivos else ["V$RECOVER_FILE no informa archivos que necesiten recuperación."]
    return Diagnostico(
        bd=base.nombre,
        generado_en=momento,
        log_mode=LogMode(str(log_mode)) if log_mode else None,
        open_mode=None if open_mode is None else str(open_mode),
        archivos=archivos,
        avisos=avisos,
    )


def diagnostico(ajustes: Ajustes, bd: str, abrir: AbrirConsulta = consulta_destino) -> Diagnostico:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
    return _diagnosticar(base, abrir)


def puntos(ajustes: Ajustes, bd: str) -> PuntosRecuperacion:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        ejecuciones = repositorio_ejecuciones.historial_detallado(
            conexion, FiltrosHistorial(bd_id=base.id), LIMITE_EJECUCIONES
        )
        piezas = repositorio_piezas.de_base(conexion, base.id)
        estrategias = {e.codigo: e for e in repositorio_estrategias.listar(conexion, base.id)}
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
    return puntos_recuperacion.construir(
        base.nombre, perfil.log_mode if perfil else None, ejecuciones, piezas, estrategias
    )


def _contenedores(perfil: PerfilBD | None) -> dict[int, str]:
    if perfil is None:
        return {}
    nombres_contenedor = {c.con_id: c.nombre for c in perfil.contenedores}
    return {d.file_id: nombres_contenedor.get(d.con_id, "") for d in perfil.datafiles}


def _destino_autobackup(ajustes: Ajustes, estrategias_destinos: list[str]) -> str | None:
    if estrategias_destinos:
        return estrategias_destinos[0]
    return str(ajustes.destino_defecto) if ajustes.destino_defecto else None


def plan(
    ajustes: Ajustes,
    bd: str,
    escenario: str,
    objetivo: str | None = None,
    hasta: datetime | None = None,
    guardar: bool = True,
    abrir: AbrirConsulta = consulta_destino,
) -> Procedimiento:
    elegido = escenario_de(escenario)
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
        destinos = [t.destino.ruta for e in repositorio_estrategias.listar(conexion, base.id) for t in e.tareas]
    diagnosticado = _diagnosticar(base, abrir)
    resumen = puntos(ajustes, bd)
    log_mode = diagnosticado.log_mode or (perfil.log_mode if perfil else LogMode.NOARCHIVELOG)
    procedimiento = generar(
        SolicitudProcedimiento(
            bd=base.nombre,
            escenario=elegido,
            log_mode=log_mode,
            dbid=perfil.dbid if perfil else None,
            destino_autobackup=_destino_autobackup(ajustes, destinos),
            objetivo=objetivo,
            hasta=hasta,
            pieza_controlfile=next((p.controlfile for p in resumen.puntos if p.controlfile), None),
            danados=diagnosticado.archivos,
            contenedor_de_datafile=_contenedores(perfil),
            hay_respaldo=bool(resumen.puntos),
        )
    )
    avisos = [*procedimiento.avisos, *diagnosticado.avisos]
    if base.ambiente is not Ambiente.PRUEBAS:
        avisos.append(AVISO_AMBIENTE)
    archivo = None
    if guardar and procedimiento.script is not None:
        momento = diagnosticado.generado_en.strftime("%Y%m%d_%H%M%S")
        ruta = ajustes.rutas.recuperacion / nombres.segmento(base.nombre) / f"{elegido.value}_{momento}.rman"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(bytes_ascii(procedimiento.script))
        archivo = str(ruta)
    return procedimiento.model_copy(update={"avisos": avisos, "archivo": archivo})
