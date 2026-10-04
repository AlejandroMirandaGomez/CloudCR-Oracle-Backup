from pathlib import Path

from cloudcr_backup.config.ajustes import Ajustes
from cloudcr_backup.domain.administracion import (
    EjemploEstrategia,
    EstrategiaImportada,
    RecomendacionAplicada,
    ResultadoValidacion,
)
from cloudcr_backup.domain.enums import TipoObjeto
from cloudcr_backup.domain.errores import OperacionNoPermitida, RecursoNoEncontrado
from cloudcr_backup.domain.estrategia import Estrategia, ObjetoAlcance
from cloudcr_backup.domain.hallazgos import ordenar_por_severidad
from cloudcr_backup.domain.historial import ArchivoExportado
from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.execution.destino import BaseDestino, perfil_actual
from cloudcr_backup.repository import bases_datos as repositorio_bases_datos
from cloudcr_backup.repository import parametros as repositorio_parametros
from cloudcr_backup.repository.bases_datos import BaseDatosRegistrada
from cloudcr_backup.services import resolucion
from cloudcr_backup.services.cliente_oracle import preparar_cliente_oracle
from cloudcr_backup.services.destinos import inspeccionar_destino
from cloudcr_backup.services.sesion import conexion_repositorio
from cloudcr_backup.strategy import servicio
from cloudcr_backup.strategy.yaml_io import EstrategiaYamlInvalida, estrategia_a_yaml, estrategia_desde_yaml
from cloudcr_backup.validation import motor, reglas  # noqa: F401
from cloudcr_backup.validation.contexto import ContextoValidacion

LARGO_MAXIMO_YAML = 200_000
EXTENSION_YAML = ".yaml"
TIPO_YAML = "application/x-yaml; charset=utf-8"
RECOMENDACIONES_APLICABLES = ("ARCH_002",)
RAIZ_PROYECTO = Path(__file__).resolve().parents[3]


def carpetas_ejemplos() -> list[Path]:
    candidatas = [Path.cwd() / "config" / "estrategias", RAIZ_PROYECTO / "config" / "estrategias"]
    unicas: list[Path] = []
    for carpeta in candidatas:
        if carpeta.is_dir() and carpeta.resolve() not in [c.resolve() for c in unicas]:
            unicas.append(carpeta)
    return unicas


def _archivos_ejemplo() -> dict[str, Path]:
    encontrados: dict[str, Path] = {}
    for carpeta in carpetas_ejemplos():
        for archivo in sorted(carpeta.glob(f"*{EXTENSION_YAML}")):
            if archivo.is_file():
                encontrados.setdefault(archivo.name, archivo)
    return encontrados


def ejemplos() -> list[EjemploEstrategia]:
    resultado = []
    for nombre, ruta in _archivos_ejemplo().items():
        try:
            estrategia = estrategia_desde_yaml(ruta.read_text(encoding="utf-8"))
        except (OSError, EstrategiaYamlInvalida):
            continue
        resultado.append(EjemploEstrategia(archivo=nombre, codigo=estrategia.codigo, nombre=estrategia.nombre))
    return resultado


def contenido_ejemplo(archivo: str) -> str:
    ruta = _archivos_ejemplo().get(archivo.strip())
    if ruta is None:
        raise RecursoNoEncontrado(f"No existe el ejemplo {archivo!r}.", "Elija uno de la lista.")
    return ruta.read_text(encoding="utf-8")


def _leer_yaml(contenido: str) -> Estrategia:
    if not contenido.strip():
        raise OperacionNoPermitida(
            "No hay contenido para importar.", "Pegue el YAML de la estrategia o elija un ejemplo."
        )
    if len(contenido) > LARGO_MAXIMO_YAML:
        raise OperacionNoPermitida(f"El YAML es demasiado grande (máximo {LARGO_MAXIMO_YAML} caracteres).")
    try:
        return estrategia_desde_yaml(contenido)
    except EstrategiaYamlInvalida as error:
        raise OperacionNoPermitida(str(error), "Corrija el YAML y vuelva a intentarlo.") from error


def importar(ajustes: Ajustes, bd: str, contenido: str, reemplazar: bool = False) -> EstrategiaImportada:
    estrategia = _leer_yaml(contenido)
    with conexion_repositorio(ajustes) as conexion:
        base = resolucion.base_por_nombre(conexion, bd)
        nueva = estrategia.model_copy(update={"bd_id": base.id})
        existente = servicio.obtener(conexion, base.id, estrategia.codigo)
        if existente is not None:
            if not reemplazar:
                raise OperacionNoPermitida(
                    f"Ya existe la estrategia {estrategia.codigo} en {base.nombre} (versión {existente.version}).",
                    "Marque «Reemplazar si ya existe» para guardarla como una versión nueva.",
                )
            editada = servicio.editar(conexion, nueva)
            return EstrategiaImportada(
                bd=base.nombre, codigo=editada.codigo, nombre=editada.nombre, version=editada.version, reemplazada=True
            )
        creada = servicio.crear(conexion, nueva)
    return EstrategiaImportada(bd=base.nombre, codigo=creada.codigo, nombre=creada.nombre, version=creada.version)


