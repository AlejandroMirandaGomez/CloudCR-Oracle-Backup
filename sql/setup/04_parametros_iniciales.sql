MERGE INTO parametro p USING (SELECT 'agente.tick_segundos' clave, '30' valor FROM dual) d
  ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (SELECT 'agente.gracia_omision_min' clave, '15' valor FROM dual) d
  ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (SELECT 'rman.nls_lang' clave, 'AMERICAN_AMERICA.AL32UTF8' valor FROM dual) d
  ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (SELECT 'rman.timeout_max_min' clave, '120' valor FROM dual) d
  ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (
  SELECT 'rman.codigos_advertencia' clave,
    '["RMAN-08137","RMAN-08138","RMAN-06207","RMAN-06208","RMAN-06214"]' valor
  FROM dual
) d ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (
  SELECT 'respaldo.formato_pieza' clave, '%d_{estrategia}_{tarea}_%T_%U.bkp' valor FROM dual
) d ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (SELECT 'verificacion.automatica' clave, 'true' valor FROM dual) d
  ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (SELECT 'alertas.eval_minutos' clave, '5' valor FROM dual) d
  ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (SELECT 'alertas.disco_uso_pct' clave, '85' valor FROM dual) d
  ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (
  SELECT 'alertas.recencia_horas.ALTA' clave, '24' valor FROM dual
) d ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (
  SELECT 'alertas.recencia_horas.MEDIA' clave, '72' valor FROM dual
) d ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (
  SELECT 'alertas.recencia_horas.BAJA' clave, '192' valor FROM dual
) d ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

MERGE INTO parametro p USING (SELECT 'notificacion.canales' clave, '["consola"]' valor FROM dual) d
  ON (p.clave = d.clave) WHEN NOT MATCHED THEN INSERT (clave, valor) VALUES (d.clave, d.valor);

COMMIT;
