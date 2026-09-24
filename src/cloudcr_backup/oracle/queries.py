BASE_DATOS = """
SELECT name, dbid, log_mode, open_mode, cdb
FROM v$database
"""

INSTANCIA = "SELECT * FROM v$instance"

CONTENEDORES = """
SELECT con_id, name, open_mode
FROM v$containers
ORDER BY con_id
"""

TABLESPACES = """
SELECT t.con_id, t.name, t.bigfile, ct.contents, ct.status
FROM v$tablespace t
LEFT JOIN cdb_tablespaces ct ON ct.con_id = t.con_id AND ct.tablespace_name = t.name
ORDER BY t.con_id, t.name
"""

DATAFILES = """
SELECT d.file#, d.con_id, t.name, d.name, d.bytes, d.status, f.autoextensible, f.maxbytes, fs.libres
FROM v$datafile d
JOIN v$tablespace t ON t.ts# = d.ts# AND t.con_id = d.con_id
LEFT JOIN cdb_data_files f ON f.file_id = d.file# AND f.con_id = d.con_id
LEFT JOIN (
    SELECT con_id, file_id, SUM(bytes) AS libres
    FROM cdb_free_space
    GROUP BY con_id, file_id
) fs ON fs.file_id = d.file# AND fs.con_id = d.con_id
ORDER BY d.con_id, t.name, d.file#
"""

TEMPFILES = """
SELECT tf.file#, tf.con_id, t.name, tf.name, tf.bytes, tf.status
FROM v$tempfile tf
JOIN v$tablespace t ON t.ts# = tf.ts# AND t.con_id = tf.con_id
ORDER BY tf.con_id, t.name, tf.file#
"""

CONTROLFILES = """
SELECT name, status, block_size * file_size_blks AS bytes
FROM v$controlfile
"""

REDO_GRUPOS = """
SELECT group#, thread#, sequence#, bytes, status, archived
FROM v$log
ORDER BY group#
"""

REDO_MIEMBROS = """
SELECT group#, member, status, type
FROM v$logfile
ORDER BY group#, member
"""

PARAMETROS = """
SELECT name, value
FROM v$parameter
WHERE name IN ('spfile', 'diagnostic_dest', 'log_archive_dest', 'log_archive_dest_1', 'db_recovery_file_dest')
"""

DESTINOS_ARCHIVADO = """
SELECT dest_name, destination, status
FROM v$archive_dest
WHERE destination IS NOT NULL AND status <> 'INACTIVE'
ORDER BY dest_id
"""

AREA_RECUPERACION = """
SELECT name, space_limit, space_used
FROM v$recovery_file_dest
WHERE name IS NOT NULL
"""

ARCHIVELOGS_SIN_RESPALDO = """
SELECT COUNT(*)
FROM v$archived_log
WHERE deleted = 'NO' AND archived = 'YES' AND backup_count = 0
"""
