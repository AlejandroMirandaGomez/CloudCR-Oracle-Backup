(function () {
  "use strict";

  const ATRIBUTO_OCULTO = "data-oculto-busqueda";

  function arbol() {
    return document.getElementById("arbol");
  }

  function abrirAncestros(elemento) {
    let actual = elemento.parentElement;
    while (actual) {
      if (actual.tagName === "DETAILS") {
        actual.open = true;
      }
      actual = actual.parentElement;
    }
  }

  function resaltar(elemento) {
    elemento.classList.remove("resaltado");
    void elemento.offsetWidth;
    elemento.classList.add("resaltado");
  }

  function irANodo(identificador) {
    const destino = document.getElementById(identificador);
    if (!destino) {
      return false;
    }
    abrirAncestros(destino);
    if (destino.tagName === "DETAILS") {
      destino.open = true;
    }
    destino.scrollIntoView({ behavior: "smooth", block: "center" });
    resaltar(destino);
    return true;
  }

  function cambiarTodos(abrir) {
    const raiz = arbol();
    if (!raiz) {
      return;
    }
    raiz.querySelectorAll("details.nodo").forEach(function (detalle) {
      detalle.open = abrir;
    });
    const primero = raiz.querySelector("details.nodo");
    if (primero) {
      primero.open = true;
    }
  }

  function aplicarBusqueda() {
    const raiz = arbol();
    const campo = document.getElementById("buscar");
    if (!raiz || !campo) {
      return;
    }
    const termino = campo.value.trim().toLowerCase();
    const nodos = raiz.querySelectorAll(".nodo");
    if (!termino) {
      nodos.forEach(function (nodo) {
        nodo.removeAttribute(ATRIBUTO_OCULTO);
      });
      return;
    }
    const visibles = new Set();
    nodos.forEach(function (nodo) {
      if ((nodo.getAttribute("data-texto") || "").includes(termino)) {
        visibles.add(nodo);
        let actual = nodo.parentElement;
        while (actual && actual !== raiz) {
          if (actual.classList.contains("nodo")) {
            visibles.add(actual);
            if (actual.tagName === "DETAILS") {
              actual.open = true;
            }
          }
          actual = actual.parentElement;
        }
      }
    });
    function ancestroCoincide(nodo) {
      let actual = nodo.parentElement ? nodo.parentElement.closest(".nodo") : null;
      while (actual && raiz.contains(actual)) {
        if ((actual.getAttribute("data-texto") || "").includes(termino)) {
          return true;
        }
        actual = actual.parentElement ? actual.parentElement.closest(".nodo") : null;
      }
      return false;
    }
    nodos.forEach(function (nodo) {
      if (visibles.has(nodo) || ancestroCoincide(nodo)) {
        nodo.removeAttribute(ATRIBUTO_OCULTO);
      } else {
        nodo.setAttribute(ATRIBUTO_OCULTO, "");
      }
    });
  }

  function aplicarFiltrosSeveridad() {
    const raiz = arbol();
    if (!raiz) {
      return;
    }
    const ocultarAdvertencias = document.getElementById("ocultar-advertencias");
    const ocultarRecomendaciones = document.getElementById("ocultar-recomendaciones");
    raiz.classList.toggle("oculta-severidad-advertencia", !!ocultarAdvertencias && ocultarAdvertencias.checked);
    raiz.classList.toggle("oculta-severidad-recomendacion", !!ocultarRecomendaciones && ocultarRecomendaciones.checked);
  }

  document.addEventListener("click", function (evento) {
    const objetivo = evento.target instanceof Element ? evento.target : null;
    if (!objetivo) {
      return;
    }
    const accion = objetivo.closest("[data-accion]");
    if (accion) {
      cambiarTodos(accion.getAttribute("data-accion") === "expandir");
      return;
    }
    const enlace = objetivo.closest("[data-ir-a]");
    if (enlace && irANodo(enlace.getAttribute("data-ir-a"))) {
      evento.preventDefault();
    }
  });

  document.addEventListener("input", function (evento) {
    if (evento.target instanceof Element && evento.target.id === "buscar") {
      aplicarBusqueda();
    }
  });

  document.addEventListener("change", function (evento) {
    if (
      evento.target instanceof Element &&
      (evento.target.id === "ocultar-advertencias" || evento.target.id === "ocultar-recomendaciones")
    ) {
      aplicarFiltrosSeveridad();
    }
  });

  document.addEventListener("htmx:afterSettle", function () {
    aplicarBusqueda();
    aplicarFiltrosSeveridad();
  });
})();
