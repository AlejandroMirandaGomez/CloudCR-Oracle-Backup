(function () {
  "use strict";

  const pagina = document.getElementById("pagina-estrategia");
  if (!pagina) {
    return;
  }

  const datos = JSON.parse(document.getElementById("datos-estrategia").textContent);
  const catalogo = datos.catalogo;
  const sid = pagina.dataset.sid;
  const oracleHome = pagina.dataset.oracleHome || "";
  const TOTAL_PASOS = 5;
  const FRECUENCIAS_CON_HORAS = ["UNA_VEZ", "DIARIA", "SEMANAL", "MENSUAL"];
  const PASO_POR_CAMPO = {
    codigo: 1,
    nombre: 1,
    descripcion: 1,
    prioridad: 1,
    creada_por: 1,
    alcance: 2,
    esquema: 3,
    tareas: 3,
    destino_ruta: 4,
    retencion: 4,
  };
  const ROTULOS_DEL_ESQUEMA = [
    { id: "rotulo-esq-dia-n0", atributo: "rotuloDia" },
    { id: "rotulo-esq-hora-n0", atributo: "rotuloHoraPrincipal" },
    { id: "rotulo-esq-hora-n1", atributo: "rotuloHoraN1" },
  ];
  const HORA_POR_DEFECTO = "02:00";
  const PATRON_CODIGO = /^[A-Z0-9_-]{1,20}$/;
  const PATRON_RUTA_ABSOLUTA = /^([A-Za-z]:[\\/]|\\\\|\/)/;

  const estado = {
    paso: 1,
    pasosAprobados: new Set(),
    seleccion: new Set(),
    prioridadesPorObjeto: new Map(),
    esquemaTocado: false,
    validacion: null,
    numeroValidacion: 0,
    guardando: false,
    guardada: false,
  };

  const paneles = Array.from(document.querySelectorAll(".paso[data-paso]"));
  const botonesPaso = Array.from(document.querySelectorAll("[data-ir-paso]"));
  const botonAnterior = document.getElementById("boton-anterior");
  const botonSiguiente = document.getElementById("boton-siguiente");
  const botonValidar = document.getElementById("boton-validar");
  const botonGuardar = document.getElementById("boton-guardar");
  const avisos = document.getElementById("avisos-formulario");

  function porId(id) {
    return document.getElementById(id);
  }

  function todos(selector, contexto) {
    return Array.from((contexto || document).querySelectorAll(selector));
  }

  function crear(etiqueta, atributos, hijos) {
    const nodo = document.createElement(etiqueta);
    Object.keys(atributos || {}).forEach(function (clave) {
      const valor = atributos[clave];
      if (clave === "texto") {
        nodo.textContent = valor;
      } else if (clave === "clase") {
        nodo.className = valor;
      } else if (valor !== null && valor !== undefined && valor !== false) {
        nodo.setAttribute(clave, valor === true ? "" : valor);
      }
    });
    (hijos || []).forEach(function (hijo) {
      if (hijo) {
        nodo.appendChild(typeof hijo === "string" ? document.createTextNode(hijo) : hijo);
      }
    });
    return nodo;
  }

  function vaciar(nodo) {
    while (nodo.firstChild) {
      nodo.removeChild(nodo.firstChild);
    }
  }

  function valorDe(id) {
    return porId(id).value.trim();
  }

  function radioSeleccionado(nombre) {
    const marcado = document.querySelector('input[name="' + nombre + '"]:checked');
    return marcado ? marcado.value : "";
  }

  function entero(texto) {
    return /^\d+$/.test(texto) ? parseInt(texto, 10) : NaN;
  }

  function rutaApi(ruta) {
    if (!oracleHome) {
      return ruta;
    }
    return ruta + (ruta.indexOf("?") === -1 ? "?" : "&") + "oracle_home=" + encodeURIComponent(oracleHome);
  }

  async function llamarApi(ruta, metodo, cuerpo) {
    const opciones = { method: metodo, headers: { Accept: "application/json" }, credentials: "same-origin" };
    if (cuerpo !== undefined) {
      opciones.headers["Content-Type"] = "application/json";
      opciones.body = JSON.stringify(cuerpo);
    }
    let respuesta;
    try {
      respuesta = await fetch(ruta, opciones);
    } catch (error) {
      throw { estado: 0, errores: [{ campo: "", mensaje: "No se pudo comunicar con el servidor de CloudCR." }], datos: null };
    }
    let contenido = null;
    try {
      contenido = await respuesta.json();
    } catch (error) {
      contenido = null;
    }
    if (!respuesta.ok) {
      const errores =
        contenido && Array.isArray(contenido.errores) && contenido.errores.length
          ? contenido.errores
          : [{ campo: "", mensaje: "El servidor respondió con el error " + respuesta.status + "." }];
      throw { estado: respuesta.status, errores: errores, datos: contenido };
    }
    return contenido;
  }

  function limpiarErrores() {
    todos(".error-campo[data-error-de], [data-error-tarea]").forEach(function (nodo) {
      nodo.hidden = true;
      nodo.textContent = "";
    });
    todos(".invalido").forEach(function (nodo) {
      nodo.classList.remove("invalido");
    });
    avisos.hidden = true;
    vaciar(avisos);
  }

  function marcarInvalido(nombreCampo, mensaje) {
    const lugar = document.querySelector('.error-campo[data-error-de="' + nombreCampo + '"]');
    if (!lugar) {
      return false;
    }
    lugar.textContent = mensaje;
    lugar.hidden = false;
    const contenedor = lugar.closest("label, fieldset, section");
    const entrada = contenedor ? contenedor.querySelector("input, select, textarea") : null;
    if (entrada && entrada.type !== "radio" && entrada.type !== "checkbox") {
      entrada.classList.add("invalido");
    }
    return true;
  }

  function mostrarAvisos(mensajes) {
    vaciar(avisos);
    avisos.appendChild(crear("strong", { texto: "Revise lo siguiente:" }));
    avisos.appendChild(
      crear(
        "ul",
        {},
        mensajes.map(function (mensaje) {
          return crear("li", { texto: mensaje });
        })
      )
    );
    avisos.hidden = false;
  }

  function reunir(errores) {
    return errores.map(function (error) {
      return error.mensaje;
    });
  }

  function prioridadEstrategia() {
    return radioSeleccionado("prioridad") || "ALTA";
  }

  function casillasAlcance() {
    return todos(".casilla-alcance");
  }

  const casillasPorNodo = new Map();

  function cubiertaPor(casilla) {
    return (casilla.dataset.cubiertaPor || "").split(" ").filter(Boolean);
  }

  function hayDescendienteSeleccionado(idNodo) {
    return Array.from(estado.seleccion).some(function (otro) {
      const casilla = casillasPorNodo.get(otro);
      return casilla ? cubiertaPor(casilla).indexOf(idNodo) !== -1 : false;
    });
  }

  function pintarSeleccion() {
    casillasAlcance().forEach(function (casilla) {
      if (casilla.dataset.bloqueada === "1") {
        return;
      }
      const idNodo = casilla.dataset.nodo;
      const cubierto = cubiertaPor(casilla).some(function (ancestro) {
        return estado.seleccion.has(ancestro);
      });
      casilla.checked = estado.seleccion.has(idNodo) || cubierto;
      casilla.disabled = cubierto;
      casilla.classList.toggle("cubierta", cubierto);
      casilla.indeterminate = !casilla.checked && hayDescendienteSeleccionado(idNodo);
    });
    renderizarResumenSeleccion();
  }

  function renderizarResumenSeleccion() {
    const lista = porId("lista-seleccion");
    vaciar(lista);
    const elegidas = casillasAlcance().filter(function (casilla) {
      return estado.seleccion.has(casilla.dataset.nodo);
    });
    porId("contador-seleccion").textContent = String(elegidas.length);
    porId("seleccion-vacia").hidden = elegidas.length > 0;
    elegidas.forEach(function (casilla) {
      const idNodo = casilla.dataset.nodo;
      const selector = crear("select", { "aria-label": "Prioridad de " + casilla.dataset.etiqueta });
      catalogo.prioridades.forEach(function (prioridad) {
        selector.appendChild(crear("option", { value: prioridad.valor, texto: prioridad.valor }));
      });
      selector.value = estado.prioridadesPorObjeto.get(idNodo) || prioridadEstrategia();
      selector.addEventListener("change", function () {
        estado.prioridadesPorObjeto.set(idNodo, selector.value);
      });
      const quitar = crear("button", {
        type: "button",
        clase: "boton boton-pequeno",
        texto: "Quitar",
        "aria-label": "Quitar " + casilla.dataset.etiqueta,
      });
      quitar.addEventListener("click", function () {
        estado.seleccion.delete(idNodo);
        pintarSeleccion();
      });
      lista.appendChild(
        crear("li", { clase: "item-seleccion" }, [
          crear("span", { clase: "item-seleccion-nombre", texto: casilla.dataset.etiqueta }),
          selector,
          quitar,
        ])
      );
    });
  }

  function inicializarSeleccion() {
    casillasAlcance().forEach(function (casilla) {
      casilla.dataset.bloqueada = casilla.disabled ? "1" : "0";
      casillasPorNodo.set(casilla.dataset.nodo, casilla);
    });
    const arbol = porId("arbol");
    arbol.addEventListener("change", function (evento) {
      const casilla = evento.target;
      if (!(casilla instanceof HTMLInputElement) || !casilla.classList.contains("casilla-alcance")) {
        return;
      }
      const idNodo = casilla.dataset.nodo;
      if (casilla.checked) {
        estado.seleccion.add(idNodo);
        casillasAlcance().forEach(function (otra) {
          if (cubiertaPor(otra).indexOf(idNodo) !== -1) {
            estado.seleccion.delete(otra.dataset.nodo);
          }
        });
      } else {
        estado.seleccion.delete(idNodo);
      }
      pintarSeleccion();
    });
    pintarSeleccion();
  }

  function construirAlcance() {
    return casillasAlcance()
      .filter(function (casilla) {
        return estado.seleccion.has(casilla.dataset.nodo);
      })
      .map(function (casilla) {
        return {
          tipo: casilla.dataset.tipo,
          identificador: casilla.dataset.identificador,
          prioridad: estado.prioridadesPorObjeto.get(casilla.dataset.nodo) || prioridadEstrategia(),
        };
      });
  }

  function actualizarRotulosDelEsquema(elegido) {
    ROTULOS_DEL_ESQUEMA.forEach(function (rotulo) {
      const texto = elegido.dataset[rotulo.atributo];
      if (texto) {
        porId(rotulo.id).textContent = texto;
      }
    });
  }

  function actualizarEsquema() {
    const elegido = document.querySelector('input[name="esquema"]:checked');
    const usaN1 = elegido && elegido.dataset.usaN1 === "si";
    const usaArchivelog = elegido && elegido.dataset.usaArchivelog === "si";
    if (elegido) {
      actualizarRotulosDelEsquema(elegido);
    }
    todos("[data-solo-n1]").forEach(function (campo) {
      campo.hidden = !usaN1;
    });
    todos("[data-solo-archivelog]").forEach(function (campo) {
      campo.hidden = !usaArchivelog;
    });
  }

  function actualizarRecomendado() {
    const prioridad = catalogo.prioridades.find(function (p) {
      return p.valor === prioridadEstrategia();
    });
    const recomendado = prioridad ? prioridad.esquema_recomendado : "";
    todos("[data-recomendado-de]").forEach(function (insignia) {
      insignia.hidden = insignia.dataset.recomendadoDe !== recomendado;
    });
    if (!estado.esquemaTocado && recomendado) {
      const radio = document.querySelector('input[name="esquema"][value="' + recomendado + '"]');
      if (radio) {
        radio.checked = true;
        actualizarEsquema();
      }
    }
  }

  function llenarSelector(selector, elementos, clave, etiqueta, elegido) {
    vaciar(selector);
    elementos.forEach(function (elemento) {
      const valor = typeof elemento === "string" ? elemento : elemento[clave];
      const texto = typeof elemento === "string" ? elemento : elemento[etiqueta];
      selector.appendChild(crear("option", { value: valor, texto: texto }));
    });
    if (elegido !== undefined) {
      selector.value = elegido;
    }
  }

  function campoDe(tarea, nombre) {
    return tarea.querySelector('[data-campo="' + nombre + '"]');
  }

  function agregarFilaHora(tarea, valor) {
    const contenedor = tarea.querySelector("[data-lista-horas]");
    const entrada = crear("input", { type: "time", "aria-label": "Hora de ejecución", value: valor || HORA_POR_DEFECTO });
    const quitar = crear("button", { type: "button", clase: "boton boton-pequeno", texto: "×", "aria-label": "Quitar hora" });
    const fila = crear("span", { clase: "fila-hora" }, [entrada, quitar]);
    quitar.addEventListener("click", function () {
      if (contenedor.children.length > 1) {
        contenedor.removeChild(fila);
      }
    });
    contenedor.appendChild(fila);
  }

  function actualizarFrecuenciaDeTarea(tarea) {
    const frecuencia = campoDe(tarea, "tipo_frecuencia").value;
    todos("[data-visible-para]", tarea).forEach(function (bloque) {
      bloque.hidden = bloque.dataset.visiblePara.split(",").indexOf(frecuencia) === -1;
    });
    tarea.querySelector("[data-rotulo-fecha]").textContent =
      frecuencia === "MENSUAL" ? "Fecha de referencia (define el día del mes)" : "Fecha de ejecución";
  }

  function actualizarDescripcionesDeTarea(tarea) {
    const tipo = catalogo.tipos_respaldo.find(function (t) {
      return t.valor === campoDe(tarea, "tipo_respaldo").value;
    });
    const modo = catalogo.modos_respaldo.find(function (m) {
      return m.valor === campoDe(tarea, "modo_respaldo").value;
    });
    tarea.querySelector("[data-descripcion-tipo]").textContent = tipo ? tipo.significado : "";
    tarea.querySelector("[data-descripcion-modo]").textContent = modo ? modo.descripcion : "";
  }

  function renumerarTareas() {
    todos("#lista-tareas [data-tarea]").forEach(function (tarea, indice) {
      tarea.querySelector("[data-titulo-tarea]").textContent = "Tipo de respaldo T" + (indice + 1);
    });
  }

  function agregarTarea() {
    const tarea = porId("plantilla-tarea").content.firstElementChild.cloneNode(true);
    llenarSelector(campoDe(tarea, "tipo_respaldo"), catalogo.tipos_respaldo, "valor", "etiqueta", "COMPLETO");
    llenarSelector(campoDe(tarea, "modo_respaldo"), catalogo.modos_respaldo, "valor", "etiqueta", "AUTO");
    llenarSelector(campoDe(tarea, "compresion"), catalogo.compresiones, "", "", catalogo.compresiones[0]);
    llenarSelector(campoDe(tarea, "tipo_frecuencia"), catalogo.frecuencias, "valor", "etiqueta", "DIARIA");
    llenarSelector(campoDe(tarea, "politica_omision"), catalogo.politicas_omision, "valor", "etiqueta");
    campoDe(tarea, "zona_horaria").value = catalogo.zona_horaria;
    const dias = tarea.querySelector("[data-lista-dias]");
    catalogo.dias_semana.forEach(function (dia) {
      dias.appendChild(
        crear("label", { clase: "casilla" }, [crear("input", { type: "checkbox", value: dia.valor }), dia.etiqueta])
      );
    });
    agregarFilaHora(tarea, HORA_POR_DEFECTO);
    tarea.querySelector("[data-agregar-hora]").addEventListener("click", function () {
      agregarFilaHora(tarea, HORA_POR_DEFECTO);
    });
    tarea.querySelector("[data-quitar-tarea]").addEventListener("click", function () {
      tarea.parentElement.removeChild(tarea);
      renumerarTareas();
    });
    campoDe(tarea, "tipo_respaldo").addEventListener("change", function () {
      actualizarDescripcionesDeTarea(tarea);
    });
    campoDe(tarea, "modo_respaldo").addEventListener("change", function () {
      actualizarDescripcionesDeTarea(tarea);
    });
    campoDe(tarea, "tipo_frecuencia").addEventListener("change", function () {
      actualizarFrecuenciaDeTarea(tarea);
    });
    porId("lista-tareas").appendChild(tarea);
    actualizarDescripcionesDeTarea(tarea);
    actualizarFrecuenciaDeTarea(tarea);
    renumerarTareas();
  }

  function modoTareas() {
    return radioSeleccionado("modo-tareas");
  }

  function actualizarModoTareas() {
    const personalizado = modoTareas() === "personalizado";
    porId("bloque-esquema").hidden = personalizado;
    porId("bloque-personalizado").hidden = !personalizado;
    if (personalizado && todos("#lista-tareas [data-tarea]").length === 0) {
      agregarTarea();
    }
  }

  function ventanaDe(inicio, fin) {
    return inicio && fin ? { inicio: inicio, fin: fin } : null;
  }

  function leerTarea(tarea) {
    const campo = function (nombre) {
      return campoDe(tarea, nombre);
    };
    const frecuencia = campo("tipo_frecuencia").value;
    const horas = FRECUENCIAS_CON_HORAS.indexOf(frecuencia) === -1
      ? []
      : todos("[data-lista-horas] input", tarea).map(function (entrada) {
          return entrada.value;
        }).filter(Boolean);
    const dias = frecuencia === "SEMANAL"
      ? todos("[data-lista-dias] input:checked", tarea).map(function (entrada) {
          return entrada.value;
        })
      : [];
    const minutos = entero(campo("intervalo_minutos").value.trim());
    return {
      como: {
        tipo_respaldo: campo("tipo_respaldo").value,
        modo_respaldo: campo("modo_respaldo").value,
        opciones: {
          compresion: campo("compresion").value,
          canales: 1,
          omitir_solo_lectura: campo("omitir_solo_lectura").checked,
        },
      },
      programacion: {
        tipo_frecuencia: frecuencia,
        horas: horas,
        dias_semana: dias,
        intervalo_minutos: frecuencia === "INTERVALO" && !isNaN(minutos) ? minutos : null,
        fecha_inicio: (frecuencia === "UNA_VEZ" || frecuencia === "MENSUAL") && campo("fecha_inicio").value ? campo("fecha_inicio").value : null,
        ventana: ventanaDe(campo("ventana_inicio").value, campo("ventana_fin").value),
        zona_horaria: campo("zona_horaria").value.trim(),
        politica_omision: campo("politica_omision").value,
      },
    };
  }

  function mensajeDeTarea(tarea) {
    const datosTarea = leerTarea(tarea);
    const programacion = datosTarea.programacion;
    const frecuencia = programacion.tipo_frecuencia;
    if (frecuencia === "UNA_VEZ" && !programacion.fecha_inicio) {
      return "Indique la fecha de ejecución.";
    }
    if (FRECUENCIAS_CON_HORAS.indexOf(frecuencia) !== -1 && programacion.horas.length === 0) {
      return "Indique al menos una hora de ejecución.";
    }
    if (frecuencia === "SEMANAL" && programacion.dias_semana.length === 0) {
      return "Marque al menos un día de la semana.";
    }
    if (frecuencia === "INTERVALO" && programacion.intervalo_minutos === null) {
      return "Indique cada cuántos minutos se ejecuta (número entero mayor que cero).";
    }
    if (frecuencia === "INTERVALO" && programacion.intervalo_minutos < 1) {
      return "El intervalo debe ser de al menos 1 minuto.";
    }
    const inicio = campoDe(tarea, "ventana_inicio").value;
    const fin = campoDe(tarea, "ventana_fin").value;
    if (Boolean(inicio) !== Boolean(fin)) {
      return "Complete la ventana de respaldo (desde y hasta) o déjela vacía.";
    }
    if (!programacion.zona_horaria) {
      return "Indique la zona horaria.";
    }
    return null;
  }

  function construirEsquema() {
    const horaN1 = porId("esq-hora-n1").value || "15:00";
    const intervalo = entero(valorDe("esq-intervalo-al"));
    return {
      esquema: radioSeleccionado("esquema"),
      dia_n0: porId("esq-dia-n0").value,
      hora_n0: porId("esq-hora-n0").value,
      hora_n1: horaN1,
      intervalo_archivelog_minutos: isNaN(intervalo) ? 240 : intervalo,
      ventana: ventanaDe(porId("esq-ventana-inicio").value, porId("esq-ventana-fin").value),
      politica_omision: porId("esq-politica").value,
      zona_horaria: valorDe("esq-zona"),
    };
  }

  function construirRetencion() {
    const retencion = {};
    const tipo = radioSeleccionado("retencion");
    if (tipo === "ventana") {
      retencion.ventana_dias = entero(valorDe("ret-ventana"));
    } else if (tipo === "redundancia") {
      retencion.redundancia = entero(valorDe("ret-redundancia"));
    }
    const archivelog = valorDe("ret-archivelog");
    if (archivelog) {
      retencion.archived_logs_dias = entero(archivelog);
    }
    return retencion;
  }

  function construirSolicitud() {
    const solicitud = {
      codigo: valorDe("campo-codigo").toUpperCase(),
      nombre: valorDe("campo-nombre"),
      descripcion: valorDe("campo-descripcion") || null,
      prioridad: prioridadEstrategia(),
      creada_por: valorDe("campo-responsable"),
      alcance: construirAlcance(),
      destino_ruta: valorDe("campo-destino"),
      retencion: construirRetencion(),
      activar: porId("opcion-activar").checked,
      aceptar_caida: porId("aceptar-caida").checked,
      guardar_en_repositorio: porId("opcion-repositorio").checked,
    };
    if (modoTareas() === "esquema") {
      solicitud.esquema = construirEsquema();
    } else {
      solicitud.tareas = todos("#lista-tareas [data-tarea]").map(leerTarea);
    }
    return solicitud;
  }

  function validarPasoGeneral() {
    const errores = [];
    const codigo = valorDe("campo-codigo").toUpperCase();
    if (!PATRON_CODIGO.test(codigo)) {
      errores.push(["codigo", "Use solo letras, números, guion y guion bajo (máximo 20 caracteres)."]);
    } else if (catalogo.codigos_existentes.indexOf(codigo) !== -1) {
      errores.push(["codigo", "Ya existe una estrategia con el código " + codigo + "."]);
    }
    if (!valorDe("campo-responsable")) {
      errores.push(["creada_por", "Escriba el nombre del responsable."]);
    }
    return errores;
  }

  function validarPasoAlcance() {
    return estado.seleccion.size === 0 ? [["alcance", "Seleccione al menos un objeto del árbol."]] : [];
  }

  function validarPasoProgramacion() {
    const errores = [];
    if (modoTareas() === "esquema") {
      if (!porId("esq-hora-n0").value) {
        errores.push(["esquema.hora_n0", "Indique la hora."]);
      }
      const hijoN1 = document.querySelector("[data-solo-n1]");
      if (hijoN1 && !hijoN1.hidden && !porId("esq-hora-n1").value) {
        errores.push(["esquema.hora_n1", "Indique la hora."]);
      }
      const hijoAl = document.querySelector("[data-solo-archivelog]");
      if (hijoAl && !hijoAl.hidden) {
        const minutos = entero(valorDe("esq-intervalo-al"));
        if (isNaN(minutos) || minutos < 1) {
          errores.push(["esquema.intervalo_archivelog_minutos", "Debe ser un número entero mayor que cero."]);
        }
      }
      if (Boolean(porId("esq-ventana-inicio").value) !== Boolean(porId("esq-ventana-fin").value)) {
        errores.push(["esquema.ventana", "Complete la ventana (desde y hasta) o déjela vacía."]);
      }
      if (!valorDe("esq-zona")) {
        errores.push(["esquema.zona_horaria", "Indique la zona horaria."]);
      }
      return errores;
    }
    const tareas = todos("#lista-tareas [data-tarea]");
    if (tareas.length === 0) {
      errores.push(["tareas", "Agregue al menos un tipo de respaldo."]);
    }
    tareas.forEach(function (tarea, indice) {
      const mensaje = mensajeDeTarea(tarea);
      if (mensaje) {
        errores.push(["tarea:" + indice, "Tipo de respaldo T" + (indice + 1) + ": " + mensaje]);
      }
    });
    return errores;
  }

  function validarPasoDestino() {
    const errores = [];
    const ruta = valorDe("campo-destino");
    if (!ruta) {
      errores.push(["destino_ruta", "Indique la carpeta de destino de los respaldos."]);
    } else if (!PATRON_RUTA_ABSOLUTA.test(ruta)) {
      errores.push(["destino_ruta", "La ruta debe ser absoluta, por ejemplo C:\\backups\\XE."]);
    }
    const tipo = radioSeleccionado("retencion");
    if (tipo === "ventana" && !(entero(valorDe("ret-ventana")) >= 1)) {
      errores.push(["retencion.ventana_dias", "Indique un número entero de días mayor que cero."]);
    }
    if (tipo === "redundancia" && !(entero(valorDe("ret-redundancia")) >= 1)) {
      errores.push(["retencion.redundancia", "Indique un número entero de copias mayor que cero."]);
    }
    const archivelog = valorDe("ret-archivelog");
    if (archivelog && !(entero(archivelog) >= 1)) {
      errores.push(["retencion.archived_logs_dias", "Debe ser un número entero mayor que cero."]);
    }
    return errores;
  }

  function validarPasoLocal(numero) {
    limpiarErrores();
    const validadores = {
      1: validarPasoGeneral,
      2: validarPasoAlcance,
      3: validarPasoProgramacion,
      4: validarPasoDestino,
    };
    const errores = validadores[numero] ? validadores[numero]() : [];
    if (errores.length === 0) {
      return true;
    }
    errores.forEach(function (error) {
      if (error[0].indexOf("tarea:") === 0) {
        const tarea = todos("#lista-tareas [data-tarea]")[parseInt(error[0].slice(6), 10)];
        const lugar = tarea ? tarea.querySelector("[data-error-tarea]") : null;
        if (lugar) {
          lugar.textContent = error[1];
          lugar.hidden = false;
          return;
        }
      }
      marcarInvalido(error[0], error[1]);
    });
    mostrarAvisos(errores.map(function (error) {
      return error[1];
    }));
    const primero = pagina.querySelector(".paso:not([hidden]) .invalido, .paso:not([hidden]) .error-campo:not([hidden])");
    if (primero) {
      primero.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    return false;
  }

  function actualizarNavegacion() {
    paneles.forEach(function (panel) {
      panel.hidden = Number(panel.dataset.paso) !== estado.paso;
    });
    botonesPaso.forEach(function (boton) {
      const numero = Number(boton.dataset.irPaso);
      boton.classList.toggle("activo", numero === estado.paso);
      boton.classList.toggle("completo", estado.pasosAprobados.has(numero) && numero !== estado.paso);
      if (numero === estado.paso) {
        boton.setAttribute("aria-current", "step");
      } else {
        boton.removeAttribute("aria-current");
      }
    });
    const enRevision = estado.paso === TOTAL_PASOS;
    botonAnterior.hidden = estado.paso === 1 || estado.guardada;
    botonSiguiente.hidden = enRevision;
    botonValidar.hidden = !enRevision || estado.guardada;
    botonGuardar.hidden = !enRevision || estado.guardada;
  }

  function mostrarPaso(numero) {
    estado.paso = numero;
    actualizarNavegacion();
    pagina.scrollIntoView({ behavior: "smooth", block: "start" });
    if (numero === TOTAL_PASOS) {
      ejecutarValidacion();
    }
  }

  function irAPaso(destino) {
    if (estado.guardada) {
      return;
    }
    for (let numero = 1; numero < destino; numero += 1) {
      if (!validarPasoLocal(numero)) {
        estado.pasosAprobados.delete(numero);
        mostrarPaso(numero);
        validarPasoLocal(numero);
        return;
      }
      estado.pasosAprobados.add(numero);
    }
    limpiarErrores();
    mostrarPaso(destino);
  }

  function pasoDeCampo(campo) {
    return PASO_POR_CAMPO[(campo || "").split(".")[0]] || TOTAL_PASOS;
  }

  function mostrarErroresServidor(errores) {
    limpiarErrores();
    mostrarAvisos(reunir(errores));
    let primerPaso = null;
    errores.forEach(function (error) {
      const campo = error.campo || "";
      const paso = pasoDeCampo(campo);
      if (primerPaso === null && campo) {
        primerPaso = paso;
      }
      const coincidenciaTarea = /^tareas\.(\d+)\./.exec(campo);
      if (coincidenciaTarea) {
        const tarea = todos("#lista-tareas [data-tarea]")[parseInt(coincidenciaTarea[1], 10)];
        const lugar = tarea ? tarea.querySelector("[data-error-tarea]") : null;
        if (lugar) {
          lugar.textContent = error.mensaje;
          lugar.hidden = false;
        }
        return;
      }
      marcarInvalido(campo, error.mensaje);
    });
    return primerPaso;
  }

  function insigniaSeveridad(hallazgo) {
    return crear("span", { clase: "severidad-" + hallazgo.severidad.toLowerCase() }, [
      crear("span", { clase: "insignia", texto: hallazgo.etiqueta_severidad }),
    ]);
  }

  function tablaHallazgos(hallazgos) {
    const cuerpo = crear("tbody");
    hallazgos.forEach(function (hallazgo) {
      cuerpo.appendChild(
        crear("tr", { clase: "severidad-" + hallazgo.severidad.toLowerCase() }, [
          crear("td", {}, [crear("span", { clase: "insignia", texto: hallazgo.etiqueta_severidad })]),
          crear("td", { clase: "columna-codigo", texto: hallazgo.codigo }),
          crear("td", { texto: hallazgo.mensaje }),
          crear("td", { clase: "accion", texto: hallazgo.accion_sugerida || "" }),
        ])
      );
    });
    return crear("table", { clase: "tabla tabla-hallazgos" }, [
      crear("thead", {}, [
        crear("tr", {}, [
          crear("th", { texto: "Nivel" }),
          crear("th", { texto: "Código" }),
          crear("th", { texto: "Observación" }),
          crear("th", { texto: "Acción sugerida" }),
        ]),
      ]),
      cuerpo,
    ]);
  }

  function pintarHallazgos(contenedor, hallazgos, resumen) {
    vaciar(contenedor);
    if (!hallazgos.length) {
      contenedor.appendChild(crear("p", { clase: "sin-observaciones", texto: "Sin observaciones." }));
      return;
    }
    const pildoras = crear("div", { clase: "resumen-hallazgos" });
    Object.keys(resumen || {}).forEach(function (severidad) {
      const ejemplo = hallazgos.find(function (h) {
        return h.severidad === severidad;
      });
      pildoras.appendChild(
        crear("span", { clase: "severidad-" + severidad.toLowerCase() }, [
          crear("span", { clase: "insignia", texto: resumen[severidad] + " " + ejemplo.etiqueta_severidad }),
        ])
      );
    });
    contenedor.appendChild(pildoras);
    contenedor.appendChild(tablaHallazgos(hallazgos));
  }

  function actualizarBotonGuardar() {
    const validacion = estado.validacion;
    const aceptaCaida = !validacion || !validacion.requiere_aceptar_caida || porId("aceptar-caida").checked;
    botonGuardar.disabled = estado.guardando || !validacion || validacion.bloqueante || !aceptaCaida;
  }

  function renderizarRevision(validacion) {
    porId("revision-estado").textContent = "";
    porId("revision-contenido").hidden = false;
    const prioridad = prioridadEstrategia();
    porId("revision-criterio").textContent =
      "Estrategia " + validacion.estrategia.codigo + " — " + validacion.estrategia.nombre + " · prioridad " + prioridad +
      " · RPO ≤ " + validacion.criterio.rpo_horas + " h · RTO ≤ " + validacion.criterio.rto_horas + " h";
    const contenedorHallazgos = porId("revision-hallazgos");
    pintarHallazgos(contenedorHallazgos, validacion.hallazgos, validacion.resumen);
    if (validacion.bloqueante) {
      contenedorHallazgos.appendChild(
        crear("p", {
          clase: "mensaje-bloqueante",
          texto: "Hay errores que bloquean esta estrategia. Corríjalos en los pasos anteriores y vuelva a validar.",
        })
      );
    }
    porId("revision-yaml").textContent = validacion.yaml;
    const bloqueCaida = porId("bloque-caida");
    bloqueCaida.hidden = !validacion.requiere_aceptar_caida;
    if (!validacion.requiere_aceptar_caida) {
      porId("aceptar-caida").checked = false;
    }
    actualizarBotonGuardar();
  }

  async function ejecutarValidacion() {
    const numero = estado.numeroValidacion + 1;
    estado.numeroValidacion = numero;
    estado.validacion = null;
    porId("revision-contenido").hidden = true;
    porId("revision-estado").textContent = "Validando la estrategia contra la instancia " + sid + "…";
    botonGuardar.disabled = true;
    limpiarErrores();
    try {
      const respuesta = await llamarApi(rutaApi("/api/instancias/" + encodeURIComponent(sid) + "/estrategias/validar"), "POST", construirSolicitud());
      if (numero !== estado.numeroValidacion) {
        return;
      }
      estado.validacion = respuesta;
      renderizarRevision(respuesta);
    } catch (error) {
      if (numero !== estado.numeroValidacion) {
        return;
      }
      porId("revision-estado").textContent = "";
      if (error.estado === 422) {
        const paso = mostrarErroresServidor(error.errores);
        porId("revision-estado").textContent = "Hay datos que corregir antes de validar.";
        if (paso !== null && paso !== TOTAL_PASOS) {
          estado.paso = paso;
          actualizarNavegacion();
        }
        return;
      }
      porId("revision-estado").textContent = reunir(error.errores).join(" ");
    }
  }

  function filaResultado(rotulo, texto) {
    return crear("p", {}, [crear("strong", { texto: rotulo + ": " }), texto]);
  }

  function mostrarResultado(resultado) {
    estado.guardada = true;
    porId("revision-contenido").hidden = true;
    porId("revision-estado").textContent = "";
    const volver = "/instancias/" + encodeURIComponent(sid) + (oracleHome ? "?oracle_home=" + encodeURIComponent(oracleHome) : "");
    const otra = "/instancias/" + encodeURIComponent(sid) + "/estrategias/nueva" + (oracleHome ? "?oracle_home=" + encodeURIComponent(oracleHome) : "");
    const contenedor = porId("resultado-guardado");
    vaciar(contenedor);
    contenedor.appendChild(crear("h3", { texto: "Estrategia " + resultado.codigo + " guardada" }));
    contenedor.appendChild(filaResultado("Nombre", resultado.nombre));
    contenedor.appendChild(filaResultado("Estado", resultado.estado + " · versión " + resultado.version));
    contenedor.appendChild(filaResultado("Archivo", resultado.archivo));
    contenedor.appendChild(filaResultado("Repositorio", resultado.repositorio.mensaje));
    contenedor.appendChild(
      crear("div", { clase: "acciones-resultado" }, [
        crear("a", {
          clase: "boton primario",
          href: "/estrategias/" + encodeURIComponent(resultado.bd) + "/" + encodeURIComponent(resultado.codigo),
          texto: "Siguiente: generar y aprobar scripts",
        }),
        crear("a", { clase: "boton", href: otra, texto: "Crear otra estrategia" }),
        crear("a", { clase: "boton", href: volver, texto: "Volver al explorador" }),
      ])
    );
    contenedor.hidden = false;
    actualizarNavegacion();
    contenedor.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function guardar() {
    if (estado.guardando || estado.guardada) {
      return;
    }
    estado.guardando = true;
    botonGuardar.textContent = "Guardando…";
    actualizarBotonGuardar();
    limpiarErrores();
    try {
      const resultado = await llamarApi(rutaApi("/api/instancias/" + encodeURIComponent(sid) + "/estrategias"), "POST", construirSolicitud());
      mostrarResultado(resultado);
    } catch (error) {
      if (error.datos && Array.isArray(error.datos.hallazgos) && error.datos.hallazgos.length) {
        pintarHallazgos(porId("revision-hallazgos"), error.datos.hallazgos, {});
      }
      if (error.estado === 422 && error.errores.length && error.errores[0].campo && PASO_POR_CAMPO[error.errores[0].campo.split(".")[0]]) {
        mostrarErroresServidor(error.errores);
      } else {
        mostrarAvisos(reunir(error.errores));
      }
    } finally {
      estado.guardando = false;
      botonGuardar.textContent = "Guardar estrategia";
      actualizarBotonGuardar();
    }
  }

  const dialogo = porId("dialogo-carpetas");
  const estadoCarpetas = { ruta: "", padre: null };

  function mostrarErrorCarpetas(mensaje) {
    const lugar = porId("carpetas-error");
    lugar.textContent = mensaje || "";
    lugar.hidden = !mensaje;
  }

  function pintarCarpetas(listado) {
    estadoCarpetas.ruta = listado.ruta;
    estadoCarpetas.padre = listado.padre;
    porId("carpetas-ruta").value = listado.ruta;
    porId("carpetas-subir").disabled = listado.padre === null;
    porId("carpetas-elegir").disabled = !listado.ruta;
    porId("carpetas-crear").disabled = !listado.ruta;
    const lista = porId("carpetas-lista");
    vaciar(lista);
    if (!listado.carpetas.length) {
      lista.appendChild(crear("li", { clase: "vacia", texto: "Esta ubicación no tiene carpetas." }));
    }
    listado.carpetas.forEach(function (carpeta) {
      const boton = crear("button", { type: "button", title: carpeta.ruta }, [
        crear("span", { clase: "icono-carpeta", "aria-hidden": "true" }),
        crear("span", { texto: carpeta.nombre }),
      ]);
      boton.addEventListener("click", function () {
        cargarCarpetas(carpeta.ruta);
      });
      lista.appendChild(crear("li", {}, [boton]));
    });
    if (listado.truncado) {
      lista.appendChild(crear("li", { clase: "vacia", texto: "Hay más carpetas de las que se pueden mostrar. Escriba la ruta para llegar a una concreta." }));
    }
  }

  function mostrarAvisoCarpetas(mensaje) {
    const lugar = porId("carpetas-aviso");
    lugar.textContent = mensaje || "";
    lugar.hidden = !mensaje;
  }

  async function cargarCarpetas(ruta, cercana) {
    mostrarErrorCarpetas("");
    mostrarAvisoCarpetas("");
    const parametros = [];
    if (ruta) {
      parametros.push("ruta=" + encodeURIComponent(ruta));
    }
    if (cercana) {
      parametros.push("cercana=true");
    }
    try {
      const listado = await llamarApi("/api/carpetas" + (parametros.length ? "?" + parametros.join("&") : ""), "GET");
      pintarCarpetas(listado);
      return listado;
    } catch (error) {
      mostrarErrorCarpetas(reunir(error.errores).join(" "));
      return null;
    }
  }

  async function abrirExplorador() {
    dialogo.showModal();
    const candidata = valorDe("campo-destino");
    const listado = await cargarCarpetas(candidata, true);
    if (listado && candidata && !listado.solicitada_existe) {
      mostrarAvisoCarpetas(
        "La carpeta indicada todavía no existe: se muestra la más cercana que sí existe. Puede crear la carpeta desde aquí."
      );
    }
  }

  async function crearCarpeta() {
    const entrada = porId("carpetas-nueva-nombre");
    const nombre = entrada.value.trim();
    if (!estadoCarpetas.ruta) {
      return;
    }
    if (!nombre) {
      mostrarErrorCarpetas("Escriba un nombre para la carpeta nueva.");
      return;
    }
    try {
      const nueva = await llamarApi("/api/carpetas", "POST", { padre: estadoCarpetas.ruta, nombre: nombre });
      entrada.value = "";
      await cargarCarpetas(nueva.ruta);
    } catch (error) {
      mostrarErrorCarpetas(reunir(error.errores).join(" "));
    }
  }

  function enlazarDialogoCarpetas() {
    porId("abrir-explorador").addEventListener("click", abrirExplorador);
    porId("formulario-carpetas").addEventListener("submit", function (evento) {
      evento.preventDefault();
    });
    porId("carpetas-subir").addEventListener("click", function () {
      if (estadoCarpetas.padre !== null) {
        cargarCarpetas(estadoCarpetas.padre);
      }
    });
    porId("carpetas-ir").addEventListener("click", function () {
      cargarCarpetas(valorDe("carpetas-ruta"));
    });
    porId("carpetas-ruta").addEventListener("keydown", function (evento) {
      if (evento.key === "Enter") {
        evento.preventDefault();
        cargarCarpetas(valorDe("carpetas-ruta"));
      }
    });
    porId("carpetas-nueva-nombre").addEventListener("keydown", function (evento) {
      if (evento.key === "Enter") {
        evento.preventDefault();
        crearCarpeta();
      }
    });
    porId("carpetas-crear").addEventListener("click", crearCarpeta);
    porId("carpetas-cancelar").addEventListener("click", function () {
      dialogo.close();
    });
    porId("carpetas-elegir").addEventListener("click", function () {
      if (!estadoCarpetas.ruta) {
        return;
      }
      porId("campo-destino").value = estadoCarpetas.ruta;
      porId("campo-destino").classList.remove("invalido");
      dialogo.close();
      porId("campo-destino").focus();
    });
  }

  function actualizarRetencion() {
    const tipo = radioSeleccionado("retencion");
    porId("campo-ret-ventana").hidden = tipo !== "ventana";
    porId("campo-ret-redundancia").hidden = tipo !== "redundancia";
  }

  function enlazarEventos() {
    botonSiguiente.addEventListener("click", function () {
      irAPaso(estado.paso + 1);
    });
    botonAnterior.addEventListener("click", function () {
      limpiarErrores();
      mostrarPaso(estado.paso - 1);
    });
    botonValidar.addEventListener("click", ejecutarValidacion);
    botonGuardar.addEventListener("click", guardar);
    botonesPaso.forEach(function (boton) {
      boton.addEventListener("click", function () {
        const destino = Number(boton.dataset.irPaso);
        if (destino <= estado.paso) {
          limpiarErrores();
          mostrarPaso(destino);
        } else {
          irAPaso(destino);
        }
      });
    });
    porId("formulario-estrategia").addEventListener("submit", function (evento) {
      evento.preventDefault();
    });
    todos('input[name="prioridad"]').forEach(function (radio) {
      radio.addEventListener("change", function () {
        actualizarRecomendado();
        renderizarResumenSeleccion();
      });
    });
    todos('input[name="esquema"]').forEach(function (radio) {
      radio.addEventListener("change", function () {
        estado.esquemaTocado = true;
        actualizarEsquema();
      });
    });
    todos('input[name="modo-tareas"]').forEach(function (radio) {
      radio.addEventListener("change", actualizarModoTareas);
    });
    todos('input[name="retencion"]').forEach(function (radio) {
      radio.addEventListener("change", actualizarRetencion);
    });
    porId("agregar-tarea").addEventListener("click", agregarTarea);
    porId("aceptar-caida").addEventListener("change", actualizarBotonGuardar);
    porId("opcion-activar").addEventListener("change", function () {
      if (estado.paso === TOTAL_PASOS && !estado.guardada) {
        ejecutarValidacion();
      }
    });
    todos("input, select, textarea", porId("formulario-estrategia")).forEach(function (campo) {
      campo.addEventListener("input", function () {
        campo.classList.remove("invalido");
      });
    });
    enlazarDialogoCarpetas();
  }

  if (catalogo.instancia.log_mode === "NOARCHIVELOG") {
    porId("aviso-noarchivelog").hidden = false;
  }
  enlazarEventos();
  inicializarSeleccion();
  actualizarRecomendado();
  actualizarEsquema();
  actualizarModoTareas();
  actualizarRetencion();
  actualizarNavegacion();
})();
