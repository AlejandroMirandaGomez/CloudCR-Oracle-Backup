ACCEPT nombre_pdb PROMPT 'Nombre de la PDB del repositorio (ej. BKPCAT): '
ACCEPT admin_pdb PROMPT 'Usuario administrador inicial de la PDB (ej. PDB_ADMIN): '
ACCEPT clave_admin_pdb PROMPT 'Clave del administrador inicial de la PDB: ' HIDE

CREATE PLUGGABLE DATABASE &nombre_pdb
  ADMIN USER &admin_pdb IDENTIFIED BY &clave_admin_pdb
  FILE_NAME_CONVERT = ('pdbseed', '&nombre_pdb');

ALTER PLUGGABLE DATABASE &nombre_pdb OPEN;
ALTER PLUGGABLE DATABASE &nombre_pdb SAVE STATE;

COLUMN name FORMAT A20
COLUMN open_mode FORMAT A15
SELECT name, open_mode FROM v$pdbs WHERE name = UPPER('&nombre_pdb');

UNDEFINE nombre_pdb
UNDEFINE admin_pdb
UNDEFINE clave_admin_pdb
