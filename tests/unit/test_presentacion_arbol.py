from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.presentacion.arbol import NodoArbol, OpcionesArbol, TipoNodo, construir_nodos, id_nodo


def _todos(nodo: NodoArbol) -> list[NodoArbol]:
    return [nodo, *(n for hijo in nodo.hijos for n in _todos(hijo))]


def _por_id(raiz: NodoArbol) -> dict[str, NodoArbol]:
    return {n.id: n for n in _todos(raiz)}


def test_ids_unicos_y_validos(exploracion_xe: Exploracion) -> None:
    nodos = _todos(construir_nodos(exploracion_xe, OpcionesArbol()))
    ids = [n.id for n in nodos]
    assert len(ids) == len(set(ids))
    assert all(i.replace("-", "").replace("_", "").isalnum() for i in ids)


def test_cada_hallazgo_tiene_su_nodo(exploracion_xe: Exploracion) -> None:
    nodos = _por_id(construir_nodos(exploracion_xe, OpcionesArbol()))
    for hallazgo in exploracion_xe.hallazgos:
        assert hallazgo in nodos[id_nodo(hallazgo.sujeto)].hallazgos


def test_jerarquia(exploracion_xe: Exploracion) -> None:
    raiz = construir_nodos(exploracion_xe, OpcionesArbol())
    assert raiz.tipo is TipoNodo.INSTANCIA
    assert len(raiz.hijos) == 2
    assert raiz.hijos[0].tipo is TipoNodo.GRUPO_PRINCIPAL
    containers = raiz.hijos[1]
    assert containers.tipo is TipoNodo.GRUPO_PRINCIPAL
    assert containers.titulo.startswith("Contenedores")
    assert [h.titulo for h in containers.hijos] == ["CDB$ROOT", "PDB$SEED", "XEPDB1"]
    pdb = containers.hijos[-1]
    assert len(pdb.hijos) == 1
    tablespaces = pdb.hijos[0]
    assert tablespaces.tipo is TipoNodo.GRUPO
    assert tablespaces.titulo.startswith("Tablespaces")
    assert [t.titulo for t in tablespaces.hijos][:3] == ["SYSTEM", "SYSAUX", "UNDOTBS1"]
    assert tablespaces.hijos[-1].titulo == "TEMP"
    assert all(t.tipo is TipoNodo.TABLESPACE for t in tablespaces.hijos)
    assert all(len(t.hijos) == 1 and t.hijos[0].tipo is TipoNodo.GRUPO for t in tablespaces.hijos)
    archivos_system = tablespaces.hijos[0].hijos[0]
    assert archivos_system.titulo.startswith("Datafiles")
    archivos_temp = tablespaces.hijos[-1].hijos[0]
    assert archivos_temp.titulo.startswith("Tempfiles")
    assert all(a.tipo is TipoNodo.ARCHIVO for t in tablespaces.hijos for a in t.hijos[0].hijos)


def test_modo_web_abre_solo_la_instancia(exploracion_xe: Exploracion) -> None:
    nodos = _por_id(construir_nodos(exploracion_xe, OpcionesArbol(), modo="web"))
    assert nodos["instancia"].abierto
    assert not nodos["archivos-instancia"].abierto
    assert not nodos["containers"].abierto
    assert not nodos["redo"].abierto
    assert not nodos["contenedor-3"].abierto
    assert not nodos["contenedor-2"].abierto
    assert not nodos["tablespace-3-USERS"].abierto


def test_modo_cli_abre_todo(exploracion_xe: Exploracion) -> None:
    assert all(n.abierto for n in _todos(construir_nodos(exploracion_xe, OpcionesArbol(), modo="cli")))


def test_id_nodo_sanea_caracteres() -> None:
    assert id_nodo("tablespace:3:SYS$AUX#1") == "tablespace-3-SYS_AUX_1"
