import secrets
from dataclasses import dataclass, field

HOSTS_LOCALES = frozenset({"127.0.0.1", "localhost", "::1"})
PUERTO_POR_DEFECTO = 8765
TTL_CACHE_POR_DEFECTO = 60


@dataclass(frozen=True)
class ConfigWeb:
    host: str = "127.0.0.1"
    puerto: int = PUERTO_POR_DEFECTO
    token: str | None = None
    ttl_cache_segundos: int = TTL_CACHE_POR_DEFECTO
    clientes_sin_token: frozenset[str] = field(default_factory=lambda: HOSTS_LOCALES)
    hosts_permitidos: frozenset[str] | None = field(default_factory=lambda: HOSTS_LOCALES)

    @property
    def es_local(self) -> bool:
        return self.host in HOSTS_LOCALES

    @classmethod
    def desde_opciones(cls, host: str, puerto: int, token: str | None, ttl_cache_segundos: int) -> "ConfigWeb":
        local = host in HOSTS_LOCALES
        token_efectivo = token or (None if local else secrets.token_urlsafe(32))
        return cls(
            host=host,
            puerto=puerto,
            token=token_efectivo,
            ttl_cache_segundos=ttl_cache_segundos,
            hosts_permitidos=HOSTS_LOCALES if local else None,
        )
