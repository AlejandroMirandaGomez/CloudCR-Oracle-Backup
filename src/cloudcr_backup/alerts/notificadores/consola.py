from collections.abc import Callable

from cloudcr_backup.domain.alertas import Condicion, VistaAlerta


def texto_alerta(alerta: VistaAlerta) -> str:
    return f"NUEVA ALERTA [{alerta.severidad.value}] {alerta.codigo} #{alerta.id} — {alerta.mensaje}"


class NotificadorConsola:
    nombre = "consola"

    def __init__(self, escribir: Callable[[str], None] = print) -> None:
        self._escribir = escribir

    def notificar(self, alerta: VistaAlerta, condicion: Condicion) -> None:
        self._escribir(texto_alerta(alerta))
        if condicion.accion_sugerida:
            self._escribir(f"  Acción sugerida: {condicion.accion_sugerida}")
