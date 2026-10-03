from datetime import date
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, Response

from cloudcr_backup.domain.enums import EstadoEjecucion
from cloudcr_backup.domain.errores import FiltroInvalido
from cloudcr_backup.domain.historial import ConsultaHistorial
from cloudcr_backup.presentacion.detalle import secciones
from cloudcr_backup.presentacion.historial import LEYENDA_SIMBOLOS, TEXTO_RESULTADO, construir_tabla
from cloudcr_backup.web.monitoreo import ProveedorMonitoreo, obtener_monitoreo
from cloudcr_backup.web.rutas.comun import es_htmx, renderizar

router = APIRouter()

Monitoreo = Annotated[ProveedorMonitoreo, Depends(obtener_monitoreo)]
FORMATOS_EXPORTACION = ("csv", "md", "html")


def _texto(valor: str | None) -> str | None:
    texto = (valor or "").strip()
    return texto or None


def _fecha(valor: str | None, campo: str) -> date | None:
    texto = _texto(valor)
    if texto is None:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError as error:
        raise FiltroInvalido(
            f"'{texto}' no es una fecha válida para '{campo}'.", "Use el formato AAAA-MM-DD."
        ) from error


def _estado(valor: str | None) -> EstadoEjecucion | None:
    texto = _texto(valor)
    if texto is None:
        return None
    try:
        return EstadoEjecucion(texto.upper())
    except ValueError as error:
        opciones = ", ".join(e.value for e in EstadoEjecucion)
        raise FiltroInvalido(f"El estado '{texto}' no existe.", f"Use uno de: {opciones}.") from error


def consulta_desde_query(
    bd: Annotated[str | None, Query(max_length=30)] = None,
    estrategia: Annotated[str | None, Query(max_length=20)] = None,
    estado: Annotated[str | None, Query(max_length=20)] = None,
    desde: Annotated[str | None, Query(max_length=10)] = None,
    hasta: Annotated[str | None, Query(max_length=10)] = None,
    limite: Annotated[int, Query(ge=1, le=500)] = 50,
    pagina: Annotated[int, Query(ge=1)] = 1,
) -> ConsultaHistorial:
    return ConsultaHistorial(
        bd=_texto(bd),
        estrategia=_texto(estrategia),
        estado=_estado(estado),
        desde=_fecha(desde, "desde"),
        hasta=_fecha(hasta, "hasta"),
        limite=limite,
        pagina=pagina,
    )


Consulta = Annotated[ConsultaHistorial, Depends(consulta_desde_query)]


def parametros_consulta(consulta: ConsultaHistorial, pagina: int | None = None) -> str:
    valores = {
        "bd": consulta.bd or "",
        "estrategia": consulta.estrategia or "",
        "estado": consulta.estado.value if consulta.estado else "",
        "desde": consulta.desde.isoformat() if consulta.desde else "",
        "hasta": consulta.hasta.isoformat() if consulta.hasta else "",
        "limite": str(consulta.limite),
    }
    if pagina is not None:
        valores["pagina"] = str(pagina)
    return urlencode({clave: valor for clave, valor in valores.items() if valor})


@router.get("/historial", response_class=HTMLResponse)
def pagina_historial(request: Request, monitoreo: Monitoreo, consulta: Consulta) -> HTMLResponse:
    resultado = monitoreo.historial(consulta)
    contexto: dict[str, Any] = {
        "seccion": "historial",
        "consulta": consulta,
        "resultado": resultado,
        "tabla": construir_tabla(resultado.filas),
        "estados": [(e.value, TEXTO_RESULTADO[e]) for e in EstadoEjecucion],
        "leyenda": LEYENDA_SIMBOLOS,
        "filtros": parametros_consulta(consulta),
        "anterior": parametros_consulta(consulta, resultado.pagina - 1) if resultado.pagina > 1 else None,
        "siguiente": (
            parametros_consulta(consulta, resultado.pagina + 1) if resultado.pagina < resultado.paginas else None
        ),
        "formatos": FORMATOS_EXPORTACION,
    }
    plantilla = "parciales/_historial.html" if es_htmx(request) else "historial.html"
    return renderizar(request, plantilla, contexto)


@router.get("/historial/exportar/{formato}", response_model=None)
def exportar_historial(formato: str, monitoreo: Monitoreo, consulta: Consulta) -> Response:
    archivo = monitoreo.exportar_historial(consulta, formato)
    return Response(
        content=archivo.contenido,
        media_type=archivo.tipo_contenido,
        headers={"Content-Disposition": f'attachment; filename="{archivo.nombre}"'},
    )


@router.get("/historial/{ejecucion_id}", response_class=HTMLResponse)
def pagina_detalle(request: Request, ejecucion_id: int, monitoreo: Monitoreo) -> HTMLResponse:
    detalle = monitoreo.detalle_ejecucion(ejecucion_id)
    contexto = {
        "seccion": "historial",
        "detalle": detalle,
        "fila": construir_tabla([detalle.fila]).filas[0],
        "secciones": secciones(detalle),
    }
    return renderizar(request, "historial_detalle.html", contexto)


@router.get("/api/historial")
def api_historial(monitoreo: Monitoreo, consulta: Consulta) -> dict[str, Any]:
    resultado = monitoreo.historial(consulta)
    tabla = construir_tabla(resultado.filas)
    return {
        "total": resultado.total,
        "pagina": resultado.pagina,
        "paginas": resultado.paginas,
        "limite": resultado.limite,
        "filas": [fila.model_dump(mode="json") for fila in resultado.filas],
        "columnas": list(tabla.columnas),
        "tabla": tabla.matriz(),
        "notas": tabla.notas,
    }


@router.get("/api/historial/{ejecucion_id}")
def api_detalle(ejecucion_id: int, monitoreo: Monitoreo) -> dict[str, Any]:
    return monitoreo.detalle_ejecucion(ejecucion_id).model_dump(mode="json")
