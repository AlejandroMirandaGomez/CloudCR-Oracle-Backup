import typer

from cloudcr_backup.config.ajustes import cargar_ajustes
from cloudcr_backup.presentacion.terminal import consola
from cloudcr_backup.services.administracion import comprobar_entorno

app = typer.Typer(add_completion=False)


@app.command(name="doctor", help="Diagnostica el entorno: Python, dependencias, configuración, Oracle y destino.")
def doctor() -> None:
    diagnosticos = comprobar_entorno(cargar_ajustes())
    salida = consola()
    salida.print("\n[bold]Diagnóstico de CloudCR Oracle Backup[/]\n", markup=True)
    hay_fallos = False
    for diagnostico in diagnosticos:
        if diagnostico.ok:
            salida.print(f"[green]✓[/] {diagnostico.nombre}: {diagnostico.detalle}", markup=True)
            continue
        hay_fallos = True
        salida.print(f"[red]✗[/] {diagnostico.nombre}: {diagnostico.detalle}", markup=True)
        if diagnostico.sugerencia:
            salida.print(f"    [yellow]Sugerencia:[/] {diagnostico.sugerencia}", markup=True)
    if hay_fallos:
        raise typer.Exit(1)
