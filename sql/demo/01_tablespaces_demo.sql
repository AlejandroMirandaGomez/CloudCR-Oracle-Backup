ACCEPT nombre_pdb PROMPT 'Nombre de la PDB de pruebas (ej. XEPDB1): '
ACCEPT usuario_demo PROMPT 'Usuario del esquema de demostracion (ej. CLOUDCR_DEMO): '
ACCEPT clave_demo PROMPT 'Clave del usuario de demostracion: ' HIDE
ACCEPT directorio_datos PROMPT 'Directorio donde crear los datafiles (ej. C:\app\...\oradata\XE\XEPDB1): '

ALTER SESSION SET CONTAINER = &nombre_pdb;

WHENEVER SQLERROR CONTINUE

DROP USER &usuario_demo CASCADE;

BEGIN
  FOR t IN (
    SELECT tablespace_name FROM dba_tablespaces
    WHERE tablespace_name IN ('VENTAS', 'FINANZAS', 'INVENTARIO', 'RRHH', 'IDX_VENTAS', 'IDX_FINANZAS')
  ) LOOP
    EXECUTE IMMEDIATE 'DROP TABLESPACE ' || t.tablespace_name || ' INCLUDING CONTENTS AND DATAFILES';
  END LOOP;
END;
/

WHENEVER SQLERROR EXIT SQL.SQLCODE

CREATE TABLESPACE ventas
  DATAFILE '&directorio_datos\VENTAS01.DBF' SIZE 50M AUTOEXTEND ON NEXT 10M MAXSIZE 500M;

CREATE TABLESPACE finanzas
  DATAFILE '&directorio_datos\FINANZAS01.DBF' SIZE 50M AUTOEXTEND ON NEXT 10M MAXSIZE 500M;

CREATE TABLESPACE inventario
  DATAFILE '&directorio_datos\INVENTARIO01.DBF' SIZE 30M AUTOEXTEND ON NEXT 10M MAXSIZE 300M;

CREATE TABLESPACE rrhh
  DATAFILE '&directorio_datos\RRHH01.DBF' SIZE 20M AUTOEXTEND ON NEXT 10M MAXSIZE 200M;

CREATE TABLESPACE idx_ventas
  DATAFILE '&directorio_datos\IDX_VENTAS01.DBF' SIZE 20M AUTOEXTEND ON NEXT 10M MAXSIZE 200M;

CREATE TABLESPACE idx_finanzas
  DATAFILE '&directorio_datos\IDX_FINANZAS01.DBF' SIZE 20M AUTOEXTEND ON NEXT 10M MAXSIZE 200M;

CREATE USER &usuario_demo IDENTIFIED BY &clave_demo
  DEFAULT TABLESPACE ventas
  QUOTA UNLIMITED ON ventas
  QUOTA UNLIMITED ON finanzas
  QUOTA UNLIMITED ON inventario
  QUOTA UNLIMITED ON rrhh
  QUOTA UNLIMITED ON idx_ventas
  QUOTA UNLIMITED ON idx_finanzas;

GRANT CREATE SESSION TO &usuario_demo;
GRANT CREATE TABLE TO &usuario_demo;

COLUMN tablespace_name FORMAT A15
COLUMN contents FORMAT A12
COLUMN status FORMAT A10
SELECT tablespace_name, contents, status FROM dba_tablespaces
WHERE tablespace_name IN ('VENTAS', 'FINANZAS', 'INVENTARIO', 'RRHH', 'IDX_VENTAS', 'IDX_FINANZAS')
ORDER BY tablespace_name;

UNDEFINE nombre_pdb
UNDEFINE usuario_demo
UNDEFINE clave_demo
UNDEFINE directorio_datos
