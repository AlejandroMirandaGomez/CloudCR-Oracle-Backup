from pathlib import Path

import pytest

from cloudcr_backup.domain.perfil_bd import PerfilBD
from cloudcr_backup.oracle.explorador import Exploracion
from cloudcr_backup.oracle.observaciones import observar

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def perfil_xe() -> PerfilBD:
    return PerfilBD.model_validate_json((FIXTURES / "perfiles_bd" / "xe_noarchivelog.json").read_text(encoding="utf-8"))


@pytest.fixture
def exploracion_xe(perfil_xe: PerfilBD) -> Exploracion:
    return Exploracion(perfil=perfil_xe, hallazgos=observar(perfil_xe))
