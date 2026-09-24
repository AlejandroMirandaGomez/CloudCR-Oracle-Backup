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
    assert raiz.hijos[0].tipo is TipoNodo.GRUPO_PRINCIPAL
    assert [h.titulo for h in raiz.hijos[1:]] == ["CDB$ROOT", "PDB$SEED", "XEPDB1"]
    pdb = raiz.hijos[-1]
    assert [t.titulo for t in pdb.hijos][:3] == ["SYSTEM", "SYSAUX", "UNDOTBS1"]
    assert pdb.hijos[-1].titulo == "TEMP"
    assert all(a.tipo is TipoNodo.ARCHIVO for t in pdb.hijos for a in t.hijos)


def test_modo_web_abre_solo_lo_necesario(exploracion_xe: Exploracion) -> None:
    nodos = _por_id(construir_nodos(exploracion_xe, OpcionesArbol(), modo="web"))
    assert nodos["instancia"].abierto
    assert nodos["archivos-instancia"].abierto
    assert nodos["redo"].abierto
    assert nodos["contenedor-3"].abierto
    assert not nodos["contenedor-2"].abierto
    assert not nodos["tablespace-3-USERS"].abierto


def test_modo_cli_abre_todo(exploracion_xe: Exploracion) -> None:
    assert all(n.abierto for n in _todos(construir_nodos(exploracion_xe, OpcionesArbol(), modo="cli")))


def test_id_nodo_sanea_caracteres() -> None:
    assert id_nodo("tablespace:3:SYS$AUX#1") == "tablespace-3-SYS_AUX_1"
