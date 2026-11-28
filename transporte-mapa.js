// transporte-mapa.js — todo el transporte del NAP dentro del mapa de siempre.
//
// 207.943 paradas y 31.970 rutas no caben en GeoJSON (×3,9 de heap), así que van como teselas
// vectoriales PMTiles dibujadas en canvas sobre Leaflet con protomaps-leaflet. Se descarga solo
// lo que se ve; a zoom de país no se pide nada.
//
// Los modos NO son una propiedad `modo`: el empaquetador del pipeline escribe `tipo` en
// castellano (Autobús, Ferroviario, Metro, Tranvía, Marítimo, Aéreo). Buscando `modo` todo caía
// al color por defecto y la red parecía solo de autobuses.
//
// Fuente: pipeline NAP de gtfs-espana (MITRAMS). El GTFS aéreo no trae geometría: los arcos entre
// aeropuertos los genera el pipeline (AECFA) y se sirven en aereo.pmtiles. Nada inventado.
//
// API para el asistente:
//   OpenInfraES.transporte.poner("paradas"|"bus"|"rail"|"ferry"|"aereo", true|false)
//   OpenInfraES.transporte.panel(true|false)
(function () {
  "use strict";
  if (window.__TM_CARGADO) return;
  window.__TM_CARGADO = true;

  const BASE = "https://ntizar.github.io/gtfs-espana/";

  // Color por tipo, los mismos del visor de transporte para que un tren sea azul en los dos.
  const COLOR = {
    "Autobús": "#f59e0b", "Ferroviario": "#3b82f6", "Metro": "#8b5cf6",
    "Marítimo": "#06b6d4", "Tranvía": "#22c55e", "Aéreo": "#ec4899",
  };
  const OTROS = "#94a3b8";

  const GRUPOS = [
    { id: "paradas", nombre: "Paradas", detalle: "207.943 · todas las redes" },
    { id: "bus", nombre: "Líneas de autobús", detalle: "ámbar" },
    { id: "rail", nombre: "Tren, metro y tranvía", detalle: "azul · violeta · verde" },
    { id: "ferry", nombre: "Ferris", detalle: "cian" },
    { id: "aereo", nombre: "Vuelos", detalle: "arcos entre aeropuertos · AECFA" },
  ];

  const estado = { paradas: false, bus: false, rail: false, ferry: false, aereo: false };
  const capas = {};    // grupo visible por clave: array de capas Leaflet
  const crudas = {};   // cada capa por separado

  const $ = (s) => document.querySelector(s);

  function mapa() {
    const ia = window.OpenInfraES && window.OpenInfraES.ia;
    return ia ? ia.mapa() : null;
  }

  function hayMotor() {
    return !!(window.protomapsL && window.pmtiles && mapa());
  }

  // Pane propio por encima del fondo y de las capas GeoJSON: el fondo del visor se pinta en
  // canvas dentro de tilePane y sin esto el transporte queda debajo (capa en el mapa, invisible).
  function pane(m) {
    if (!m.getPane("tm-pane")) {
      const p = m.createPane("tm-pane");
      p.style.zIndex = 450;
      p.style.pointerEvents = "none";
    }
    return "tm-pane";
  }

  // protomaps-leaflet llama a los estilizadores con (zoom, feature): el primer argumento NO es la
  // feature. Con la firma al revés todo caía al color por defecto y los filtros no casaban nada.
  const colorDe = (z, f) => COLOR[(f && f.props && f.props.tipo) || ""] || OTROS;

  function capaParadas() {
    if (crudas.paradas) return crudas.paradas;
    crudas.paradas = protomapsL.leafletLayer({
      pane: pane(mapa()),
      url: BASE + "stops.pmtiles",
      maxDataZoom: 14,
      attribution: "Paradas: NAP · MITRAMS",
      paintRules: [{
        dataLayer: "stops",
        minzoom: 9,
        symbolizer: new protomapsL.CircleSymbolizer({
          radius: 2.4, fill: colorDe, opacity: 0.95, strokeWidth: 0,
        }),
      }],
    });
    return crudas.paradas;
  }

  // `lines.pmtiles` guarda `tipo` como CÓDIGO GTFS en texto ("3" bus, "2" tren, "1" metro,
  // "0"/"900" tranvía, "7" funicular, "4" ferry), no el nombre del modo. Y el LineSymbolizer
  // solo acepta color FIJO: con una función no dibuja nada y no avisa. De ahí una regla por
  // modo con su color y su filtro.
  const GRUPO_REGLAS = {
    bus: [{ cods: ["3", "200", "704", "715"], color: "#f59e0b", w: 1.3 }],
    rail: [
      { cods: ["2"], color: "#3b82f6", w: 2.0 },          // tren
      { cods: ["1"], color: "#8b5cf6", w: 1.8 },          // metro
      { cods: ["0", "900"], color: "#22c55e", w: 1.6 },   // tranvía
      { cods: ["7"], color: "#a3e635", w: 1.5 },          // funicular
    ],
    ferry: [{ cods: ["4"], color: "#06b6d4", w: 1.9 }],
  };

  function capaLineas(clave) {
    if (crudas[clave]) return crudas[clave];
    crudas[clave] = protomapsL.leafletLayer({
      pane: pane(mapa()),
      url: BASE + "lines.pmtiles",
      maxDataZoom: 14,
      attribution: "Red: NAP · MITRAMS",
      paintRules: GRUPO_REGLAS[clave].map((r) => ({
        dataLayer: "lines",
        minzoom: clave === "bus" ? 7 : (clave === "ferry" ? 5 : 6),
        filter: (z, f) => r.cods.indexOf(String(f.props.tipo)) >= 0,
        symbolizer: new protomapsL.LineSymbolizer({
          color: r.color, width: r.w, opacity: 0.85,
        }),
      })),
    });
    return crudas[clave];
  }

  // A escala de país `lines.pmtiles` no tiene datos (empieza en z7): la red de tren, metro y
  // tranvía se sirve aparte en red-baja.pmtiles hasta z7,6. Sin esto, a zoom de España no se
  // veía ni un tren y parecía que no había datos.
  function capaRedBaja() {
    if (crudas.redbaja) return crudas.redbaja;
    crudas.redbaja = protomapsL.leafletLayer({
      pane: pane(mapa()),
      url: BASE + "red-baja.pmtiles",
      maxDataZoom: 6,
      attribution: "Red de tren y metro: NAP · MITRAMS",
      paintRules: [
        { dataLayer: "redbaja_tren", minzoom: 3, maxzoom: 7.6,
          symbolizer: new protomapsL.LineSymbolizer({ color: "#3b82f6", width: 1.6, opacity: 0.9 }) },
        { dataLayer: "redbaja_metro", minzoom: 3, maxzoom: 7.6,
          symbolizer: new protomapsL.LineSymbolizer({ color: "#8b5cf6", width: 1.4, opacity: 0.9 }) },
        { dataLayer: "redbaja_tram", minzoom: 3, maxzoom: 7.6,
          symbolizer: new protomapsL.LineSymbolizer({ color: "#22c55e", width: 1.2, opacity: 0.9 }) },
      ],
    });
    return crudas.redbaja;
  }

  // Los vuelos NO van por teselas: el PMTiles solo conservó los 36 aeropuertos y perdía los
  // 1.715 arcos. Son pocos y ligeros (386 KB), así que van como GeoJSON directo, que además
  // permite señalarlos con el ratón. Las props traen `de`/`a` (IATA), `op` y `cid`.
  function capaAereo() {
    if (crudas.aereo) return crudas.aereo;
    crudas.aereo = L.geoJSON(null, {
      pane: pane(mapa()),
      style: { color: "#ec4899", weight: 1.3, opacity: 0.62, fill: false },
      pointToLayer: (f, latlng) => L.circleMarker(latlng, {
        pane: pane(mapa()), radius: 3.4, color: "#ec4899", weight: 1,
        fillColor: "#ec4899", fillOpacity: 0.9,
      }),
      onEachFeature: (f, l) => {
        // L.geoJSON no siempre hereda `pane`: se fija capa a capa antes de entrar al mapa.
        if (l.options) l.options.pane = pane(mapa());
        const p = f.properties || {};
        if (p.de && p.a) l.bindTooltip(p.de + " → " + p.a + (p.op ? " · " + p.op : ""), { sticky: true });
        else if (p.iata || p.codigo) l.bindTooltip(String(p.nombre || p.iata || p.codigo), { direction: "top" });
      },
    });
    fetch(BASE + "aereo.geojson")
      .then((r) => r.json())
      .then((d) => {
        crudas.aereo.addData(d);
        window.__aereoN = (d.features || []).length;
      })
      .catch(() => { document.documentElement.dataset.tmerror = "aereo geojson"; });
    return crudas.aereo;
  }

  function capasDe(clave) {
    if (!capas[clave]) {
      if (clave === "paradas") capas[clave] = [capaParadas()];
      else if (clave === "aereo") capas[clave] = [capaAereo()];
      else {
        capas[clave] = [capaLineas(clave)];
        if (clave === "rail") capas[clave].push(capaRedBaja());
      }
    }
    return capas[clave];
  }

  function poner(que, on) {
    const m = mapa();
    if (!m || !hayMotor()) return false;
    const clave = estado[que] === undefined ? "paradas" : que;
    let grupo;
    try {
      grupo = capasDe(clave);
    } catch (e) {
      document.documentElement.dataset.tmerror = "crear: " + e.message;
      return false;
    }
    try {
      grupo.forEach((c) => { if (on) c.addTo(m); else c.remove(); });
    } catch (e) {
      document.documentElement.dataset.tmerror = "add: " + e.message;
      return false;
    }
    estado[clave] = !!on;
    pintaEstado();
    return true;
  }

  function pintaEstado() {
    const act = GRUPOS.filter((g) => estado[g.id]).map((g) => g.nombre.toLowerCase());
    const b = $("#tp-estado");
    if (b) {
      b.textContent = act.length ? act.join(" · ") : "sin capas de transporte";
      b.className = "tp-est" + (act.length ? " on" : "");
    }
    const caja = $("#tp-caja");
    if (caja) caja.querySelectorAll("input[data-g]").forEach((i) => {
      i.checked = !!estado[i.dataset.g];
    });
  }

  const CSS = `
  #tp-velo{position:fixed;inset:0;z-index:1400;display:none;align-items:center;justify-content:center;
    background:rgba(4,8,15,.62);padding:16px}
  #tp-velo.on{display:flex}
  #tp-caja{width:min(340px,100%);max-height:82vh;overflow:auto;border-radius:14px;padding:16px;
    background:var(--panel-solido,#0f1729);border:1px solid var(--borde-fuerte,#2a3a5c);
    box-shadow:0 24px 70px rgba(0,0,0,.6);color:var(--tinta,#e6edf9);font:13px inherit}
  #tp-cabeza{display:flex;align-items:center;gap:8px;margin-bottom:2px}
  #tp-cabeza h4{margin:0;font:700 15px inherit;color:#f59e0b;flex:1}
  #tp-x{width:26px;height:26px;border-radius:8px;border:1px solid var(--borde,#22304d);
    background:transparent;color:var(--tenue,#7d8ca8);font:14px/1 inherit;cursor:pointer}
  #tp-x:hover{border-color:#f59e0b;color:#f59e0b}
  #tp-caja .sub{color:#7d8ca8;font-size:11px;line-height:1.45;margin:0 0 10px}
  #tp-caja label{display:flex;align-items:center;gap:10px;cursor:pointer;padding:9px 0;
    border-top:1px solid rgba(255,255,255,.07);line-height:1.3}
  #tp-caja label span{flex:1}
  #tp-caja label small{display:block;color:#7d8ca8;font-size:10.5px}
  #tp-caja input{accent-color:#f59e0b;width:16px;height:16px;flex:0 0 auto}
  .tp-est{margin-top:12px;color:#7d8ca8;font-size:11px}
  .tp-est.on{color:#22c55e}
  #tp-caja .pie{color:#5f6d86;font-size:10px;margin-top:10px;line-height:1.4}
  `;

  function monta() {
    const st = document.createElement("style");
    st.textContent = CSS;
    document.head.appendChild(st);

    const velo = document.createElement("div");
    velo.id = "tp-velo";
    velo.innerHTML = `
      <div id="tp-caja" role="dialog" aria-label="Transporte público">
        <div id="tp-cabeza"><h4>Transporte público</h4>
          <button id="tp-x" title="Cerrar" aria-label="Cerrar">✕</button></div>
        <p class="sub">Red del NAP (MITRAMS): paradas, líneas, ferris y vuelos. Teselas vectoriales:
          se dibuja solo lo que ves; a zoom de país no se descarga nada.</p>
        ${GRUPOS.map((g) => `
          <label><input type="checkbox" data-g="${g.id}">
            <span>${g.nombre}<small>${g.detalle}</small></span></label>`).join("")}
        <div class="tp-est" id="tp-estado">sin capas de transporte</div>
        <div class="pie">Paradas y líneas: GTFS del NAP. Vuelos: arcos AECFA entre aeropuertos.</div>
      </div>`;
    document.body.appendChild(velo);

    velo.addEventListener("click", (e) => { if (e.target === velo) panel(false); });
    $("#tp-x").addEventListener("click", () => panel(false));
    velo.querySelectorAll("input[data-g]").forEach((i) => {
      i.addEventListener("change", (e) => poner(e.target.dataset.g, e.target.checked));
    });

    pintaEstado();
    // Deep link: ?transporte=paradas,rail,ferry,aereo
    const pedido = new URLSearchParams(location.search).get("transporte");
    if (pedido) {
      pedido.split(",").forEach((q) => {
        const k = q.trim();
        if (estado[k] !== undefined) poner(k, true);
      });
      panel(true);
    }
  }

  function panel(on) {
    const v = $("#tp-velo");
    if (!v) return "sin panel";
    v.classList.toggle("on", !!on);
    if (on) pintaEstado();
    return "ok";
  }

  window.OpenInfraES = window.OpenInfraES || {};
  window.OpenInfraES.transporte = {
    poner,
    panel,
    estado: () => ({ ...estado }),
    hayMotor,
    _capas: capas,
    _diag: (que) => {
      const m = mapa();
      const cs = capas[que] || [];
      const pane = m && m.getPane("tm-pane");
      return {
        capas: cs.length, enMapa: cs.every((c) => m && m.hasLayer(c)),
        canvas: pane ? pane.querySelectorAll("canvas").length : -1,
        panes: m ? Object.keys(m._panes) : [],
        error: document.documentElement.dataset.tmerror || "",
      };
    },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", monta);
  else monta();
})();
