from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from cloudcr_backup.presentacion.arbol import perfil_tiene_pdb
from cloudcr_backup.reports.exportar_instancia import TIPO_CONTENIDO, FormatoExportacion, exportar, nombre_archivo
from cloudcr_backup.web.rutas.comun import ErroresExploracion, renderizar_error
from cloudcr_backup.web.rutas.instancias import Opciones, OracleHome, Servicio, validar_oracle_home

router = APIRouter()


@router.get("/instancias/{sid}/exportar/{formato}", response_model=None)
def exportar_instancia(
    request: Request,
    sid: str,
    formato: str,
    servicio: Servicio,
    opciones: Opciones,
    oracle_home: OracleHome = None,
) -> Response:
    try:
        formato_elegido = FormatoExportacion(formato.lower())
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Formato de exportación desconocido.") from error
    try:
        home = validar_oracle_home(oracle_home, servicio.descubrir())
        exploracion, _ = servicio.explorar(sid, home, refrescar=False)
    except ErroresExploracion as error:
        return renderizar_error(request, error, sid.upper())
    if opciones.pdb and not perfil_tiene_pdb(exploracion.perfil, opciones.pdb):
        raise HTTPException(status_code=404, detail=f"La instancia no tiene un contenedor llamado {opciones.pdb}.")
    contenido = exportar(exploracion, opciones, formato_elegido)
    archivo = nombre_archivo(exploracion, formato_elegido)
    return Response(
        content=contenido.encode("utf-8"),
        media_type=TIPO_CONTENIDO[formato_elegido],
        headers={"Content-Disposition": f'attachment; filename="{archivo}"'},
    )
