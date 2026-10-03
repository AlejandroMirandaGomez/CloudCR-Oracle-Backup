from datetime import datetime, time

from cloudcr_backup.domain.enums import DiaSemana, PoliticaOmision, TipoFrecuencia
from cloudcr_backup.domain.estrategia import Programacion, Retencion

NOMBRE_DIA = {
    DiaSemana.LUNES: "lunes",
    DiaSemana.MARTES: "martes",
    DiaSemana.MIERCOLES: "miércoles",
    DiaSemana.JUEVES: "jueves",
    DiaSemana.VIERNES: "viernes",
    DiaSemana.SABADO: "sábado",
    DiaSemana.DOMINGO: "domingo",
}

TEXTO_POLITICA = {
    PoliticaOmision.EJECUTAR_EN_VENTANA: "si se pierde, se recupera solo dentro de su ventana",
    PoliticaOmision.OMITIR: "si se pierde, se omite",
    PoliticaOmision.EJECUTAR_SIEMPRE: "si se pierde, se ejecuta apenas sea posible",
}


def _hora(valor: time) -> str:
    return valor.strftime("%H:%M")


def enumerar(elementos: list[str]) -> str:
    if len(elementos) <= 1:
        return "".join(elementos)
    return f"{', '.join(elementos[:-1])} y {elementos[-1]}"


def _intervalo(minutos: int) -> str:
    if minutos % 1440 == 0:
        dias = minutos // 1440
        return "cada día" if dias == 1 else f"cada {dias} días"
    if minutos % 60 == 0:
        horas = minutos // 60
        return "cada hora" if horas == 1 else f"cada {horas} horas"
    return f"cada {minutos} minutos"


def describir_programacion(programacion: Programacion) -> str:
    horas = enumerar([_hora(h) for h in programacion.horas])
    tipo = programacion.tipo_frecuencia
    if tipo is TipoFrecuencia.DIARIA:
        texto = f"Diaria a las {horas}" if horas else "Diaria (sin horas)"
    elif tipo is TipoFrecuencia.SEMANAL:
        dias = enumerar([NOMBRE_DIA[d] for d in programacion.dias_semana]) or "(sin días)"
        texto = f"Semanal los {dias} a las {horas or '(sin horas)'}"
    elif tipo is TipoFrecuencia.MENSUAL:
        dia = programacion.fecha_inicio.day if programacion.fecha_inicio else 1
        texto = f"Mensual el día {dia} a las {horas or '(sin horas)'}"
    elif tipo is TipoFrecuencia.UNA_VEZ:
        fecha = programacion.fecha_inicio.isoformat() if programacion.fecha_inicio else "(sin fecha)"
        hora = _hora(programacion.horas[0]) if programacion.horas else "00:00"
        texto = f"Una vez, el {fecha} a las {hora}"
    else:
        minutos = programacion.intervalo_minutos
        texto = (_intervalo(minutos) if minutos else "intervalo sin definir").capitalize()
        if programacion.fecha_inicio:
            texto += f" desde el {programacion.fecha_inicio.isoformat()}"
    if programacion.ventana is not None:
        ventana = f"{_hora(programacion.ventana.inicio)} a {_hora(programacion.ventana.fin)}"
        texto += f"; ventana {ventana}"
    return f"{texto} ({programacion.zona_horaria}); {TEXTO_POLITICA[programacion.politica_omision]}"


def describir_retencion(retencion: Retencion) -> str:
    partes = []
    if retencion.ventana_dias is not None:
        partes.append(f"ventana de recuperación de {retencion.ventana_dias} días")
    elif retencion.redundancia is not None:
        partes.append(f"redundancia de {retencion.redundancia} copias")
    else:
        partes.append("sin política de retención")
    if retencion.archived_logs_dias is not None:
        partes.append(f"archived logs {retencion.archived_logs_dias} días")
    partes.append("purga automática" if retencion.purga_automatica else "purga manual")
    return "; ".join(partes)


def formato_momento(momento: datetime | None, formato: str = "%Y-%m-%d %H:%M") -> str:
    return momento.strftime(formato) if momento is not None else "—"
