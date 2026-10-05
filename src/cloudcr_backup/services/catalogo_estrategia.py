import getpass
import sys
from datetime import time
from pathlib import Path, PureWindowsPath
from typing import Any

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.enums import (
    Compresion,
    DiaSemana,
    LogMode,
    ModoRespaldo,
    PoliticaOmision,
    Prioridad,
    TipoFrecuencia,
    TipoRespaldo,
)
from cloudcr_backup.domain.estrategia import Como, Destino
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.oracle.capacidades import capacidades_de
from cloudcr_backup.rman.constructor import modo_efectivo
from cloudcr_backup.strategy.codigos import siguiente_codigo_sugerido
from cloudcr_backup.strategy.plantillas_esquema import (
    DescripcionEsquema,
    EsquemaPredefinido,
    ParametrosEsquema,
    tareas_de,
    todos_los_esquemas,
)
from cloudcr_backup.strategy.prioridad import todos_los_criterios
from cloudcr_backup.strategy.vocabulario import NOTA_PARCIAL, equivalencia_de, etiqueta_doble

ETIQUETA_DIA = {
    DiaSemana.LUNES: "Lunes",
    DiaSemana.MARTES: "Martes",
    DiaSemana.MIERCOLES: "Miércoles",
    DiaSemana.JUEVES: "Jueves",
    DiaSemana.VIERNES: "Viernes",
    DiaSemana.SABADO: "Sábado",
    DiaSemana.DOMINGO: "Domingo",
}

ETIQUETA_FRECUENCIA = {
    TipoFrecuencia.UNA_VEZ: "Una sola vez",
    TipoFrecuencia.INTERVALO: "Cada cierto intervalo",
    TipoFrecuencia.DIARIA: "Todos los días",
    TipoFrecuencia.SEMANAL: "Días de la semana",
    TipoFrecuencia.MENSUAL: "Una vez al mes",
}

HORA_REFERENCIA = time(2, 0)

ETIQUETA_MODO = {
    ModoRespaldo.AUTO: "Automático",
    ModoRespaldo.EN_LINEA: "En línea",
    ModoRespaldo.CONSISTENTE: "Consistente",
}

DESCRIPCION_MODO = {
    ModoRespaldo.AUTO: "Automático: en línea si la base está en ARCHIVELOG, consistente si no.",
    ModoRespaldo.EN_LINEA: "En línea: la base sigue abierta. Exige ARCHIVELOG.",
    ModoRespaldo.CONSISTENTE: "Consistente: apaga la base de datos mientras dura el respaldo.",
}

ETIQUETA_POLITICA_OMISION = {
    PoliticaOmision.EJECUTAR_EN_VENTANA: "Ejecutar si todavía está dentro de la ventana",
    PoliticaOmision.OMITIR: "Omitir la ejecución perdida",
    PoliticaOmision.EJECUTAR_SIEMPRE: "Ejecutar siempre que se detecte",
}

ESQUEMA_POR_PRIORIDAD = {
    Prioridad.ALTA: EsquemaPredefinido.N0_N1_ACUMULATIVO_CON_ARCHIVELOGS,
    Prioridad.MEDIA: EsquemaPredefinido.N0_SEMANAL_N1_DIFERENCIAL_DIARIO,
    Prioridad.BAJA: EsquemaPredefinido.COMPLETO_SEMANAL,
}


def esquema_recomendado(prioridad: Prioridad, log_mode: LogMode) -> EsquemaPredefinido:
    if log_mode is LogMode.NOARCHIVELOG:
        return EsquemaPredefinido.CONSISTENTE_NOARCHIVELOG
    return ESQUEMA_POR_PRIORIDAD[prioridad]


def destino_sugerido(ajustes: Ajustes, sid: str) -> str:
    if ajustes.destino_defecto is not None:
        return str(ajustes.destino_defecto)
    if sys.platform == "win32":
        return str(PureWindowsPath("C:/backups") / sid)
    return str(Path.home() / "backups" / sid)


def responsable_sugerido() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return ""


