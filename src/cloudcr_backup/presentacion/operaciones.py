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
    Escenario.TABLESPACE: "Pérdida de un tablespace (PERDIDA_DATAFILE_NO_CRITICO)",
    Escenario.DATAFILE: "Pérdida de un datafile no crítico (PERDIDA_DATAFILE_NO_CRITICO)",
    Escenario.DATAFILE_CRITICO: "Pérdida de un datafile crítico: SYSTEM o UNDO (PERDIDA_DATAFILE_CRITICO)",
    Escenario.CONTROLFILE: "Pérdida del control file (PERDIDA_CONTROL_FILE)",
    Escenario.MIEMBRO_REDOLOG: "Pérdida de un miembro de redo log (PERDIDA_MIEMBRO_REDOLOG)",
    Escenario.GRUPO_REDOLOG_ACTUAL: "Pérdida del grupo de redo log actual (PERDIDA_GRUPO_REDOLOG_CURRENT)",
    Escenario.CORRUPCION_BLOQUE: "Corrupción de bloques (CORRUPCION_DE_BLOQUE)",
    Escenario.SPFILE: "Pérdida del SPFILE (PERDIDA_SPFILE)",
    Escenario.TOTAL_NOARCHIVELOG: "Pérdida total sin ARCHIVELOG: respaldo consistente (PERDIDA_TOTAL_SIN_ARCHIVELOG)",
    Escenario.PUNTO_EN_TIEMPO: "Recuperación a un punto en el tiempo",
}

AYUDA_OBJETIVO = {
    Escenario.PDB: "Nombre de la PDB, por ejemplo XEPDB1. Si se deja vacío se deduce del diagnóstico.",
    Escenario.TABLESPACE: "PDB:TABLESPACE, por ejemplo XEPDB1:USERS. Si se deja vacío se deduce del diagnóstico.",
    Escenario.DATAFILE: "Número del datafile (file#). Si se deja vacío se deduce de V$RECOVER_FILE.",
    Escenario.DATAFILE_CRITICO: (
        "Número del datafile de SYSTEM o UNDO (file#). Si se deja vacío se deduce de V$RECOVER_FILE. "
        "Detiene la instancia y la recupera montada."
    ),
    Escenario.CONTROLFILE: "No necesita objetivo.",
    Escenario.MIEMBRO_REDOLOG: (
        "GRUPO:RUTA del miembro dañado, por ejemplo 2:C:\\ORADATA\\XE\\REDO02B.LOG. "
        "Si se deja vacío se deduce de V$LOGFILE y de los archivos que faltan en disco."
    ),
    Escenario.GRUPO_REDOLOG_ACTUAL: (
        "Secuencia (SEQUENCE#) del grupo CURRENT perdido, o HILO:SECUENCIA. Si se deja vacío se deduce de V$LOG. "
        "Misma familia que «punto en el tiempo» (recuperación incompleta), pero no pide hora: se detiene antes del "
        "log perdido, como RECOVER DATABASE UNTIL CANCEL."
    ),
    Escenario.CORRUPCION_BLOQUE: (
        "FILE#:BLOQUE, por ejemplo 7:131. Si se deja vacío se recuperan todos los bloques de "
        "V$DATABASE_BLOCK_CORRUPTION."
    ),
    Escenario.SPFILE: "No necesita objetivo.",
    Escenario.TOTAL_NOARCHIVELOG: (
        "Normalmente no necesita objetivo. Escriba controlfile si también se perdió el control file: el "
        "procedimiento lo restaura antes con el DBID y el autobackup (se usa solo si la instancia no responde)."
    ),
    Escenario.PUNTO_EN_TIEMPO: (
        "Indique el momento en «Hasta». Sirve para volver a una hora exacta por otro motivo, por ejemplo un "
        "DROP TABLE accidental; si se perdió el grupo de redo actual use ese escenario, que no pide hora."
    ),
}

TONO_SEVERIDAD = {
    Severidad.ERROR: "peligro",
    Severidad.ADVERTENCIA: "advertencia",
    Severidad.RECOMENDACION: "dato",
    Severidad.INFORMATIVA: "atenuado",
}
