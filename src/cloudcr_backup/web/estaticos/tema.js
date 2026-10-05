(function () {
  "use strict";

  // Se carga en el <head>, antes de pintar, para que no haya parpadeo al elegir el tema.
  const CLAVE = "cloudcr-tema";
  const raiz = document.documentElement;

  function guardado() {
    try {
      const valor = window.localStorage.getItem(CLAVE);
      return valor === "claro" || valor === "oscuro" ? valor : null;
    } catch (error) {
      return null;
    }
  }

  function recordar(tema) {
    try {
      window.localStorage.setItem(CLAVE, tema);
    } catch (error) {
      // Sin almacenamiento disponible: el tema solo dura mientras la página esté abierta.
    }
  }

  function delSistema() {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "oscuro" : "claro";
  }

  function vigente() {
    return raiz.getAttribute("data-tema") || delSistema();
  }

  function aplicar(tema) {
    raiz.setAttribute("data-tema", tema);
  }

  // Un cambio de tema altera casi todos los colores a la vez: sin transiciones, el cambio es instantáneo.
  function sinTransiciones() {
    raiz.classList.add("sin-transiciones");
    void raiz.offsetWidth;
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        raiz.classList.remove("sin-transiciones");
      });
    });
  }

  const inicial = guardado();
  if (inicial) {
    aplicar(inicial);
  }

  document.addEventListener("click", function (evento) {
    const boton = evento.target.closest("[data-alternar-tema]");
    if (!boton) {
      return;
    }
    const siguiente = vigente() === "oscuro" ? "claro" : "oscuro";
    sinTransiciones();
    aplicar(siguiente);
    recordar(siguiente);
  });
})();