def _descripcion_de_modo(modo: ModoRespaldo, log_mode: LogMode) -> str:
    descripcion = DESCRIPCION_MODO[modo]
    if modo is not ModoRespaldo.AUTO:
        return descripcion
    elegido = modo_efectivo(Como(tipo_respaldo=TipoRespaldo.COMPLETO, modo_respaldo=modo), log_mode)
    return f"{descripcion} En esta base equivale a «{ETIQUETA_MODO[elegido]}»."


def _descripcion_de_esquema(descripcion: DescripcionEsquema) -> dict[str, Any]:
    parametros = ParametrosEsquema(
        destino=Destino(ruta="x"), dia_n0=DiaSemana.DOMINGO, hora_n0=HORA_REFERENCIA, hora_n1=HORA_REFERENCIA
    )
    tareas = tareas_de(descripcion.esquema, parametros)
    tipos = {tarea.como.tipo_respaldo for tarea in tareas}
    return {
        "valor": descripcion.esquema.value,
        "nombre": descripcion.nombre,
        "que_hace": descripcion.que_hace,
        "ideal_para": descripcion.ideal_para,
        "nota": descripcion.nota,
        "rotulo_dia": descripcion.rotulo_dia,
        "rotulo_hora_principal": descripcion.rotulo_hora_principal,
        "rotulo_hora_n1": descripcion.rotulo_hora_n1,
        "usa_n1": bool(tipos & {TipoRespaldo.INCREMENTAL_N1_DIFERENCIAL, TipoRespaldo.INCREMENTAL_N1_ACUMULATIVO}),
        "usa_archivelog": TipoRespaldo.ARCHIVELOG in tipos,
        "consistente": any(tarea.como.modo_respaldo is ModoRespaldo.CONSISTENTE for tarea in tareas),
        "tareas": len(tareas),
    }


def construir_catalogo(perfil: PerfilBD, codigos_existentes: list[str], ajustes: Ajustes, sid: str) -> dict[str, Any]:
    capacidades = capacidades_de(perfil.edicion)
    return {
        "instancia": {
            "sid": sid.upper(),
            "nombre": perfil.nombre,
            "edicion": perfil.edicion,
            "log_mode": perfil.log_mode.value,
            "es_cdb": perfil.es_cdb,
        },
        "codigo_sugerido": siguiente_codigo_sugerido(codigos_existentes),
        "codigos_existentes": codigos_existentes,
        "responsable_sugerido": responsable_sugerido(),
        "destino_sugerido": destino_sugerido(ajustes, sid.upper()),
        "zona_horaria": ajustes.zona_horaria,
        "prioridades": [
            {
                "valor": criterio.prioridad.value,
                "rpo_horas": criterio.rpo_horas,
                "rto_horas": criterio.rto_horas,
                "recencia_maxima_horas": criterio.recencia_maxima_horas,
                "esquema_sugerido": criterio.esquema_sugerido,
                "descripcion": criterio.descripcion,
                "esquema_recomendado": esquema_recomendado(criterio.prioridad, perfil.log_mode).value,
            }
            for criterio in todos_los_criterios()
        ],
        "esquemas": [_descripcion_de_esquema(descripcion) for descripcion in todos_los_esquemas()],
        "nota_parcial": NOTA_PARCIAL,
        "tipos_respaldo": [
            {
                "valor": tipo.value,
                "etiqueta": etiqueta_doble(tipo),
                "significado": equivalencia_de(tipo).significado,
            }
            for tipo in TipoRespaldo
        ],
        "modos_respaldo": [
            {
                "valor": modo.value,
                "etiqueta": ETIQUETA_MODO[modo],
                "descripcion": _descripcion_de_modo(modo, perfil.log_mode),
            }
            for modo in DESCRIPCION_MODO
        ],
        "compresiones": [
            compresion.value for compresion in Compresion if compresion in capacidades.compresiones_soportadas
        ],
        "canales_maximos": capacidades.canales_maximos,
        "frecuencias": [{"valor": f.value, "etiqueta": ETIQUETA_FRECUENCIA[f]} for f in TipoFrecuencia],
        "dias_semana": [{"valor": d.value, "etiqueta": ETIQUETA_DIA[d]} for d in DiaSemana],
        "politicas_omision": [
            {"valor": politica.value, "etiqueta": ETIQUETA_POLITICA_OMISION[politica]} for politica in PoliticaOmision
        ],
    }
