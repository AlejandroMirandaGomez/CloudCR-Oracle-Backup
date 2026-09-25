import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from cloudcr_backup.domain.enums import ContenidoTablespace, LogMode
from cloudcr_backup.domain.hallazgos import Hallazgo
from cloudcr_backup.domain.perfil_bd import (
    ArchivoFisico,
    ContenedorInfo,
    DatafileInfo,
    PerfilBD,
    TablespaceInfo,
    TempfileInfo,
)
from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.oracle.observaciones import (
    SUJETO_ARCHIVADO,
    SUJETO_CONTROLFILES,
    SUJETO_INSTANCIA,
    SUJETO_PARAMETROS,
    SUJETO_REDO,
    sujeto_contenedor,
    sujeto_datafile,
    sujeto_redo_grupo,
    sujeto_tablespace,
)
from cloudcr_backup.presentacion.formato import (
    DESCRIPCION_CONTENIDO,
    DESCRIPCION_PARAMETROS,
    Tono,
    formato_bytes,
    nombre_edicion,
    tono_uso,
)

Modo = Literal["cli", "web"]
SEPARADOR = "  ·  "
ORDEN_SISTEMA = {"SYSTEM": 0, "SYSAUX": 1}
ESTADOS_NORMALES = {"ONLINE", "SYSTEM", "AVAILABLE"}
CARACTERES_NO_VALIDOS_ID = re.compile(r"[^A-Za-z0-9_-]")
SUJETO_GRUPO_INSTANCIA = "archivos-instancia"


class TipoNodo(StrEnum):
    INSTANCIA = "instancia"
    GRUPO_PRINCIPAL = "grupo-principal"
    GRUPO = "grupo"
    REDO_GRUPO = "redo-grupo"
    CONTENEDOR = "contenedor"
    TABLESPACE = "tablespace"
    ARCHIVO = "archivo"
    TEXTO = "texto"


@dataclass(frozen=True)
class OpcionesArbol:
    pdb: str | None = None
    sin_seed: bool = False
    rutas_completas: bool = False


@dataclass(frozen=True)
class Detalle:
    texto: str
    tono: Tono = Tono.NORMAL
    prefijo: str = SEPARADOR


@dataclass
class NodoArbol:
    id: str
    tipo: TipoNodo
    titulo: str
    tono_titulo: Tono | None = None
    detalles: list[Detalle] = field(default_factory=list)
    lineas_extra: list[list[Detalle]] = field(default_factory=list)
    ubicacion: str | None = None
    porcentaje_uso: float | None = None
    hallazgos: list[Hallazgo] = field(default_factory=list)
    hijos: list["NodoArbol"] = field(default_factory=list)
    abierto: bool = True

    @property
    def es_hoja(self) -> bool:
        return not self.hijos and not self.hallazgos


def id_nodo(sujeto: str) -> str:
    return CARACTERES_NO_VALIDOS_ID.sub("_", sujeto.replace(":", "-"))


def perfil_tiene_pdb(perfil: PerfilBD, nombre: str) -> bool:
    return any(c.nombre.upper() == nombre.upper() for c in perfil.contenedores)


def uso_tablespace(datafiles: list[DatafileInfo]) -> float | None:
    usados = [d.bytes_usados for d in datafiles]
    if not datafiles or any(u is None for u in usados):
        return None
    limite = sum(d.limite_bytes for d in datafiles)
    if limite == 0:
        return None
    return sum(u for u in usados if u is not None) / limite * 100


def ordenar_tablespaces(tablespaces: list[TablespaceInfo]) -> list[TablespaceInfo]:
    def clave(tablespace: TablespaceInfo) -> tuple[int, str]:
        if tablespace.nombre in ORDEN_SISTEMA:
            return ORDEN_SISTEMA[tablespace.nombre], tablespace.nombre
        if tablespace.contenido is ContenidoTablespace.UNDO:
            return 2, tablespace.nombre
        if tablespace.contenido is ContenidoTablespace.TEMPORAL:
            return 4, tablespace.nombre
        return 3, tablespace.nombre

    return sorted(tablespaces, key=clave)


