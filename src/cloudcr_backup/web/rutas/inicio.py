from dataclasses import dataclass, replace
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from cloudcr_backup import __version__
from cloudcr_backup.domain.enums import EstadoEstrategia
from cloudcr_backup.domain.monitoreo import ColorSemaforo, EstadoAgente, ResumenEstrategia
from cloudcr_backup.web.dependencias import ProveedorExploracion, obtener_servicio
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import ErroresRepositorio, avance_del_flujo, estrategia_lista, renderizar

router = APIRouter()

Servicio = Annotated[ProveedorExploracion, Depends(obtener_servicio)]
Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]


@dataclass(frozen=True)
class Paso:
    numero: int
    titulo: str
    pregunta: str
    detalle: str
    enlace: str
    accion: str
    hecho: bool
    estado: str
    bloqueado: bool = False


def construir_pasos(
    instancias_detectadas: int,
    estrategias: list[ResumenEstrategia],
    agentes: list[EstadoAgente],
) -> list[Paso]:
    activas = [e for e in estrategias if e.estado == EstadoEstrategia.ACTIVA]
    listas = [e for e in estrategias if estrategia_lista(e)]
    enlace_preparar = (avance_del_flujo(estrategias)["pendiente"] or {}).get("ruta", "/estrategias")
    con_evidencia = [e for e in estrategias if e.color != ColorSemaforo.SIN_DATOS]
    agente_vivo = any(a.vivo for a in agentes)
    return [
        Paso(
            1,
            "Conocer el entorno",
            "¿Qué bases de datos hay y en qué estado están?",
            "Detecte las instancias Oracle del equipo y revise su modo de archivado, sus tablespaces y sus datafiles.",
            "/instancias",
            "Ver instancias",
            instancias_detectadas > 0,
            f"{instancias_detectadas} detectada(s)" if instancias_detectadas else "Sin instancias detectadas",
        ),
        Paso(
            2,
            "Definir la estrategia",
            "¿Qué, cómo y cuándo respaldar?",
            "Elija los objetos y su prioridad (qué), el tipo de respaldo (cómo) y los horarios (cuándo).",
            "/estrategias",
            "Ver estrategias" if estrategias else "Crear la primera",
            bool(estrategias),
            f"{len(estrategias)} registrada(s)" if estrategias else "Todavía no hay estrategias",
        ),
        Paso(
            3,
            "Preparar y activar",
            "¿Los scripts RMAN están listos y aprobados?",
            "Genere los scripts RMAN de cada tarea, apruébelos y active la estrategia.",
            enlace_preparar,
            "Revisar scripts",
            bool(listas),
            f"{len(activas)} activa(s), {len(listas)} lista(s) para ejecutarse"
            if estrategias
            else "Requiere una estrategia",
        ),
        Paso(
            4,
            "Automatizar la ejecución",
            "¿Quién ejecuta los respaldos a su hora?",
            "El agente lanza los scripts RMAN a su hora. También puede ejecutar una tarea a mano.",
            "/sistema#agente",
            "Ver el agente",
            agente_vivo,
            "Agente en marcha" if agente_vivo else "Agente detenido",
        ),
        Paso(
            5,
            "Comprobar la evidencia",
            "¿Se hicieron los respaldos y cómo terminaron?",
            "Consulte el estado de cada estrategia, el historial de ejecuciones, los mensajes de RMAN y las alertas.",
            "/estado",
            "Ver estado",
            bool(con_evidencia),
            f"{len(con_evidencia)} con ejecuciones" if con_evidencia else "Aún sin ejecuciones",
        ),
        Paso(
            6,
            "Conservar y recuperar",
            "¿Cuánto se conserva y cómo se restaura?",
            "Aplique la retención para liberar espacio y use el plan de recuperación cuando haya una falla.",
            "/recuperacion",
            "Ver recuperación",
            False,
            "Disponible cuando haya respaldos" if not con_evidencia else "Listo para usarse",
        ),
    ]


def bloquear_sin_estrategia(pasos: list[Paso]) -> list[Paso]:
    sin_estrategias = not pasos[1].hecho
    return [replace(p, bloqueado=sin_estrategias and p.numero > 2) for p in pasos]


@router.get("/", response_class=HTMLResponse)
def inicio(request: Request, servicio: Servicio, monitoreo: Monitoreo) -> HTMLResponse:
    instancias = servicio.descubrir()
    estrategias: list[ResumenEstrategia] = []
    agentes: list[EstadoAgente] = []
    alertas_abiertas = 0
    repositorio_disponible = True
    try:
        estrategias = monitoreo.estrategias()
        agentes = monitoreo.agentes()
        alertas_abiertas = len(monitoreo.estado(None).alertas)
    except ErroresRepositorio:
        repositorio_disponible = False
    pasos = bloquear_sin_estrategia(
        construir_pasos(len([i for i in instancias if i.en_ejecucion]), estrategias, agentes)
    )
    siguiente = next((p for p in pasos if not p.hecho), None)
    contexto = {
        "seccion": "inicio",
        **(
            avance_del_flujo(estrategias)
            if repositorio_disponible
            else {"n_estrategias": None, "n_listas": None, "pendiente": None}
        ),
        "instancias": instancias,
        "estrategias": estrategias,
        "pasos": pasos,
        "siguiente": siguiente,
        "completados": sum(1 for p in pasos if p.hecho),
        "alertas_abiertas": alertas_abiertas,
        "agente_vivo": any(a.vivo for a in agentes),
        "repositorio_disponible": repositorio_disponible,
    }
    return renderizar(request, "inicio.html", contexto)


@router.get("/salud")
def salud() -> dict[str, str]:
    return {"estado": "ok", "version": __version__}
