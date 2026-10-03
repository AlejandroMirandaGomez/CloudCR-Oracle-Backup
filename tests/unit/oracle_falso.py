import re
from collections import deque
from typing import Any

PATRON_BIND = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
PATRON_LITERAL = re.compile(r"'[^']*'")


def binds_de(sql: str) -> set[str]:
    return {nombre.lower() for nombre in PATRON_BIND.findall(PATRON_LITERAL.sub("''", sql))}


class VariableFalsa:
    def __init__(self, valor: int) -> None:
        self._valor = valor

    def getvalue(self) -> list[int]:
        return [self._valor]


class CursorFalso:
    def __init__(self, conexion: "ConexionFalsa") -> None:
        self._conexion = conexion
        self.rowcount = 0

    def execute(self, sql: str, **parametros: Any) -> None:
        esperados = binds_de(sql)
        recibidos = {nombre.lower() for nombre in parametros}
        assert esperados == recibidos, f"Binds del SQL {sorted(esperados)} != parámetros {sorted(recibidos)}\n{sql}"
        self._conexion.ejecutados.append((" ".join(sql.split()), parametros))
        error = self._conexion.errores.popleft() if self._conexion.errores else None
        if error is not None:
            raise error
        self.rowcount = self._conexion.filas_afectadas

    def var(self, tipo: type) -> VariableFalsa:
        return VariableFalsa(self._conexion.siguiente_id)

    def fetchone(self) -> Any:
        return self._conexion.respuestas.popleft() if self._conexion.respuestas else None

    def fetchall(self) -> list[Any]:
        respuesta = self._conexion.respuestas.popleft() if self._conexion.respuestas else []
        return list(respuesta)

    def close(self) -> None:
        pass


class ConexionFalsa:
    def __init__(self, respuestas: list[Any] | None = None) -> None:
        self.respuestas: deque[Any] = deque(respuestas or [])
        self.errores: deque[Exception | None] = deque()
        self.ejecutados: list[tuple[str, dict[str, Any]]] = []
        self.commits = 0
        self.rollbacks = 0
        self.siguiente_id = 1
        self.filas_afectadas = 1

    def cursor(self) -> CursorFalso:
        return CursorFalso(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        pass

    def sql(self, indice: int) -> str:
        return self.ejecutados[indice][0]
