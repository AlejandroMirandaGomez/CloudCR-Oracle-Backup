ACCEPT nombre_pdb PROMPT 'Nombre de la PDB del repositorio (ej. BKPCAT): '
ACCEPT usuario_repo PROMPT 'Usuario del repositorio (ej. BKP_ADMIN): '
ACCEPT clave_repo PROMPT 'Clave del usuario del repositorio: ' HIDE
ACCEPT cuota_mb PROMPT 'Cuota en MB sobre USERS (ej. 500): '

ALTER SESSION SET CONTAINER = &nombre_pdb;

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