def exportar(ajustes: Ajustes, bd: str, codigo: str) -> ArchivoExportado:
    with conexion_repositorio(ajustes) as conexion:
        base, estrategia = resolucion.estrategia(conexion, bd, codigo)
    nombre = f"{base.nombre}_{estrategia.codigo}_v{estrategia.version}{EXTENSION_YAML}"
    return ArchivoExportado(nombre=nombre, tipo_contenido=TIPO_YAML, contenido=estrategia_a_yaml(estrategia).encode())


def _perfil(base: BaseDatosRegistrada, guardado: PerfilBD | None, avisos: list[str]) -> tuple[PerfilBD, bool]:
    try:
        return perfil_actual(BaseDestino(oracle_home=Path(base.oracle_home), sid=base.nombre)), True
    except Exception as error:
        if guardado is None:
            raise OperacionNoPermitida(
                f"No se pudo inspeccionar la base {base.nombre} ({error}) y no hay un perfil guardado.",
                "Inicie la instancia o guarde su perfil desde Sistema → Bases de datos.",
            ) from error
        avisos.append(
            f"No se pudo inspeccionar la base en vivo ({error}); se validó con el perfil guardado el "
            f"{guardado.capturado_en:%Y-%m-%d %H:%M}."
        )
        return guardado, False


def _contexto(
    estrategia: Estrategia, perfil: PerfilBD, parametros: dict[str, str], otras: list[str]
) -> ContextoValidacion:
    escribibles: dict[str, bool] = {}
    libres: dict[str, int] = {}
    totales: dict[str, int] = {}
    for ruta in {tarea.destino.ruta for tarea in estrategia.tareas}:
        estado = inspeccionar_destino(ruta)
        escribibles[ruta] = estado.escribible
        if estado.libre_bytes is not None and estado.total_bytes is not None:
            libres[ruta] = estado.libre_bytes
            totales[ruta] = estado.total_bytes
    return ContextoValidacion(
        estrategia=estrategia,
        perfil=perfil,
        parametros=parametros,
        codigos_estrategia_existentes=otras,
        destinos_escribibles=escribibles,
        espacio_libre_destino_bytes=libres,
        espacio_total_destino_bytes=totales,
    )


def validar(ajustes: Ajustes, bd: str, codigo: str) -> ResultadoValidacion:
    preparar_cliente_oracle()
    with conexion_repositorio(ajustes) as conexion:
        base, estrategia = resolucion.estrategia(conexion, bd, codigo)
        parametros = repositorio_parametros.listar(conexion)
        guardado = repositorio_bases_datos.ultimo_perfil(conexion, base.id)
        otras = [e.codigo for e in servicio.listar(conexion, base.id) if e.codigo != estrategia.codigo]
    avisos: list[str] = []
    perfil, en_vivo = _perfil(base, guardado, avisos)
    if en_vivo:
        with conexion_repositorio(ajustes) as conexion:
            repositorio_bases_datos.guardar_perfil(conexion, base.id, perfil)
    hallazgos = motor.validar(_contexto(estrategia, perfil, parametros, otras))
    return ResultadoValidacion(
        bd=base.nombre,
        estrategia=estrategia.codigo,
        version=estrategia.version,
        hallazgos=ordenar_por_severidad(hallazgos),
        perfil_capturado_en=perfil.capturado_en,
        perfil_en_vivo=en_vivo,
        avisos=avisos,
    )


def aplicar_recomendacion(ajustes: Ajustes, bd: str, codigo: str, recomendacion: str) -> RecomendacionAplicada:
    elegida = recomendacion.strip().upper()
    if elegida not in RECOMENDACIONES_APLICABLES:
        raise OperacionNoPermitida(
            f"La recomendación {elegida} no se puede aplicar automáticamente.",
            "Por ahora solo ARCH_002 (agregar los archived logs al alcance) está implementada.",
        )
    with conexion_repositorio(ajustes) as conexion:
        base, estrategia = resolucion.estrategia(conexion, bd, codigo)
        if any(objeto.tipo is TipoObjeto.ARCHIVELOG for objeto in estrategia.alcance):
            return RecomendacionAplicada(
                bd=base.nombre,
                estrategia=estrategia.codigo,
                codigo=elegida,
                version=estrategia.version,
                aplicada=False,
                mensaje="La estrategia ya incluye los archived logs en su alcance: no hubo cambios.",
            )
        nuevo = ObjetoAlcance(tipo=TipoObjeto.ARCHIVELOG, identificador="", prioridad=estrategia.prioridad)
        editada = servicio.editar(conexion, estrategia.model_copy(update={"alcance": [*estrategia.alcance, nuevo]}))
    return RecomendacionAplicada(
        bd=base.nombre,
        estrategia=editada.codigo,
        codigo=elegida,
        version=editada.version,
        aplicada=True,
        mensaje=(
            f"Se agregó ARCHIVELOG al alcance de {editada.codigo} (versión {editada.version}). "
            "Genere y apruebe de nuevo los scripts para que el cambio llegue a RMAN."
        ),
    )
