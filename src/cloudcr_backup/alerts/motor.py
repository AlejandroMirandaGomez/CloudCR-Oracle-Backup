import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from cloudcr_backup.alerts.instantanea import Instantanea
from cloudcr_backup.alerts.reglas import REGLAS, ReglaAlerta
from cloudcr_backup.domain.alertas import CodigoAlerta, Condicion, ResumenEvaluacion, VistaAlerta
from cloudcr_backup.scheduling.reloj import utc_consciente

REGISTRO = logging.getLogger("cloudcr.alertas")


class FuenteAlertas(Protocol):
    def instantanea(self, ahora: datetime) -> Instantanea: ...

    def vigentes(self) -> list[VistaAlerta]: ...

    def abrir(self, condicion: Condicion) -> tuple[VistaAlerta, bool]: ...

    def resolver(self, alerta_id: int) -> bool: ...


class Notificador(Protocol):
    nombre: str

    def notificar(self, alerta: VistaAlerta, condicion: Condicion) -> None: ...


class MotorAlertas:
    def __init__(
        self,
        fuente: FuenteAlertas,
        notificadores: Sequence[Notificador] = (),
        reglas: dict[CodigoAlerta, ReglaAlerta] | None = None,
    ) -> None:
        self._fuente = fuente
        self._notificadores = list(notificadores)
        self._reglas = REGLAS if reglas is None else reglas

    def condiciones(self, instantanea: Instantanea, resumen: ResumenEvaluacion) -> tuple[list[Condicion], set[str]]:
        condiciones: dict[str, Condicion] = {}
        fallidas: set[str] = set()
        for codigo, regla in self._reglas.items():
            try:
                for condicion in regla(instantanea):
                    condiciones.setdefault(condicion.clave_dedup, condicion)
            except Exception as error:
                fallidas.add(codigo.value)
                resumen.errores.append(f"La regla {codigo.value} falló: {error}")
                REGISTRO.exception("La regla %s falló", codigo.value)
        return list(condiciones.values()), fallidas

    def evaluar(self, ahora: datetime) -> ResumenEvaluacion:
        resumen = ResumenEvaluacion(evaluada_en=utc_consciente(ahora))
        instantanea = self._fuente.instantanea(utc_consciente(ahora))
        condiciones, fallidas = self.condiciones(instantanea, resumen)
        vigentes = self._fuente.vigentes()
        for condicion in condiciones:
            self._persistir(condicion, resumen)
        claves_actuales = {condicion.clave_dedup for condicion in condiciones}
        codigos_evaluados = {codigo.value for codigo in self._reglas} - fallidas
        for alerta in vigentes:
            if alerta.codigo not in codigos_evaluados or alerta.clave_dedup in claves_actuales:
                continue
            if self._fuente.resolver(alerta.id):
                resumen.resueltas.append(alerta.clave_dedup)
        return resumen

    def registrar_evento(self, condiciones: Sequence[Condicion], ahora: datetime) -> ResumenEvaluacion:
        resumen = ResumenEvaluacion(evaluada_en=utc_consciente(ahora))
        for condicion in condiciones:
            self._persistir(condicion, resumen)
        return resumen

    def _persistir(self, condicion: Condicion, resumen: ResumenEvaluacion) -> None:
        alerta, es_nueva = self._fuente.abrir(condicion)
        if not es_nueva:
            resumen.actualizadas.append(condicion.clave_dedup)
            return
        resumen.abiertas.append(condicion.clave_dedup)
        for notificador in self._notificadores:
            try:
                notificador.notificar(alerta, condicion)
            except Exception as error:
                resumen.errores.append(f"El notificador {notificador.nombre} falló: {error}")
                REGISTRO.exception("El notificador %s falló con la alerta %s", notificador.nombre, alerta.id)
            else:
                resumen.notificadas.append(f"{notificador.nombre}:{condicion.clave_dedup}")
