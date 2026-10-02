from cloudcr_backup.domain.perfil_bd import ContenedorInfo


def identificador_tablespace(contenedor: ContenedorInfo, nombre_tablespace: str) -> str:
    if contenedor.es_raiz:
        return nombre_tablespace
    return f"{contenedor.nombre}:{nombre_tablespace}"
