from datetime import datetime
from pathlib import Path

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.errores import OperacionNoPermitida
from cloudcr_backup.domain.estrategia import Estrategia
from cloudcr_backup.domain.retencion import InformeRetencion, ResultadoPurga, RetencionEstrategia
from cloudcr_backup.execution.parser import analizar
from cloudcr_backup.execution.runner import InvocacionRman, escribir_script, lanzar, leer_log
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import estrategias as repositorio_estrategias
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository import piezas as repositorio_piezas
from cloudcr_backup.repository.bases_datos import BaseDatosRegistrada
from cloudcr_backup.retention import politica
from cloudcr_backup.retention.politica import PoliticaNoDefinida, PurgaNoPermitida
from cloudcr_backup.rman import nombres
from cloudcr_backup.scheduling.reloj import RelojSistema, utc_ingenuo
from cloudcr_backup.services import resolucion
from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle
from cloudcr_backup.services.sesion import conexion_repositorio

PARAMETRO_NLS = "rman.nls_lang"
NLS_POR_DEFECTO = "AMERICAN_AMERICA.AL32UTF8"
TIMEOUT_SEGUNDOS = 30 * 60


CARPETA_RETENCION = "retencion"


def carpeta_retencion(ajustes: Ajustes, bd: str) -> Path:
    return ajustes.work_dir / CARPETA_RETENCION / nombres.segmento(bd)


def _marca(momento: datetime) -> str:
    return momento.strftime("%Y%m%d_%H%M%S")


def _ejecutar_rman(
    base: BaseDatosRegistrada, carpeta: Path, nombre: str, contenido: str, nls: str
) -> tuple[str, Path, str | None]:
    script = carpeta / f"{nombre}.rman"
    log = carpeta / f"{nombre}.log"
    escribir_script(script, contenido)
    resultado = lanzar(
        InvocacionRman(
            oracle_home=Path(base.oracle_home),
            sid=base.nombre,
            script=script,
            log=log,
            timeout_segundos=TIMEOUT_SEGUNDOS,
            nls_lang=nls,
        )
    )
    return leer_log(log), log, resultado.error_lanzamiento


def _resumen(
    estrategia: Estrategia,
    piezas: list[repositorio_piezas.PiezaRegistrada],
    ahora: datetime,
    obsoletas: list[str],
) -> RetencionEstrategia:
    propias = [p for p in piezas if p.estrategia_id == estrategia.id and not p.obsoleta]
    avisos = []
    try:
        script = politica.script(estrategia.retencion)
    except PoliticaNoDefinida as error:
        script = None
        avisos.append(str(error))
    return RetencionEstrategia(
        estrategia=estrategia.codigo,
        nombre=estrategia.nombre,
        politica=politica.clausula(estrategia.retencion) if script is not None else None,
        descripcion=politica.describir(estrategia.retencion),
        archived_logs_dias=estrategia.retencion.archived_logs_dias,
        purga_automatica=estrategia.retencion.purga_automatica,
        piezas_total=len(propias),
        vencidas=politica.vencidas(propias, estrategia.retencion, ahora, obsoletas),
        script=script,
        avisos=avisos,
    )


def informe(ajustes: Ajustes, bd: str, consultar_rman: bool = False) -> InformeRetencion:
    preparar_cliente_oracle()
    ahora = RelojSistema().ahora()
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        estrategias = repositorio_estrategias.listar(conexion, base.id)
        piezas = repositorio_piezas.de_base(conexion, base.id)
        perfil = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
        nls = repositorio_parametros.listar(conexion).get(PARAMETRO_NLS) or NLS_POR_DEFECTO
    avisos: list[str] = []
    obsoletas: list[str] = []
    if consultar_rman:
        carpeta = carpeta_retencion(ajustes, base.nombre)
        politicas = sorted({c for e in estrategias if (c := _clausula_segura(e)) is not None})
        for indice, clausula in enumerate(politicas, start=1):
            contenido = f"CROSSCHECK BACKUP;\nREPORT OBSOLETE {clausula};\n"
            texto, log, fallo = _ejecutar_rman(base, carpeta, f"informe_{_marca(ahora)}_{indice}", contenido, nls)
            if fallo or analizar(texto).errores:
                avisos.append(f"RMAN no pudo generar el informe ({clausula}); revise {log}.")
                continue
            obsoletas += politica.obsoletas_de_reporte(texto)
    resultado = InformeRetencion(
        bd=base.nombre,
        generado_en=ahora,
        estrategias=[_resumen(e, piezas, utc_ingenuo(ahora), obsoletas) for e in estrategias],
        archivelogs_sin_respaldo=perfil.archivelogs_sin_respaldo if perfil is not None else None,
        consulto_rman=consultar_rman,
        obsoletas_rman=list(dict.fromkeys(obsoletas)),
        avisos=avisos,
    )
    if not estrategias:
        resultado.avisos.append(f"La base {base.nombre} no tiene estrategias registradas.")
    return resultado


def _clausula_segura(estrategia: Estrategia) -> str | None:
    try:
        return politica.clausula(estrategia.retencion)
    except PoliticaNoDefinida:
        return None


def purgar(ajustes: Ajustes, bd: str, codigo: str, confirmado: bool) -> ResultadoPurga:
    if not confirmado:
        raise OperacionNoPermitida(
            "La purga borra respaldos obsoletos y no se puede deshacer.",
            "Revise primero 'cloudcr retencion informe' y confirme con --purgar.",
        )
    preparar_cliente_oracle()
    ahora = RelojSistema().ahora()
    with conexion_repositorio(ajustes) as conexion:
        base, estrategia = resolucion.estrategia(conexion, bd, codigo)
        try:
            contenido = politica.script(estrategia.retencion, purgar=True)
        except (PoliticaNoDefinida, PurgaNoPermitida) as error:
            raise OperacionNoPermitida(
                str(error), "Active purga_automatica en la retención de la estrategia si el DBA lo decide."
            ) from error
        piezas = repositorio_piezas.de_base(conexion, base.id)
        nls = repositorio_parametros.listar(conexion).get(PARAMETRO_NLS) or NLS_POR_DEFECTO
    carpeta = carpeta_retencion(ajustes, base.nombre)
    texto, log, fallo = _ejecutar_rman(base, carpeta, f"purga_{estrategia.codigo}_{_marca(ahora)}", contenido, nls)
    analizado = analizar(texto)
    errores = [fallo] if fallo else [str(e) for e in analizado.errores]
    borradas = [p.handle for p in analizado.piezas]
    vencidas = politica.vencidas(
        [p for p in piezas if p.estrategia_id == estrategia.id and not p.obsoleta],
        estrategia.retencion,
        utc_ingenuo(ahora),
    )
    marcadas = 0
    if not errores:
        with conexion_repositorio(ajustes) as conexion:
            marcadas = repositorio_piezas.marcar_obsoletas(conexion, [p.pieza_id for p in vencidas])
    return ResultadoPurga(
        bd=base.nombre,
        estrategia=estrategia.codigo,
        script=contenido,
        log=str(log),
        piezas_marcadas=marcadas,
        borradas=borradas,
        errores=errores,
    )
