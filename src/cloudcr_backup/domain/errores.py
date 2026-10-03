class ErrorServicio(Exception):
    def __init__(self, mensaje: str, sugerencia: str | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.sugerencia = sugerencia


class RepositorioNoDisponible(ErrorServicio):
    pass


class RecursoNoEncontrado(ErrorServicio):
    pass


class OperacionNoPermitida(ErrorServicio):
    pass


class PipelineNoDisponible(ErrorServicio):
    pass
