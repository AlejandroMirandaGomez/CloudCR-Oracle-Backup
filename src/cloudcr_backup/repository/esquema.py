from dataclasses import dataclass

from cloudcr_backup.repository.conexion import Conexion

TABLAS = (
    "PARAMETRO",
    "BD_REGISTRADA",
    "PERFIL_BD",
    "ESTRATEGIA",
    "ESTRATEGIA_OBJETO",
    "TAREA",
    "PROGRAMACION",
    "SCRIPT_RMAN",
    "EJECUCION",
    "EJECUCION_PIEZA",
    "VERIFICACION",
    "ALERTA",
)
TABLA_RECUPERACION = "RECUPERACION_PROCEDIMIENTO"
TABLAS_COMPLEMENTARIAS = (TABLA_RECUPERACION,)

OPCIONES_TABLA = "ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"

DDL_RECUPERACION = f"""
    CREATE TABLE IF NOT EXISTS recuperacion_procedimiento (
      id             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      bd_id          BIGINT NOT NULL,
      escenario      VARCHAR(30) NOT NULL,
      objetivo       VARCHAR(400),
      ruta_script    VARCHAR(1000) NOT NULL,
      contenido      LONGTEXT NOT NULL,
      hash_sha256    VARCHAR(64) NOT NULL,
      estado         VARCHAR(15) NOT NULL DEFAULT 'BORRADOR',
      generado_en    DATETIME(6) NOT NULL,
      aprobado_por   VARCHAR(100),
      aprobado_en    DATETIME(6),
      ejecutado_en   DATETIME(6),
      finalizado_en  DATETIME(6),
      resultado      VARCHAR(30),
      ruta_log       VARCHAR(1000),
      mensaje        VARCHAR(4000),
      CONSTRAINT fk_recuperacion_proc_bd FOREIGN KEY (bd_id) REFERENCES bd_registrada (id),
      CONSTRAINT ck_recuperacion_proc_estado CHECK (estado IN ('BORRADOR', 'APROBADO', 'RECHAZADO', 'OBSOLETO')),
      CONSTRAINT ck_recuperacion_proc_resultado CHECK (resultado IS NULL OR resultado IN
        ('EN_CURSO', 'EJECUTADO_OK', 'EJECUTADO_CON_ERRORES', 'NO_LANZADO'))
    ) {OPCIONES_TABLA}
"""

