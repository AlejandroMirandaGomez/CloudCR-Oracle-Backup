ACCEPT usuario_monitor PROMPT 'Usuario común de monitoreo (ej. C##BKP_MON): '
ACCEPT clave_monitor PROMPT 'Clave del usuario de monitoreo: ' HIDE

CREATE USER &usuario_monitor IDENTIFIED BY &clave_monitor CONTAINER = ALL;

GRANT CREATE SESSION TO &usuario_monitor CONTAINER = ALL;
GRANT SELECT_CATALOG_ROLE TO &usuario_monitor CONTAINER = ALL;
ALTER USER &usuario_monitor SET CONTAINER_DATA = ALL CONTAINER = CURRENT;

UNDEFINE usuario_monitor
UNDEFINE clave_monitor
