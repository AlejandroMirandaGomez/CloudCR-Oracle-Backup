from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from cloudcr_backup.strategy.plantillas_esquema import todos_los_esquemas
from cloudcr_backup.strategy.prioridad import todos_los_criterios
from cloudcr_backup.strategy.vocabulario import NOTA_INCOMPLETO, NOTA_PARCIAL, todas_las_equivalencias
from cloudcr_backup.web.rutas.comun import renderizar

router = APIRouter()


@router.get("/criterios", response_class=HTMLResponse)
def criterios(request: Request) -> HTMLResponse:
    contexto = {
        "seccion": "criterios",
        "prioridades": todos_los_criterios(),
        "esquemas": todos_los_esquemas(),
        "equivalencias": todas_las_equivalencias(),
        "nota_parcial": NOTA_PARCIAL,
        "nota_incompleto": NOTA_INCOMPLETO,
    }
    return renderizar(request, "criterios.html", contexto)
