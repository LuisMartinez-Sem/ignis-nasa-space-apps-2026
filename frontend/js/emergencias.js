/**
 * Pestaña "Emergencias" del HUD (módulo NUEVO e independiente).
 *
 * Consume `/api/v1/emergencias` (contrato verificado por tests/test_contratos_v1.py),
 * muestra una tarjeta por emergencia y, al hacer clic, una vista "split screen":
 *   - Izquierda: Humano, con la línea de tiempo DOCUMENTADA (sin retrasos inventados).
 *   - Derecha: IGNIS, con HUD de telemetría, detección y copiloto.
 *   - Abajo: gráfico comparativo de latencias (escala logarítmica).
 *   - Botón "Ver resolución": pasos de cómo IGNIS habría guiado la respuesta.
 *
 * Requiere cargar `reconstruccion.js` antes (usa sus formateadores y la comparación).
 * Formato UMD: `window.IgnisEmergencias` en el navegador; `module.exports` en Node.
 */
(function (raiz, fabrica) {
  'use strict';
  if (typeof module === 'object' && module.exports) {
    module.exports = fabrica(require('./reconstruccion.js'));
  } else {
    raiz.IgnisEmergencias = fabrica(raiz.IgnisReconstruccion);
  }
})(typeof self !== 'undefined' ? self : this, function (R) {
  'use strict';

  if (!R) throw new Error('emergencias.js requiere cargar reconstruccion.js antes.');

  const BASE_API = '/api/v1/emergencias';
  const ORDEN_PREFERIDO = ['mir', 'iss', 'columbus', 'saffire'];
  const ID_VALIDO = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;
  const CONFIANZAS = ['documentado', 'aproximado', 'no_verificado'];
  const GUION = '\u2014';

  /**
   * Cifras de referencia aportadas por el equipo (OPT-IN: pásalas a `montar` mediante
   * `opciones.referencias`). Están rotuladas como supuesto: no tienen respaldo documental
   * en este repositorio y la interfaz lo indica.
   */
  const REFERENCIAS_EQUIPO = Object.freeze({
    humano: Object.freeze({
      deteccion_s: 0,
      extincion_s: 90,
      extincion_verificada: true,
      fuente: 'NASA Shuttle-Mir: fin de la llama a ~90 s (la extinci\u00f3n completa no est\u00e1 verificada)',
    }),
    convencional: Object.freeze({
      deteccion_s: 1.5,
      falsas_alarmas: true,
      es_supuesto: true,
      fuente: 'Supuesto del equipo IGNIS; sin respaldo documental',
    }),
    ignis: Object.freeze({
      deteccion_s: 0.9,
      deteccion_fuente: 'TCN (modelo f\u00edsico actualizado)',
      supresion_s: 3,
      supresion_es_supuesto: true,
      falsas_alarmas: 0,
      es_supuesto: true,
    }),
  });

  const esc = R.escaparHtml;
  const fd = R.formatearDuracion;
  const esNumero = (x) => typeof x === 'number' && Number.isFinite(x);
  const numeroOnull = (v) => (esNumero(v) && v >= 0 ? v : null);

  class ErrorEmergencias extends Error {
    /** @param {'red'|'http'|'formato'} codigo */
    constructor(codigo, mensaje) {
      super(mensaje);
      this.name = 'ErrorEmergencias';
      this.codigo = codigo;
    }
  }

  // ---------------------------------------------------------------------------
  // Datos: normalización y acceso a la API
  // ---------------------------------------------------------------------------

  /** Normaliza el resumen de una emergencia. Devuelve null si no tiene un id válido. */
  function normalizarEmergencia(raw) {
    if (!raw || typeof raw !== 'object' || typeof raw.id !== 'string' || !ID_VALIDO.test(raw.id)) return null;
    return {
      id: raw.id,
      nombre: String(raw.nombre || raw.id),
      fecha: raw.fecha == null ? null : String(raw.fecha),
      lugar: raw.lugar == null ? null : String(raw.lugar),
      tipo: raw.tipo == null ? null : String(raw.tipo),
      es_incendio: raw.es_incendio !== false,
      modelo_aplicable: raw.modelo_aplicable !== false,
      resumen: raw.resumen == null ? '' : String(raw.resumen),
    };
  }

  /** Falsas alarmas: true (existen, sin cuantificar), un número >= 0, o null (sin dato). */
  function normalizarFalsas(v) {
    return v === true ? true : numeroOnull(v);
  }

  function textoFalsas(v) {
    if (v === true) return 'S\u00ed (no cuantificadas)';
    return esNumero(v) ? String(v) : GUION;
  }

  /** Normaliza los tiempos de IGNIS (segundos tras el inicio del evento). */
  function normalizarIgnis(raw) {
    if (!raw || typeof raw !== 'object') return null;
    return {
      deteccion_s: numeroOnull(raw.deteccion_s),
      deteccion_fuente: raw.deteccion_fuente == null ? '' : String(raw.deteccion_fuente),
      supresion_s: numeroOnull(raw.supresion_s),
      supresion_es_supuesto: raw.supresion_es_supuesto !== false,
      falsas_alarmas: normalizarFalsas(raw.falsas_alarmas),
      es_supuesto: raw.es_supuesto === true,
    };
  }

  /** Normaliza el detector convencional (umbral fijo). Sin `es_supuesto: false` se trata como supuesto. */
  function normalizarConvencional(raw) {
    if (!raw || typeof raw !== 'object') return null;
    return {
      deteccion_s: numeroOnull(raw.deteccion_s),
      falsas_alarmas: normalizarFalsas(raw.falsas_alarmas),
      es_supuesto: raw.es_supuesto !== false,
      fuente: raw.fuente == null ? '' : String(raw.fuente),
    };
  }

  /** Normaliza una referencia humana explícita (reemplaza campos de la derivada del incidente). */
  function normalizarHumano(raw) {
    if (!raw || typeof raw !== 'object') return null;
    return {
      deteccion_s: numeroOnull(raw.deteccion_s),
      extincion_s: numeroOnull(raw.extincion_s),
      extincion_verificada: raw.extincion_verificada !== false,
      fuente: raw.fuente == null ? '' : String(raw.fuente),
    };
  }

  /**
   * Normaliza el detalle de una emergencia. Acepta el incidente directamente o dentro de
   * `incidente`, y las muestras/acciones en la raíz o dentro de `simulacion`.
   */
  function normalizarDetalle(raw) {
    if (!raw || typeof raw !== 'object') throw new ErrorEmergencias('formato', 'El detalle no es un objeto JSON.');
    const incidente = raw.incidente && typeof raw.incidente === 'object' ? raw.incidente : raw;
    const resumen = normalizarEmergencia(incidente);
    if (!resumen) throw new ErrorEmergencias('formato', 'El detalle no tiene un id v\u00e1lido.');
    const sim = raw.simulacion && typeof raw.simulacion === 'object' ? raw.simulacion : {};
    const lista = (...candidatos) => candidatos.find(Array.isArray) || [];
    return {
      ...resumen,
      incidente,
      inicio_evento_s: numeroOnull(incidente.inicio_evento_s) || 0,
      timeline: lista(incidente.timeline_humano),
      advertencia: incidente.advertencia_modelo ? String(incidente.advertencia_modelo) : '',
      supuestos: lista(incidente.supuestos_ignis),
      ignis: normalizarIgnis(raw.ignis),
      convencional: normalizarConvencional(raw.convencional),
      humano: normalizarHumano(raw.humano),
      muestras: lista(sim.muestras, raw.muestras),
      acciones: lista(raw.acciones, sim.acciones),
    };
  }

  /** Orden preferido (Mir, ISS, Columbus, Saffire) y luego el resto, conservando el orden original. */
  function ordenarEmergencias(lista) {
    const rango = (e) => {
      const i = ORDEN_PREFERIDO.findIndex((clave) => e.id.toLowerCase().startsWith(clave));
      return i === -1 ? ORDEN_PREFERIDO.length : i;
    };
    return lista
      .map((e, posicion) => ({ e, posicion }))
      .sort((a, b) => rango(a.e) - rango(b.e) || a.posicion - b.posicion)
      .map((x) => x.e);
  }

  async function pedirJson(fetchFn, url) {
    let respuesta;
    try {
      respuesta = await fetchFn(url, { headers: { Accept: 'application/json' } });
    } catch (_) {
      throw new ErrorEmergencias('red', 'No se pudo conectar con el servidor.');
    }
    if (!respuesta || !respuesta.ok) {
      throw new ErrorEmergencias('http', 'El servidor respondi\u00f3 ' + (respuesta ? respuesta.status : 'sin respuesta') + '.');
    }
    try {
      return await respuesta.json();
    } catch (_) {
      throw new ErrorEmergencias('formato', 'La respuesta del servidor no es JSON v\u00e1lido.');
    }
  }

  async function cargarEmergencias(fetchFn, base = BASE_API) {
    const datos = await pedirJson(fetchFn, base);
    const lista = Array.isArray(datos) ? datos : datos && datos.emergencias;
    if (!Array.isArray(lista)) throw new ErrorEmergencias('formato', 'Se esperaba una lista de emergencias.');
    return ordenarEmergencias(lista.map(normalizarEmergencia).filter(Boolean));
  }

  async function cargarDetalle(fetchFn, id, base = BASE_API) {
    if (typeof id !== 'string' || !ID_VALIDO.test(id)) throw new ErrorEmergencias('formato', 'Identificador no v\u00e1lido.');
    return normalizarDetalle(await pedirJson(fetchFn, base + '/' + encodeURIComponent(id)));
  }

  // ---------------------------------------------------------------------------
  // Cálculos de presentación
  // ---------------------------------------------------------------------------

  /** Telemetría en el instante t: números interpolados; nivel y NTC de la muestra previa. */
  function hudEn(muestras, t) {
    if (!Array.isArray(muestras) || muestras.length === 0 || !esNumero(t)) return null;
    let previa = muestras[0];
    for (const m of muestras) {
      if (m.t_s <= t) previa = m;
      else break;
    }
    return {
      t_s: t,
      indice_riesgo: R.interpolar(muestras, 'indice_riesgo', t),
      fraccion_o2: R.interpolar(muestras, 'fraccion_o2', t),
      temperatura_reaccion_k: R.interpolar(muestras, 'temperatura_reaccion_k', t),
      nivel_riesgo: previa.nivel_riesgo == null ? null : String(previa.nivel_riesgo),
      estado_ntc: previa.estado_ntc == null ? null : String(previa.estado_ntc),
    };
  }

  /** Comparación humano vs IGNIS con la misma vara de medir (ver reconstruccion.js). */
  /** Referencia humana: derivada del incidente, con los campos no nulos de `detalle.humano` por encima. */
  function referenciaHumana(detalle) {
    const base = R.humanoDesdeIncidente(detalle.incidente);
    const o = detalle.humano || {};
    return {
      ...base,
      deteccion_s: o.deteccion_s !== null && o.deteccion_s !== undefined ? o.deteccion_s : base.deteccion_s,
      extincion_s: o.extincion_s !== null && o.extincion_s !== undefined ? o.extincion_s : base.extincion_s,
      extincion_verificada: detalle.humano ? o.extincion_verificada : base.extincion_verificada,
      fuente: o.fuente || '',
    };
  }

  function resumenDe(detalle) {
    const ignis = detalle.ignis || {};
    return R.resumenComparativo({
      humano: referenciaHumana(detalle),
      ignis: { deteccion_s: ignis.deteccion_s, supresion_s: ignis.supresion_s },
    });
  }

  /** Filas del gráfico. Con `convencional` se añade su barra (solo tiene tiempo de detección). */
  function datosGraficoLatencias(resumen, convencional) {
    const filas = [
      { clave: 'deteccion', etiqueta: 'Detecci\u00f3n', humano_s: resumen.humano.deteccion_s, ignis_s: resumen.ignis.deteccion_s, ventaja_s: resumen.ventaja_deteccion_s },
      { clave: 'extincion', etiqueta: 'Extinci\u00f3n', humano_s: resumen.humano.extincion_s, ignis_s: resumen.ignis.extincion_s, ventaja_s: resumen.ventaja_extincion_s },
    ];
    if (convencional) {
      filas[0].convencional_s = convencional.deteccion_s;
      filas[1].convencional_s = null;
    }
    return filas;
  }

  /** Ancho relativo (0-1) en escala logar\u00edtmica: permite ver 0,9 s junto a 840 s. */
  function anchoBarra(valor, maximo) {
    if (!esNumero(valor) || !esNumero(maximo) || maximo <= 0 || valor < 0) return 0;
    return Math.min(1, Math.log1p(valor) / Math.log1p(maximo));
  }

  function construirGraficoLatenciasSVG(filas, ancho = 520) {
    const valores = filas.flatMap((f) => [f.humano_s, f.ignis_s, f.convencional_s]).filter(esNumero);
    const conConvencional = filas.some((f) => 'convencional_s' in f);
    const maximo = valores.length ? Math.max(...valores) : 0;
    const margenIzq = 84;
    const margenDer = 96;
    const util = ancho - margenIzq - margenDer;
    const altoFila = conConvencional ? 76 : 54;
    const alto = filas.length * altoFila + 8;
    const barra = (valor, y, clase) => {
      const w = valor === null || valor === undefined ? 0 : anchoBarra(valor, maximo) * util;
      const ancho2 = valor > 0 ? Math.max(w, 2) : 0;
      return (
        '<rect class="' + clase + '" x="' + margenIzq + '" y="' + y + '" width="' + ancho2.toFixed(1) + '" height="16" rx="3"></rect>' +
        '<text class="emg-lat__valor" x="' + (margenIzq + ancho2 + 6).toFixed(1) + '" y="' + (y + 12) + '">' + esc(fd(valor === undefined ? null : valor)) + '</text>'
      );
    };
    const partes = [];
    const descripcion = [];
    filas.forEach((f, i) => {
      const y = 6 + i * altoFila;
      partes.push('<text class="emg-lat__etiqueta" x="0" y="' + (y + 22) + '">' + esc(f.etiqueta) + '</text>');
      partes.push(barra(f.humano_s, y, 'emg-lat__barra emg-lat__barra--humano'));
      if (conConvencional) partes.push(barra(f.convencional_s, y + 22, 'emg-lat__barra emg-lat__barra--convencional'));
      partes.push(barra(f.ignis_s, y + (conConvencional ? 44 : 22), 'emg-lat__barra emg-lat__barra--ignis'));
      descripcion.push(
        f.etiqueta + ': humano ' + fd(f.humano_s) +
        (conConvencional ? ', convencional ' + fd(f.convencional_s) : '') + ', IGNIS ' + fd(f.ignis_s)
      );
    });
    return (
      '<svg class="emg-lat__svg" viewBox="0 0 ' + ancho + ' ' + alto + '" role="img" aria-label="' + esc(descripcion.join('; ')) + '">' +
      partes.join('') + '</svg>'
    );
  }

  /** Acciones del copiloto ordenadas por primera aparición (máximo n). */
  function accionesPrincipales(acciones, n = 3) {
    return [...acciones]
      .filter((a) => a && typeof a === 'object' && a.id)
      .sort((a, b) => (numeroOnull(a.primer_t_s) ?? Infinity) - (numeroOnull(b.primer_t_s) ?? Infinity) || String(a.id).localeCompare(String(b.id)))
      .slice(0, n);
  }

  /**
   * Pasos de cómo IGNIS habría guiado la respuesta. IGNIS RECOMIENDA; la tripulación ejecuta.
   * Solo se incluyen pasos respaldados por datos recibidos (nada se inventa).
   */
  function pasosResolucion(detalle) {
    const ignis = detalle.ignis;
    if (!ignis || detalle.modelo_aplicable === false) return [];
    const inicio = detalle.inicio_evento_s || 0;
    const pasos = [];
    let tDeteccion = null;

    if (ignis.deteccion_s !== null) {
      tDeteccion = inicio + ignis.deteccion_s;
      pasos.push({
        tipo: 'deteccion',
        t_s: tDeteccion,
        titulo: 'Detecci\u00f3n',
        detalle: 'El detector temporal se\u00f1ala el evento ' + fd(ignis.deteccion_s) + ' despu\u00e9s del inicio.' +
          (ignis.deteccion_fuente ? ' Fuente: ' + ignis.deteccion_fuente + '.' : ''),
        es_supuesto: false,
      });
      const hud = hudEn(detalle.muestras, tDeteccion);
      if (hud && hud.indice_riesgo !== null) {
        pasos.push({
          tipo: 'evaluacion',
          t_s: tDeteccion,
          titulo: 'Evaluaci\u00f3n',
          detalle: '\u00cdndice de riesgo ' + hud.indice_riesgo.toFixed(0) +
            (hud.nivel_riesgo ? ' (' + hud.nivel_riesgo + ')' : '') +
            (hud.estado_ntc ? '; zona NTC: ' + hud.estado_ntc : '') + '.',
          es_supuesto: false,
        });
      }
    }

    for (const a of accionesPrincipales(detalle.acciones)) {
      const confianza = Array.isArray(a.confianzas) && a.confianzas.length ? a.confianzas.join('/') : 'sin dato';
      pasos.push({
        tipo: 'recomendacion',
        t_s: numeroOnull(a.primer_t_s),
        titulo: 'Recomendaci\u00f3n del copiloto',
        detalle: String(a.descripcion || a.id) + ' Fuente: ' + String(a.fuente || 'sin fuente') +
          (a.fuente_verificada ? '' : ' (secci\u00f3n sin verificar)') + '. Confianza: ' + confianza + '.',
        es_supuesto: false,
      });
    }

    if (ignis.supresion_s !== null) {
      pasos.push({
        tipo: 'supresion',
        t_s: tDeteccion === null ? null : tDeteccion + ignis.supresion_s,
        titulo: 'Supresi\u00f3n por la tripulaci\u00f3n',
        detalle: 'Tiempo ' + (ignis.supresion_es_supuesto ? 'supuesto' : 'registrado') + ' de ' + fd(ignis.supresion_s) +
          ' desde la detecci\u00f3n. IGNIS recomienda; ejecutar la acci\u00f3n depende de la tripulaci\u00f3n.',
        es_supuesto: ignis.supresion_es_supuesto,
      });
    }
    return pasos;
  }

  // ---------------------------------------------------------------------------
  // HTML (todo texto dinámico pasa por esc)
  // ---------------------------------------------------------------------------

  function recortar(texto, max) {
    return texto.length > max ? texto.slice(0, max - 1).trimEnd() + '\u2026' : texto;
  }

  function construirTarjetaHTML(e) {
    const insignias = [];
    if (!e.es_incendio) insignias.push('Experimento');
    if (!e.modelo_aplicable) insignias.push('Modelo no aplicable');
    return (
      '<button type="button" class="emg-tarjeta" data-accion="abrir" data-id="' + esc(e.id) + '">' +
      '<span class="emg-tarjeta__fecha">' + esc(e.fecha || 'Fecha no indicada') + '</span>' +
      '<strong class="emg-tarjeta__nombre">' + esc(e.nombre) + '</strong>' +
      (e.lugar ? '<span class="emg-tarjeta__lugar">' + esc(e.lugar) + '</span>' : '') +
      (e.resumen ? '<span class="emg-tarjeta__resumen">' + esc(recortar(e.resumen, 180)) + '</span>' : '') +
      insignias.map((i) => '<span class="emg-insignia">' + esc(i) + '</span>').join('') +
      '</button>'
    );
  }

  function construirListaHTML(lista) {
    const cuerpo = lista.length
      ? '<div class="emg-tarjetas">' + lista.map(construirTarjetaHTML).join('') + '</div>'
      : '<p class="emg-vacio">No hay emergencias disponibles.</p>';
    return (
      '<section class="emg-lista"><h2 class="emg-titulo">Emergencias</h2>' +
      '<p class="emg-intro">Elige una emergencia para comparar la respuesta humana documentada con la de IGNIS.</p>' +
      cuerpo + '</section>'
    );
  }

  function construirColumnaHumano(detalle) {
    const ventana = R.humanoDesdeIncidente(detalle.incidente);
    const ref = referenciaHumana(detalle);
    const eventos = detalle.timeline.map((ev) => {
      const e = ev && typeof ev === 'object' ? ev : {};
      const confianza = CONFIANZAS.includes(e.confianza) ? e.confianza : 'desconocida';
      return (
        '<li class="emg-evento emg-evento--' + confianza + '">' +
        '<span class="emg-evento__t">' + (esNumero(e.t_s) ? esc(fd(e.t_s)) : 'n/d') + '</span>' +
        '<span class="emg-evento__texto"><strong>' + esc(e.accion || 'Evento sin descripci\u00f3n') + '</strong>' +
        (e.resultado ? ' \u2014 ' + esc(e.resultado) : '') + '</span>' +
        '<span class="emg-insignia emg-insignia--' + confianza + '">' + esc(confianza.replace('_', ' ')) + '</span></li>'
      );
    });
    const ventanaTxt =
      ventana.fin_llama_s !== null && ventana.extincion_s !== null
        ? '<p class="emg-nota">Duraci\u00f3n documentada del fuego: ' + esc(fd(ventana.fin_llama_s)) + ' a ' + esc(fd(ventana.extincion_s)) +
          ' (ventana de oportunidad, no un resultado medido).</p>'
        : '';
    return (
      '<article class="emg-col emg-col--humano"><h3>Humano</h3>' +
      '<p class="emg-deteccion">Detecci\u00f3n: <strong>' + esc(fd(ref.deteccion_s)) + '</strong> \u00b7 Extinci\u00f3n: <strong>' + esc(fd(ref.extincion_s)) + '</strong>' +
      (ref.fuente ? ' <span class="emg-nota">(' + esc(ref.fuente) + ')</span>' : '') + '</p>' +
      '<p class="emg-nota">L\u00ednea de tiempo documentada en fuentes p\u00fablicas. \u201cn/d\u201d = tiempo no documentado.</p>' +
      (eventos.length ? '<ol class="emg-eventos">' + eventos.join('') + '</ol>' : '<p class="emg-vacio">Sin eventos documentados.</p>') +
      ventanaTxt + '</article>'
    );
  }

  function celdaHud(etiqueta, valor) {
    return '<div class="emg-hud__celda"><dt>' + esc(etiqueta) + '</dt><dd>' + esc(valor === null || valor === undefined ? GUION : valor) + '</dd></div>';
  }

  function construirColumnaConvencional(detalle) {
    const cabecera = '<article class="emg-col emg-col--convencional"><h3>Detector convencional</h3>' +
      '<p class="emg-nota">Umbral fijo de temperatura.</p>';
    if (detalle.modelo_aplicable === false) {
      return cabecera + '<p class="emg-vacio">Esta emergencia est\u00e1 marcada como no aplicable al modelo.</p></article>';
    }
    const c = detalle.convencional;
    if (!c) return cabecera + '<p class="emg-vacio">Sin datos del detector convencional.</p></article>';
    return (
      cabecera +
      '<p class="emg-deteccion">Detecci\u00f3n: <strong>' + esc(fd(c.deteccion_s)) + '</strong> tras el inicio ' +
      (c.es_supuesto ? '<span class="emg-insignia emg-insignia--supuesto">supuesto</span>' : '') + '</p>' +
      '<p class="emg-falsas">Falsas alarmas: <strong>' + esc(textoFalsas(c.falsas_alarmas)) + '</strong></p>' +
      (c.fuente ? '<p class="emg-nota">' + esc(c.fuente) + '</p>' : '') + '</article>'
    );
  }

  function construirColumnaIgnis(detalle) {
    const cabecera = '<article class="emg-col emg-col--ignis"><h3>IGNIS</h3>';
    if (detalle.modelo_aplicable === false) {
      return cabecera + '<p class="emg-vacio">Esta emergencia est\u00e1 marcada como no aplicable al modelo.</p></article>';
    }
    const ignis = detalle.ignis;
    if (!ignis) {
      return cabecera + '<p class="emg-vacio">El servidor no entreg\u00f3 los tiempos de IGNIS para esta emergencia.</p></article>';
    }
    const partes = [cabecera];
    if (ignis.deteccion_s !== null) {
      const tDet = (detalle.inicio_evento_s || 0) + ignis.deteccion_s;
      partes.push(
        '<p class="emg-deteccion">Detecci\u00f3n: <strong>' + esc(fd(ignis.deteccion_s)) + '</strong> tras el inicio' +
        (ignis.deteccion_fuente ? ' <span class="emg-nota">(' + esc(ignis.deteccion_fuente) + ')</span>' : '') +
        (ignis.es_supuesto ? ' <span class="emg-insignia emg-insignia--supuesto">supuesto</span>' : '') + '</p>' +
        '<p class="emg-falsas">Falsas alarmas: <strong>' + esc(textoFalsas(ignis.falsas_alarmas)) + '</strong></p>'
      );
      const hud = hudEn(detalle.muestras, tDet);
      if (hud) {
        partes.push(
          '<dl class="emg-hud" aria-label="Telemetr\u00eda en el momento de la detecci\u00f3n">' +
          celdaHud('\u00cdndice de riesgo', hud.indice_riesgo === null ? null : hud.indice_riesgo.toFixed(0)) +
          celdaHud('Nivel', hud.nivel_riesgo) +
          celdaHud('O\u2082', hud.fraccion_o2 === null ? null : hud.fraccion_o2.toFixed(3)) +
          celdaHud('T reacci\u00f3n', hud.temperatura_reaccion_k === null ? null : hud.temperatura_reaccion_k.toFixed(0) + ' K') +
          celdaHud('Zona NTC', hud.estado_ntc) + '</dl>'
        );
      }
    } else {
      partes.push('<p class="emg-vacio">Sin tiempo de detecci\u00f3n disponible.</p>');
    }
    const acciones = accionesPrincipales(detalle.acciones);
    partes.push('<h4>Copiloto</h4>');
    partes.push(
      acciones.length
        ? '<ol class="emg-acciones">' + acciones.map((a) =>
            '<li><span>' + esc(a.descripcion || a.id) + '</span> <span class="emg-nota">' + esc(a.fuente || 'sin fuente') +
            (a.fuente_verificada ? '' : ' \u00b7 secci\u00f3n sin verificar') + '</span> ' +
            '<span class="emg-insignia">' + esc(Array.isArray(a.confianzas) && a.confianzas.length ? a.confianzas.join('/') : 'sin dato') + '</span></li>'
          ).join('') + '</ol>'
        : '<p class="emg-vacio">Sin recomendaciones disponibles.</p>'
    );
    partes.push('</article>');
    return partes.join('');
  }

  function construirResolucionHTML(detalle) {
    const pasos = pasosResolucion(detalle);
    if (!pasos.length) {
      return '<section class="emg-resolucion"><p class="emg-vacio">No hay datos suficientes para reconstruir la resoluci\u00f3n.</p></section>';
    }
    return (
      '<section class="emg-resolucion" aria-label="Resoluci\u00f3n paso a paso"><h3>C\u00f3mo IGNIS habr\u00eda guiado la respuesta</h3><ol class="emg-pasos">' +
      pasos.map((p, i) =>
        '<li class="emg-paso emg-paso--' + esc(p.tipo) + (p.es_supuesto ? ' emg-paso--supuesto' : '') + '" style="--emg-i:' + i + '">' +
        '<span class="emg-paso__t">' + (esNumero(p.t_s) ? 't = ' + esc(fd(p.t_s)) : 'n/d') + '</span>' +
        '<strong>' + esc(p.titulo) + '</strong> ' + (p.es_supuesto ? '<span class="emg-insignia emg-insignia--supuesto">supuesto</span>' : '') +
        '<span class="emg-paso__detalle">' + esc(p.detalle) + '</span></li>'
      ).join('') + '</ol></section>'
    );
  }

  function construirVistaSplitHTML(detalle, opciones = {}) {
    const resumen = resumenDe(detalle);
    const avisos = [];
    if (detalle.advertencia) avisos.push(detalle.advertencia);
    for (const a of resumen.advertencias) avisos.push(a);
    if ((detalle.convencional && detalle.convencional.es_supuesto) || (detalle.ignis && detalle.ignis.es_supuesto)) {
      avisos.push('Las cifras marcadas como supuesto (detector convencional e IGNIS) son referencias del equipo, no mediciones.');
    }
    const boton = detalle.ignis && detalle.modelo_aplicable !== false
      ? '<button type="button" class="emg-boton" data-accion="resolucion" aria-expanded="' + (opciones.resolucion ? 'true' : 'false') + '">' +
        (opciones.resolucion ? 'Ocultar resoluci\u00f3n' : 'Ver resoluci\u00f3n') + '</button>'
      : '';
    return (
      '<section class="emg-split" aria-label="' + esc(detalle.nombre) + '">' +
      '<header class="emg-split__cabecera"><button type="button" class="emg-boton" data-accion="volver">\u2190 Volver</button>' +
      '<h2 class="emg-titulo">' + esc(detalle.nombre) + '</h2>' + boton + '</header>' +
      avisos.map((a) => '<p class="emg-aviso">' + esc(a) + '</p>').join('') +
      '<div class="emg-columnas">' + construirColumnaHumano(detalle) + construirColumnaConvencional(detalle) + construirColumnaIgnis(detalle) + '</div>' +
      '<figure class="emg-latencias"><figcaption>Comparaci\u00f3n de latencias (escala logar\u00edtmica)</figcaption>' +
      '<p class="emg-leyenda"><span class="emg-leyenda__humano">Humano</span> <span class="emg-leyenda__convencional">Convencional</span> <span class="emg-leyenda__ignis">IGNIS</span></p>' +
      construirGraficoLatenciasSVG(datosGraficoLatencias(resumen, detalle.convencional)) +
      '<p class="emg-nota">Ventaja = humano \u2212 IGNIS. Detecci\u00f3n: ' + esc(R.formatearVentaja(resumen.ventaja_deteccion_s)) +
      '. Extinci\u00f3n: ' + esc(R.formatearVentaja(resumen.ventaja_extincion_s)) + '.</p></figure>' +
      (opciones.resolucion ? construirResolucionHTML(detalle) : '') + '</section>'
    );
  }

  function construirErrorHTML(mensaje) {
    return '<div class="emg-error" role="alert"><p>' + esc(mensaje) + '</p>' +
      '<button type="button" class="emg-boton" data-accion="reintentar">Reintentar</button></div>';
  }

  // ---------------------------------------------------------------------------
  // Montaje
  // ---------------------------------------------------------------------------

  /**
   * @param {Element} contenedor Elemento donde se dibuja la pestaña.
   * @param {object} [opciones]
   * @param {Function} [opciones.fetch] Función fetch (por defecto, la global).
   * @param {string} [opciones.base] URL base de la API.
   * @param {object} [opciones.ignisPorDefecto] Tiempos de IGNIS a usar si la API no los entrega:
   *        { deteccion_s, deteccion_fuente, supresion_s, supresion_es_supuesto, falsas_alarmas }.
   * @param {object} [opciones.referencias] { humano, convencional, ignis }: se usan solo donde la API
   *        no entrega el dato (p. ej. `IgnisEmergencias.REFERENCIAS_EQUIPO`). Prevalece sobre `ignisPorDefecto`.
   * @returns {{listo: Promise<void>, recargar: Function, destruir: Function, estado: Function}}
   */
  function montar(contenedor, opciones = {}) {
    if (!contenedor || typeof contenedor.addEventListener !== 'function') {
      throw new TypeError('contenedor debe ser un elemento del DOM');
    }
    const fetchFn = opciones.fetch || (typeof fetch === 'function' ? fetch.bind(globalThis) : null);
    if (!fetchFn) throw new TypeError('No hay fetch disponible; pasa opciones.fetch');
    const base = opciones.base || BASE_API;
    const refs = opciones.referencias || {};
    const ignisPorDefecto = normalizarIgnis(refs.ignis || opciones.ignisPorDefecto);
    const convencionalPorDefecto = normalizarConvencional(refs.convencional);
    const humanoPorDefecto = normalizarHumano(refs.humano);

    const estado = { vista: 'cargando', lista: [], detalle: null, resolucion: false, error: null };
    let solicitud = 0;
    let activo = true;

    function render() {
      if (!activo) return;
      if (estado.error) contenedor.innerHTML = construirErrorHTML(estado.error);
      else if (estado.vista === 'cargando') contenedor.innerHTML = '<p class="emg-cargando" role="status">Cargando emergencias\u2026</p>';
      else if (estado.vista === 'detalle' && estado.detalle) contenedor.innerHTML = construirVistaSplitHTML(estado.detalle, { resolucion: estado.resolucion });
      else contenedor.innerHTML = construirListaHTML(estado.lista);
    }

    async function cargarLista() {
      const mia = ++solicitud;
      Object.assign(estado, { vista: 'cargando', error: null, detalle: null, resolucion: false });
      render();
      try {
        const lista = await cargarEmergencias(fetchFn, base);
        if (mia !== solicitud) return;
        Object.assign(estado, { lista, vista: 'lista' });
      } catch (e) {
        if (mia !== solicitud) return;
        estado.error = e instanceof ErrorEmergencias ? e.message : 'Error inesperado al cargar las emergencias.';
        estado.reintento = 'lista';
      }
      render();
    }

    async function abrir(id) {
      const mia = ++solicitud;
      Object.assign(estado, { vista: 'cargando', error: null, resolucion: false, idPendiente: id });
      render();
      try {
        const detalle = await cargarDetalle(fetchFn, id, base);
        if (mia !== solicitud) return;
        if (!detalle.ignis && ignisPorDefecto) detalle.ignis = ignisPorDefecto;
        if (!detalle.convencional && convencionalPorDefecto) detalle.convencional = convencionalPorDefecto;
        if (!detalle.humano && humanoPorDefecto) detalle.humano = humanoPorDefecto;
        Object.assign(estado, { detalle, vista: 'detalle' });
      } catch (e) {
        if (mia !== solicitud) return;
        estado.error = e instanceof ErrorEmergencias ? e.message : 'Error inesperado al cargar la emergencia.';
        estado.reintento = 'detalle';
      }
      render();
    }

    function alHacerClic(ev) {
      const objetivo = ev && ev.target;
      if (!objetivo) return;
      const el = typeof objetivo.closest === 'function' ? objetivo.closest('[data-accion]') : objetivo;
      if (!el || typeof el.getAttribute !== 'function') return;
      const accion = el.getAttribute('data-accion');
      if (accion === 'abrir') {
        const id = el.getAttribute('data-id');
        if (id) abrir(id);
      } else if (accion === 'volver') {
        solicitud += 1;
        Object.assign(estado, { vista: 'lista', detalle: null, resolucion: false, error: null });
        render();
      } else if (accion === 'resolucion') {
        estado.resolucion = !estado.resolucion;
        render();
      } else if (accion === 'reintentar') {
        if (estado.reintento === 'detalle' && estado.idPendiente) abrir(estado.idPendiente);
        else cargarLista();
      }
    }

    contenedor.addEventListener('click', alHacerClic);
    const listo = cargarLista();
    return {
      listo,
      recargar: cargarLista,
      estado: () => ({ vista: estado.vista, error: estado.error, resolucion: estado.resolucion, total: estado.lista.length }),
      destruir() {
        activo = false;
        if (typeof contenedor.removeEventListener === 'function') contenedor.removeEventListener('click', alHacerClic);
        contenedor.innerHTML = '';
      },
    };
  }

  return {
    BASE_API,
    REFERENCIAS_EQUIPO,
    ErrorEmergencias,
    normalizarEmergencia,
    normalizarIgnis,
    normalizarConvencional,
    normalizarHumano,
    normalizarDetalle,
    ordenarEmergencias,
    cargarEmergencias,
    cargarDetalle,
    hudEn,
    referenciaHumana,
    resumenDe,
    datosGraficoLatencias,
    anchoBarra,
    construirGraficoLatenciasSVG,
    accionesPrincipales,
    pasosResolucion,
    construirTarjetaHTML,
    construirListaHTML,
    construirColumnaHumano,
    construirColumnaConvencional,
    construirColumnaIgnis,
    construirResolucionHTML,
    construirVistaSplitHTML,
    montar,
  };
});