_DDL: tuple[str, ...] = (
    f"""
    CREATE TABLE parametro (
      clave   VARCHAR(100) NOT NULL,
      valor   VARCHAR(4000) NOT NULL,
      CONSTRAINT pk_parametro PRIMARY KEY (clave)
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE bd_registrada (
      id            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      nombre        VARCHAR(30) NOT NULL,
      oracle_home   VARCHAR(400) NOT NULL,
      ambiente      VARCHAR(20) NOT NULL,
      activa        CHAR(1) NOT NULL DEFAULT 'S',
      creada_en     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      CONSTRAINT uq_bd_registrada_nombre UNIQUE (nombre),
      CONSTRAINT ck_bd_registrada_ambiente CHECK (ambiente IN ('PRODUCCION', 'PRUEBAS', 'DESARROLLO')),
      CONSTRAINT ck_bd_registrada_activa CHECK (activa IN ('S', 'N'))
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE perfil_bd (
      id              BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      bd_id           BIGINT NOT NULL,
      log_mode        VARCHAR(20) NOT NULL,
      contenido_json  LONGTEXT NOT NULL,
      capturado_en    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      CONSTRAINT fk_perfil_bd_bd FOREIGN KEY (bd_id) REFERENCES bd_registrada (id),
      CONSTRAINT ck_perfil_bd_log_mode CHECK (log_mode IN ('ARCHIVELOG', 'NOARCHIVELOG'))
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE estrategia (
      id                          BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      bd_id                       BIGINT NOT NULL,
      codigo                      VARCHAR(20) NOT NULL,
      nombre                      VARCHAR(200) NOT NULL,
      descripcion                 VARCHAR(1000),
      prioridad                   VARCHAR(10) NOT NULL,
      estado                      VARCHAR(10) NOT NULL,
      version                     INT NOT NULL DEFAULT 1,
      creada_por                  VARCHAR(100) NOT NULL,
      creada_en                   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      retencion_ventana_dias      INT,
      retencion_redundancia       INT,
      retencion_archivelog_dias   INT,
      retencion_purga_automatica  CHAR(1) NOT NULL DEFAULT 'N',
      CONSTRAINT fk_estrategia_bd FOREIGN KEY (bd_id) REFERENCES bd_registrada (id),
      CONSTRAINT uq_estrategia_bd_codigo UNIQUE (bd_id, codigo),
      CONSTRAINT ck_estrategia_prioridad CHECK (prioridad IN ('ALTA', 'MEDIA', 'BAJA')),
      CONSTRAINT ck_estrategia_estado CHECK (estado IN ('ACTIVA', 'INACTIVA')),
      CONSTRAINT ck_estrategia_purga CHECK (retencion_purga_automatica IN ('S', 'N')),
      CONSTRAINT ck_estrategia_retencion CHECK (
        retencion_ventana_dias IS NULL OR retencion_redundancia IS NULL
      )
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE estrategia_objeto (
      id             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      estrategia_id  BIGINT NOT NULL,
      tipo_objeto    VARCHAR(20) NOT NULL,
      identificador  VARCHAR(200),
      prioridad      VARCHAR(10) NOT NULL,
      CONSTRAINT fk_estrategia_objeto_est FOREIGN KEY (estrategia_id) REFERENCES estrategia (id),
      CONSTRAINT ck_estrategia_objeto_tipo CHECK (tipo_objeto IN
        ('BASE_DATOS', 'PDB', 'TABLESPACE', 'DATAFILE', 'CONTROLFILE', 'SPFILE', 'ARCHIVELOG')),
      CONSTRAINT ck_estrategia_objeto_prioridad CHECK (prioridad IN ('ALTA', 'MEDIA', 'BAJA'))
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE tarea (
      id                    BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      estrategia_id         BIGINT NOT NULL,
      codigo                VARCHAR(10) NOT NULL,
      tipo_respaldo         VARCHAR(30) NOT NULL,
      modo_respaldo         VARCHAR(15) NOT NULL,
      compresion            VARCHAR(10) NOT NULL DEFAULT 'NINGUNA',
      canales               INT NOT NULL DEFAULT 1,
      destino_ruta          VARCHAR(400) NOT NULL,
      destino_etiqueta      VARCHAR(100),
      omitir_solo_lectura   CHAR(1) NOT NULL DEFAULT 'N',
      CONSTRAINT fk_tarea_estrategia FOREIGN KEY (estrategia_id) REFERENCES estrategia (id),
      CONSTRAINT uq_tarea_codigo UNIQUE (estrategia_id, codigo),
      CONSTRAINT ck_tarea_tipo CHECK (tipo_respaldo IN
        ('COMPLETO', 'INCREMENTAL_N0', 'INCREMENTAL_N1_DIFERENCIAL', 'INCREMENTAL_N1_ACUMULATIVO', 'ARCHIVELOG')),
      CONSTRAINT ck_tarea_modo CHECK (modo_respaldo IN ('AUTO', 'EN_LINEA', 'CONSISTENTE')),
      CONSTRAINT ck_tarea_compresion CHECK (compresion IN ('NINGUNA', 'BASIC', 'LOW', 'MEDIUM', 'HIGH')),
      CONSTRAINT ck_tarea_omitir CHECK (omitir_solo_lectura IN ('S', 'N'))
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE programacion (
      id                  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      tarea_id            BIGINT NOT NULL,
      tipo_frecuencia     VARCHAR(15) NOT NULL,
      horas               VARCHAR(200),
      dias_semana         VARCHAR(50),
      intervalo_minutos   INT,
      fecha_inicio        DATE,
      ventana_inicio      VARCHAR(5),
      ventana_fin         VARCHAR(5),
      zona_horaria        VARCHAR(60) NOT NULL DEFAULT 'America/Costa_Rica',
      politica_omision    VARCHAR(25) NOT NULL DEFAULT 'EJECUTAR_EN_VENTANA',
      CONSTRAINT fk_programacion_tarea FOREIGN KEY (tarea_id) REFERENCES tarea (id),
      CONSTRAINT uq_programacion_tarea UNIQUE (tarea_id),
      CONSTRAINT ck_programacion_frecuencia CHECK (tipo_frecuencia IN
        ('UNA_VEZ', 'INTERVALO', 'DIARIA', 'SEMANAL', 'MENSUAL')),
      CONSTRAINT ck_programacion_omision CHECK (politica_omision IN
        ('EJECUTAR_EN_VENTANA', 'OMITIR', 'EJECUTAR_SIEMPRE'))
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE script_rman (
      id             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      tarea_id       BIGINT NOT NULL,
      version        INT NOT NULL,
      contenido      LONGTEXT NOT NULL,
      hash_sha256    VARCHAR(64) NOT NULL,
      estado         VARCHAR(15) NOT NULL DEFAULT 'BORRADOR',
      aprobado_por   VARCHAR(100),
      aprobado_en    DATETIME(6),
      acepto_caida   CHAR(1) NOT NULL DEFAULT 'N',
      motivo_rechazo VARCHAR(1000),
      creado_en      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      CONSTRAINT fk_script_rman_tarea FOREIGN KEY (tarea_id) REFERENCES tarea (id),
      CONSTRAINT uq_script_tarea_version UNIQUE (tarea_id, version),
      CONSTRAINT ck_script_rman_estado CHECK (estado IN ('BORRADOR', 'APROBADO', 'RECHAZADO', 'OBSOLETO')),
      CONSTRAINT ck_script_rman_acepto CHECK (acepto_caida IN ('S', 'N'))
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE ejecucion (
      id                  BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      tarea_id            BIGINT NOT NULL,
      script_id           BIGINT NOT NULL,
      bd_id               BIGINT NOT NULL,
      programada_para     DATETIME(6) NOT NULL,
      inicio              DATETIME(6),
      fin                 DATETIME(6),
      estado              VARCHAR(20) NOT NULL DEFAULT 'PROGRAMADA',
      tipo_respaldo       VARCHAR(30) NOT NULL,
      agente              VARCHAR(64),
      ubicacion           VARCHAR(400),
      archivos_generados  INT,
      tamano_bytes        BIGINT,
      duracion_segundos   BIGINT,
      mensaje_rman        VARCHAR(4000),
      errores             LONGTEXT,
      advertencias        LONGTEXT,
      estado_prueba       VARCHAR(15) NOT NULL DEFAULT 'PENDIENTE',
      CONSTRAINT fk_ejecucion_tarea FOREIGN KEY (tarea_id) REFERENCES tarea (id),
      CONSTRAINT fk_ejecucion_script FOREIGN KEY (script_id) REFERENCES script_rman (id),
      CONSTRAINT fk_ejecucion_bd FOREIGN KEY (bd_id) REFERENCES bd_registrada (id),
      CONSTRAINT uq_ejecucion_tarea_hora UNIQUE (tarea_id, programada_para),
      CONSTRAINT ck_ejecucion_estado CHECK (estado IN
        ('PROGRAMADA', 'EN_CURSO', 'EXITOSA', 'CON_ADVERTENCIAS', 'FALLIDA', 'NO_EJECUTADA', 'BLOQUEADA', 'CANCELADA')),
      CONSTRAINT ck_ejecucion_prueba CHECK (estado_prueba IN ('PENDIENTE', 'OK', 'FALLIDA', 'NO_APLICA')),
      INDEX ix_ejecucion_estado (estado, programada_para)
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE ejecucion_pieza (
      id              BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      ejecucion_id    BIGINT NOT NULL,
      nombre_archivo  VARCHAR(400) NOT NULL,
      tamano_bytes    BIGINT,
      tag             VARCHAR(30),
      vence_en        DATETIME(6),
      obsoleta        CHAR(1) NOT NULL DEFAULT 'N',
      CONSTRAINT fk_ejecucion_pieza_ejec FOREIGN KEY (ejecucion_id) REFERENCES ejecucion (id),
      CONSTRAINT ck_ejecucion_pieza_obsoleta CHECK (obsoleta IN ('S', 'N'))
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE verificacion (
      id            BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      ejecucion_id  BIGINT NOT NULL,
      tipo_prueba   VARCHAR(30) NOT NULL,
      resultado     VARCHAR(15) NOT NULL,
      detalle       LONGTEXT,
      ejecutada_en  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      CONSTRAINT fk_verificacion_ejec FOREIGN KEY (ejecucion_id) REFERENCES ejecucion (id),
      CONSTRAINT ck_verificacion_resultado CHECK (resultado IN ('PENDIENTE', 'OK', 'FALLIDA', 'NO_APLICA'))
    ) {OPCIONES_TABLA}
    """,
    f"""
    CREATE TABLE alerta (
      id             BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      codigo         VARCHAR(40) NOT NULL,
      clave_dedup    VARCHAR(200) NOT NULL,
      severidad      VARCHAR(15) NOT NULL,
      estado         VARCHAR(15) NOT NULL DEFAULT 'ABIERTA',
      mensaje        VARCHAR(2000) NOT NULL,
      bd_id          BIGINT,
      estrategia_id  BIGINT,
      tarea_id       BIGINT,
      ejecucion_id   BIGINT,
      abierta_en     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      resuelta_en    DATETIME(6),
      CONSTRAINT fk_alerta_bd FOREIGN KEY (bd_id) REFERENCES bd_registrada (id),
      CONSTRAINT fk_alerta_estrategia FOREIGN KEY (estrategia_id) REFERENCES estrategia (id),
      CONSTRAINT fk_alerta_tarea FOREIGN KEY (tarea_id) REFERENCES tarea (id),
      CONSTRAINT fk_alerta_ejecucion FOREIGN KEY (ejecucion_id) REFERENCES ejecucion (id),
      CONSTRAINT ck_alerta_estado CHECK (estado IN ('ABIERTA', 'RECONOCIDA', 'RESUELTA')),
      INDEX ix_alerta_abierta (estado, clave_dedup)
    ) {OPCIONES_TABLA}
    """,
)


