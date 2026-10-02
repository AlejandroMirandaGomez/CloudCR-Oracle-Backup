import re

PATRON_CODIGO = re.compile(r"[A-Za-z0-9_-]{1,20}")


def siguiente_codigo_sugerido(existentes: list[str]) -> str:
    numeros = [int(codigo[3:]) for codigo in existentes if codigo.startswith("EST") and codigo[3:].isdigit()]
    return f"EST{max(numeros, default=0) + 1:03d}"


def codigo_es_valido(codigo: str) -> bool:
    return PATRON_CODIGO.fullmatch(codigo) is not None
