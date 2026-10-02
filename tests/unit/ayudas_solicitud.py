from typing import Any

from cloudcr_backup.services.solicitud_estrategia import SolicitudEstrategia

ALCANCE_BASE = [
    {"tipo": "TABLESPACE", "identificador": "XEPDB1:USERS", "prioridad": "ALTA"},
    {"tipo": "CONTROLFILE", "identificador": "", "prioridad": "ALTA"},
    {"tipo": "SPFILE", "identificador": "", "prioridad": "ALTA"},
]

ESQUEMA_BASE = {
    "esquema": "N0_SEMANAL_N1_DIFERENCIAL_DIARIO",
    "dia_n0": "DOM",
    "hora_n0": "02:00",
    "hora_n1": "15:00",
}


def datos_solicitud(destino: str, **cambios: Any) -> dict[str, Any]:
    datos: dict[str, Any] = {
        "codigo": "est010",
        "nombre": "Producción diaria",
        "descripcion": "",
        "prioridad": "ALTA",
        "creada_por": "ale",
        "alcance": ALCANCE_BASE,
        "esquema": ESQUEMA_BASE,
        "destino_ruta": destino,
        "retencion": {"ventana_dias": 30},
        "guardar_en_repositorio": False,
    }
    datos.update(cambios)
    return datos


def solicitud(destino: str, **cambios: Any) -> SolicitudEstrategia:
    return SolicitudEstrategia.model_validate(datos_solicitud(destino, **cambios))
