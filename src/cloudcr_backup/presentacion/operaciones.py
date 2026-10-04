from cloudcr_backup.domain.enums import EstadoScript, Severidad
from cloudcr_backup.domain.recuperacion import Escenario

TONO_ESTADO_SCRIPT = {
    EstadoScript.BORRADOR: "advertencia",
    EstadoScript.APROBADO: "exito",
    EstadoScript.RECHAZADO: "peligro",
    EstadoScript.OBSOLETO: "atenuado",
}

ETIQUETA_ESTADO_SCRIPT = {
    EstadoScript.BORRADOR: "Borrador sin aprobar",
    EstadoScript.APROBADO: "Aprobado",
    EstadoScript.RECHAZADO: "Rechazado",
    EstadoScript.OBSOLETO: "Obsoleto",
}

ETIQUETA_ESCENARIO = {
    Escenario.PDB: "Pérdida de una PDB",
    Escenario.TABLESPACE: "Pérdida de un tablespace",
    Escenario.DATAFILE: "Pérdida de un datafile",
    Escenario.CONTROLFILE: "Pérdida del control file",
    Escenario.TOTAL_NOARCHIVELOG: "Recuperación total desde un respaldo consistente (NOARCHIVELOG)",
    Escenario.PUNTO_EN_TIEMPO: "Recuperación a un punto en el tiempo",
}

AYUDA_OBJETIVO = {
    Escenario.PDB: "Nombre de la PDB, por ejemplo XEPDB1. Si se deja vacío se deduce del diagnóstico.",
    Escenario.TABLESPACE: "PDB:TABLESPACE, por ejemplo XEPDB1:USERS. Si se deja vacío se deduce del diagnóstico.",
    Escenario.DATAFILE: "Número del datafile (file#). Si se deja vacío se deduce de V$RECOVER_FILE.",
    Escenario.CONTROLFILE: "No necesita objetivo.",
    Escenario.TOTAL_NOARCHIVELOG: "No necesita objetivo.",
    Escenario.PUNTO_EN_TIEMPO: "Indique el momento en «Hasta».",
}

TONO_SEVERIDAD = {
    Severidad.ERROR: "peligro",
    Severidad.ADVERTENCIA: "advertencia",
    Severidad.RECOMENDACION: "dato",
    Severidad.INFORMATIVA: "atenuado",
}