@dataclass(frozen=True)
class EstadoEsquema:
    instalado: bool
    tablas: dict[str, int]


def _eliminar_tablas(conexion: Conexion) -> None:
    cursor = conexion.cursor()
    try:
        for tabla in (*TABLAS_COMPLEMENTARIAS, *reversed(TABLAS)):
            cursor.execute(f"DROP TABLE IF EXISTS {tabla.lower()}")
        conexion.commit()
    finally:
        cursor.close()


def instalar(conexion: Conexion) -> None:
    _eliminar_tablas(conexion)
    cursor = conexion.cursor()
    try:
        for sentencia in (*_DDL, DDL_RECUPERACION):
            cursor.execute(sentencia)
        conexion.commit()
    finally:
        cursor.close()


def desinstalar(conexion: Conexion) -> None:
    _eliminar_tablas(conexion)


def estado(conexion: Conexion) -> EstadoEsquema:
    cursor = conexion.cursor()
    try:
        cursor.execute(
            "SELECT UPPER(table_name) FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND UPPER(table_name) IN ({})".format(
                ",".join(f"'{t}'" for t in TABLAS)
            )
        )
        instaladas = {fila[0] for fila in cursor.fetchall()}
        if not instaladas:
            return EstadoEsquema(instalado=False, tablas={})
        conteos: dict[str, int] = {}
        for tabla in TABLAS:
            if tabla in instaladas:
                cursor.execute(f"SELECT COUNT(*) FROM {tabla.lower()}")
                conteos[tabla] = int(cursor.fetchone()[0])
        return EstadoEsquema(instalado=len(instaladas) == len(TABLAS), tablas=conteos)
    finally:
        cursor.close()