class ConstructorNodos:
    def __init__(self, exploracion: Exploracion, opciones: OpcionesArbol) -> None:
        self._perfil = exploracion.perfil
        self._opciones = opciones
        self._por_sujeto: dict[str, list[Hallazgo]] = defaultdict(list)
        for hallazgo in exploracion.hallazgos:
            self._por_sujeto[hallazgo.sujeto].append(hallazgo)

    def construir(self) -> NodoArbol:
        raiz = self._raiz()
        raiz.hijos.append(self._archivos_instancia())
        raiz.hijos.append(self._containers())
        return raiz

    def _containers(self) -> NodoArbol:
        contenedores = self.contenedores_visibles()
        return NodoArbol(
            id=id_nodo("containers"),
            tipo=TipoNodo.GRUPO_PRINCIPAL,
            titulo=f"Contenedores ({len(contenedores)})",
            hijos=[self._contenedor(c) for c in contenedores],
        )

    def contenedores_visibles(self) -> list[ContenedorInfo]:
        visibles = []
        for contenedor in self._perfil.contenedores:
            if self._opciones.sin_seed and contenedor.es_semilla:
                continue
            if self._opciones.pdb and contenedor.nombre.upper() != self._opciones.pdb.upper():
                continue
            visibles.append(contenedor)
        return visibles

    def _hallazgos(self, sujeto: str) -> list[Hallazgo]:
        return list(self._por_sujeto.get(sujeto, []))

    def _raiz(self) -> NodoArbol:
        perfil = self._perfil
        tipo = "CDB (multitenant)" if perfil.es_cdb else "no-CDB"
        tono_modo = Tono.EXITO if perfil.log_mode is LogMode.ARCHIVELOG else Tono.ADVERTENCIA
        return NodoArbol(
            id=id_nodo(SUJETO_INSTANCIA),
            tipo=TipoNodo.INSTANCIA,
            titulo=f"Instancia {perfil.nombre_instancia.upper()}",
            detalles=[Detalle(f"Oracle Database {perfil.version} {nombre_edicion(perfil.edicion)}")],
            lineas_extra=[
                [
                    Detalle(
                        f"Base {perfil.nombre} · {tipo} · DBID {perfil.dbid} · host {perfil.host} · {perfil.open_mode}",
                        Tono.ATENUADO,
                        prefijo="",
                    )
                ],
                [Detalle("Modo de archivado: ", prefijo=""), Detalle(perfil.log_mode.value, tono_modo, prefijo="")],
            ],
            hallazgos=self._hallazgos(SUJETO_INSTANCIA),
        )

    def _archivo(self, identificador: str, archivo: ArchivoFisico, detalles: list[Detalle]) -> NodoArbol:
        completas = self._opciones.rutas_completas
        return NodoArbol(
            id=id_nodo(identificador),
            tipo=TipoNodo.ARCHIVO,
            titulo=archivo.ruta if completas else archivo.nombre_archivo,
            detalles=detalles,
            ubicacion=None if completas else archivo.directorio,
        )

    def _archivos_instancia(self) -> NodoArbol:
        titulo = "Archivos de la instancia"
        if self._perfil.es_cdb:
            titulo += " (compartidos por todos los contenedores)"
        return NodoArbol(
            id=id_nodo(SUJETO_GRUPO_INSTANCIA),
            tipo=TipoNodo.GRUPO_PRINCIPAL,
            titulo=titulo,
            hijos=[self._control_files(), self._redo_logs(), self._parametros(), self._archivado()],
        )

    def _control_files(self) -> NodoArbol:
        controlfiles = self._perfil.controlfiles
        hijos = []
        for indice, controlfile in enumerate(controlfiles):
            detalles = [Detalle(formato_bytes(controlfile.bytes), Tono.DATO)]
            if controlfile.estado:
                detalles.append(Detalle(controlfile.estado, Tono.ADVERTENCIA))
            hijos.append(self._archivo(f"controlfile:{indice}", controlfile, detalles))
        return NodoArbol(
            id=id_nodo(SUJETO_CONTROLFILES),
            tipo=TipoNodo.GRUPO,
            titulo=f"Control files ({len(controlfiles)})",
            hallazgos=self._hallazgos(SUJETO_CONTROLFILES),
            hijos=hijos,
        )

    def _redo_logs(self) -> NodoArbol:
        grupos = self._perfil.redo_grupos
        miembros = {len(g.miembros) for g in grupos}
        resumen = f"{len(grupos)} grupos"
        if len({g.bytes for g in grupos}) == 1 and grupos:
            resumen += f" · {formato_bytes(grupos[0].bytes)} c/u"
        if len(miembros) == 1:
            cantidad = miembros.pop()
            resumen += f" · {cantidad} miembro{'s' if cantidad != 1 else ''} por grupo"
        hijos = []
        for grupo in grupos:
            miembros_nodo = []
            for indice, miembro in enumerate(grupo.miembros):
                detalles = [Detalle(miembro.estado, Tono.ADVERTENCIA)] if miembro.estado else []
                miembros_nodo.append(self._archivo(f"redo:{grupo.grupo}:{indice}", miembro, detalles))
            hijos.append(
                NodoArbol(
                    id=id_nodo(sujeto_redo_grupo(grupo.grupo)),
                    tipo=TipoNodo.REDO_GRUPO,
                    titulo=f"Grupo {grupo.grupo}",
                    detalles=[
                        Detalle(grupo.estado, Tono.EXITO if grupo.estado == "CURRENT" else Tono.NORMAL),
                        Detalle(f"hilo {grupo.hilo} · secuencia {grupo.secuencia}", Tono.ATENUADO),
                        Detalle(formato_bytes(grupo.bytes), Tono.DATO, prefijo=" · "),
                        Detalle(f"archivado: {'sí' if grupo.archivado else 'no'}", Tono.ATENUADO, prefijo=" · "),
                    ],
                    hallazgos=self._hallazgos(sujeto_redo_grupo(grupo.grupo)),
                    hijos=miembros_nodo,
                )
            )
        return NodoArbol(
            id=id_nodo(SUJETO_REDO),
            tipo=TipoNodo.GRUPO,
            titulo="Redo logs",
            detalles=[Detalle(f"({resumen})", Tono.ATENUADO, prefijo="  ")],
            hallazgos=self._hallazgos(SUJETO_REDO),
            hijos=hijos,
        )

    def _parametros(self) -> NodoArbol:
        hijos = [
            self._archivo(
                f"parametro:{indice}",
                archivo,
                [Detalle(DESCRIPCION_PARAMETROS[archivo.tipo], Tono.EXITO if archivo.en_uso else Tono.NORMAL)],
            )
            for indice, archivo in enumerate(self._perfil.archivos_parametros)
        ]
        return NodoArbol(
            id=id_nodo(SUJETO_PARAMETROS),
            tipo=TipoNodo.GRUPO,
            titulo="Archivos de parámetros",
            hallazgos=self._hallazgos(SUJETO_PARAMETROS),
            hijos=hijos,
        )

    def _archivado(self) -> NodoArbol:
        perfil = self._perfil
        hijos: list[NodoArbol] = []
        if perfil.log_mode is LogMode.NOARCHIVELOG:
            hijos.append(
                NodoArbol(
                    id="archivado-estado",
                    tipo=TipoNodo.TEXTO,
                    titulo="No se generan: la base está en NOARCHIVELOG.",
                    tono_titulo=Tono.ADVERTENCIA,
                )
            )
        else:
            hijos.append(
                NodoArbol(
                    id="archivado-estado",
                    tipo=TipoNodo.TEXTO,
                    titulo=f"Archived logs sin respaldo: {perfil.archivelogs_sin_respaldo}",
                )
            )
        for indice, destino in enumerate(perfil.destinos_archivado):
            configurado = "" if perfil.destino_archivado_configurado else " (por defecto)"
            hijos.append(
                NodoArbol(
                    id=f"archivado-destino-{indice}",
                    tipo=TipoNodo.TEXTO,
                    titulo=f"{destino.nombre}{configurado}: ",
                    detalles=[
                        Detalle(destino.destino, Tono.RESALTADO, prefijo=""),
                        Detalle(destino.estado, Tono.ATENUADO),
                    ],
                )
            )
        area = perfil.area_recuperacion
        if area is not None:
            hijos.append(
                NodoArbol(
                    id="archivado-fra",
                    tipo=TipoNodo.TEXTO,
                    titulo="Área de recuperación: ",
                    detalles=[
                        Detalle(area.ruta, Tono.RESALTADO, prefijo=""),
                        Detalle(f"{formato_bytes(area.usados_bytes)} de {formato_bytes(area.limite_bytes)}", Tono.DATO),
                    ],
                )
            )
        return NodoArbol(
            id=id_nodo(SUJETO_ARCHIVADO),
            tipo=TipoNodo.GRUPO,
            titulo="Archived redo logs",
            hallazgos=self._hallazgos(SUJETO_ARCHIVADO),
            hijos=hijos,
        )

    def _rol(self, contenedor: ContenedorInfo) -> str:
        if not self._perfil.es_cdb:
            return "base de datos"
        if contenedor.es_raiz:
            return "contenedor raíz"
        if contenedor.es_semilla:
            return "plantilla para crear PDBs"
        return "PDB"

    def _contenedor(self, contenedor: ContenedorInfo) -> NodoArbol:
        sujeto = sujeto_contenedor(contenedor.con_id)
        return NodoArbol(
            id=id_nodo(sujeto),
            tipo=TipoNodo.CONTENEDOR,
            titulo=contenedor.nombre,
            detalles=[
                Detalle(self._rol(contenedor), Tono.ATENUADO),
                Detalle(contenedor.open_mode, Tono.EXITO if contenedor.abierto else Tono.ADVERTENCIA),
            ],
            hallazgos=self._hallazgos(sujeto),
            hijos=[self._tablespaces(contenedor)],
        )

    def _tablespaces(self, contenedor: ContenedorInfo) -> NodoArbol:
        tablespaces = ordenar_tablespaces(self._perfil.tablespaces_de(contenedor.con_id))
        return NodoArbol(
            id=id_nodo(f"tablespaces:{contenedor.con_id}"),
            tipo=TipoNodo.GRUPO,
            titulo=f"Tablespaces ({len(tablespaces)})",
            hijos=[self._tablespace(t) for t in tablespaces],
        )

    def _tablespace(self, tablespace: TablespaceInfo) -> NodoArbol:
        perfil = self._perfil
        datafiles = perfil.datafiles_de(tablespace.con_id, tablespace.nombre)
        tempfiles = perfil.tempfiles_de(tablespace.con_id, tablespace.nombre)
        total = sum(d.bytes for d in datafiles) + sum(t.bytes for t in tempfiles)
        detalles = []
        descripcion = DESCRIPCION_CONTENIDO[tablespace.contenido]
        if descripcion:
            detalles.append(Detalle(descripcion, Tono.ATENUADO))
        detalles.append(Detalle(formato_bytes(total), Tono.DATO))
        uso = uso_tablespace(datafiles)
        if uso is not None:
            detalles.append(Detalle(f"{uso:.0f} % usado", tono_uso(uso)))
        if tablespace.estado and tablespace.estado not in ESTADOS_NORMALES:
            detalles.append(Detalle(tablespace.estado, Tono.ADVERTENCIA))
        sujeto = sujeto_tablespace(tablespace.con_id, tablespace.nombre)
        return NodoArbol(
            id=id_nodo(sujeto),
            tipo=TipoNodo.TABLESPACE,
            titulo=tablespace.nombre,
            detalles=detalles,
            porcentaje_uso=uso,
            hallazgos=self._hallazgos(sujeto),
            hijos=[self._archivos_tablespace(tablespace, datafiles, tempfiles)],
        )

    def _archivos_tablespace(
        self, tablespace: TablespaceInfo, datafiles: list[DatafileInfo], tempfiles: list[TempfileInfo]
    ) -> NodoArbol:
        hijos = [*(self._datafile(d) for d in datafiles), *(self._tempfile(t) for t in tempfiles)]
        titulo = "Datafiles" if datafiles else "Tempfiles" if tempfiles else "Archivos"
        return NodoArbol(
            id=id_nodo(f"archivos-tablespace:{tablespace.con_id}:{tablespace.nombre}"),
            tipo=TipoNodo.GRUPO,
            titulo=f"{titulo} ({len(hijos)})",
            hijos=hijos,
        )

    def _datafile(self, datafile: DatafileInfo) -> NodoArbol:
        detalles = [Detalle(f"#{datafile.file_id}", Tono.ATENUADO), Detalle(formato_bytes(datafile.bytes), Tono.DATO)]
        uso = datafile.porcentaje_uso
        if uso is not None:
            detalles.append(Detalle(f"{uso:.0f} % de {formato_bytes(datafile.limite_bytes)}", tono_uso(uso)))
        if datafile.autoextensible:
            detalles.append(Detalle("autoextensible", Tono.ATENUADO))
        if datafile.estado.upper() not in ESTADOS_NORMALES:
            detalles.append(Detalle(datafile.estado, Tono.ADVERTENCIA))
        nodo = self._archivo(sujeto_datafile(datafile.file_id), datafile, detalles)
        nodo.porcentaje_uso = uso
        nodo.hallazgos = self._hallazgos(sujeto_datafile(datafile.file_id))
        return nodo

    def _tempfile(self, tempfile: TempfileInfo) -> NodoArbol:
        detalles = [Detalle("tempfile", Tono.ATENUADO), Detalle(formato_bytes(tempfile.bytes), Tono.DATO)]
        if tempfile.estado.upper() not in ESTADOS_NORMALES:
            detalles.append(Detalle(tempfile.estado, Tono.ADVERTENCIA))
        return self._archivo(f"tempfile:{tempfile.con_id}:{tempfile.file_id}", tempfile, detalles)


def _marcar_abiertos_web(nodo: NodoArbol) -> None:
    for hijo in nodo.hijos:
        _marcar_abiertos_web(hijo)
    nodo.abierto = nodo.tipo is TipoNodo.INSTANCIA


def construir_nodos(exploracion: Exploracion, opciones: OpcionesArbol, modo: Modo = "cli") -> NodoArbol:
    raiz = ConstructorNodos(exploracion, opciones).construir()
    if modo == "web":
        _marcar_abiertos_web(raiz)
    return raiz
