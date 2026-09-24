import pytest

from cloudcr_backup.oracle.discovery import descubrir_instancias
from cloudcr_backup.oracle.explorador import explorar_local, resolver_instancia

pytestmark = pytest.mark.oracle


def test_explora_la_instancia_local_en_ejecucion() -> None:
    instancia = resolver_instancia(descubrir_instancias(), None, None)
    exploracion = explorar_local(instancia)
    perfil = exploracion.perfil
    assert perfil.dbid > 0
    assert perfil.controlfiles
    assert perfil.redo_grupos and all(g.miembros for g in perfil.redo_grupos)
    assert perfil.datafiles
    assert {d.con_id for d in perfil.datafiles} <= {c.con_id for c in perfil.contenedores}
    assert all(perfil.tablespaces_de(t.con_id) for t in perfil.tablespaces)
