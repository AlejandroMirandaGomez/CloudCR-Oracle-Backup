ACCEPT nombre_pdb PROMPT 'Nombre de la PDB de pruebas (ej. XEPDB1): '
ACCEPT usuario_demo PROMPT 'Usuario del esquema de demostracion (ej. CLOUDCR_DEMO): '

ALTER SESSION SET CONTAINER = &nombre_pdb;
ALTER SESSION SET CURRENT_SCHEMA = &usuario_demo;

INSERT INTO ventas (fecha, cliente, producto, monto)
SELECT SYSDATE, 'Cliente actividad', 'Producto actividad', ROUND(DBMS_RANDOM.VALUE(10, 5000), 2)
FROM dual CONNECT BY LEVEL <= 200;
COMMIT;

ALTER SESSION SET CONTAINER = CDB$ROOT;
ALTER SYSTEM SWITCH LOGFILE;

ALTER SESSION SET CONTAINER = &nombre_pdb;
ALTER SESSION SET CURRENT_SCHEMA = &usuario_demo;

INSERT INTO finanzas (fecha, cuenta, tipo, monto)
SELECT SYSDATE, 'Cuenta actividad', CASE MOD(ROWNUM, 2) WHEN 0 THEN 'INGRESO' ELSE 'EGRESO' END,
  ROUND(DBMS_RANDOM.VALUE(100, 20000), 2)
FROM dual CONNECT BY LEVEL <= 200;
COMMIT;

UPDATE inventario SET cantidad = cantidad + TRUNC(DBMS_RANDOM.VALUE(1, 50)), actualizado_en = SYSDATE
WHERE MOD(id, 10) = 0;
COMMIT;

ALTER SESSION SET CONTAINER = CDB$ROOT;
ALTER SYSTEM SWITCH LOGFILE;

ALTER SESSION SET CONTAINER = &nombre_pdb;
ALTER SESSION SET CURRENT_SCHEMA = &usuario_demo;

INSERT INTO ventas (fecha, cliente, producto, monto)
SELECT SYSDATE, 'Cliente actividad 2', 'Producto actividad 2', ROUND(DBMS_RANDOM.VALUE(10, 5000), 2)
FROM dual CONNECT BY LEVEL <= 200;
COMMIT;

ALTER SESSION SET CONTAINER = CDB$ROOT;
ALTER SYSTEM SWITCH LOGFILE;

COLUMN name FORMAT A70
SELECT name, sequence#, status FROM v$archived_log ORDER BY sequence# DESC FETCH FIRST 5 ROWS ONLY;

UNDEFINE nombre_pdb
UNDEFINE usuario_demo
