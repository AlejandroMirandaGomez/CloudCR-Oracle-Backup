ACCEPT nombre_pdb PROMPT 'Nombre de la PDB del repositorio (ej. BKPCAT): '
ACCEPT usuario_repo PROMPT 'Usuario del repositorio (ej. BKP_ADMIN): '
ACCEPT clave_repo PROMPT 'Clave del usuario del repositorio: ' HIDE
ACCEPT cuota_mb PROMPT 'Cuota en MB sobre USERS (ej. 500): '

ALTER SESSION SET CONTAINER = &nombre_pdb;

DECLARE
  v_existe       NUMBER;
  v_ruta_sistema VARCHAR2(400);
  v_ruta_users   VARCHAR2(400);
BEGIN
  SELECT COUNT(*) INTO v_existe FROM dba_tablespaces WHERE tablespace_name = 'USERS';
  IF v_existe = 0 THEN
    SELECT file_name INTO v_ruta_sistema FROM dba_data_files WHERE tablespace_name = 'SYSTEM' AND ROWNUM = 1;
    v_ruta_users := REGEXP_REPLACE(v_ruta_sistema, 'SYSTEM01\.DBF$', 'USERS01.DBF', 1, 1, 'i');
    EXECUTE IMMEDIATE
      'CREATE TABLESPACE users DATAFILE ''' || v_ruta_users ||
      ''' SIZE 500M AUTOEXTEND ON NEXT 100M MAXSIZE UNLIMITED';
  END IF;
END;
/

CREATE USER &usuario_repo IDENTIFIED BY &clave_repo
  DEFAULT TABLESPACE users
  QUOTA &cuota_mb.M ON users;

GRANT CREATE SESSION TO &usuario_repo;
GRANT CREATE TABLE TO &usuario_repo;
GRANT CREATE SEQUENCE TO &usuario_repo;
GRANT CREATE VIEW TO &usuario_repo;

UNDEFINE nombre_pdb
UNDEFINE usuario_repo
UNDEFINE clave_repo
UNDEFINE cuota_mb
