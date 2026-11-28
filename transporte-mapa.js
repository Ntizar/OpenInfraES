// transporte-mapa.js — el GTFS del NAP dentro del visor de siempre.
//
// 207.943 paradas y 31.970 rutas no caben en GeoJSON (×3,9 de heap), así que van como teselas
// vectoriales PMTiles, dibujadas en canvas sobre Leaflet con protomaps-leaflet. Se descarga solo
// lo que se ve, y a zoom de país no se pide nada.
//
// Fuente: pipeline NAP de gtfs-espana (MITRAMS). Teselas servidas desde ntizar.github.io.
//
// API para el asistente:
//   OpenInfraES.transporte.poner("paradas"|"lineas", true|false)
(function () {
  "use strict";
  if (window.__TM_CARGADO) return;
  window.__TM_CARGADO = true;

  const BASE = "https://ntizar.github.io/gtfs-espana/";
  const COLOR = { rail: "#3b82f6", ferry: "#06b6d4", air: "#a855f7", bus: "#f59e0b" };
  const estado = { paradas: false, lineas: false };
  const capas = {};
  let contador = 0;

  const $ = (s) => document.querySelector(s);

  function mapa() {
    const ia = window.OpenInfraES && window.OpenInfraES.ia;
    return ia ? ia.mapa() : null;
  }

  // Pane propio por encima del fondo y de las capas GeoJSON: el fondo del visor se pinta en
  // canvas dentro de tilePane, y sin esto el transporte queda debajo y no se ve.
  function pane(m) {
    if (!m.getPane("tm-pane")) {
      const p = m.createPane("tm-pane");
      p.style.zIndex = 450;
      p.style.pointerEvents = "none";
    }
    return "tm-pane";
  }

  function hayMotor() {
    return !!(window.protomapsL && window.pmtiles && mapa());
  }

  function pintaParadas() {
    if (capas.paradas) return capas.paradas;
    capas.paradas = protomapsL.leafletLayer({
      pane: pane(mapa()),
      url: BASE + "stops.pmtiles",
      maxDataZoom: 14,
      attribution: "Paradas: NAP · MITRAMS",
      paintRules: [{
        dataLayer: "stops",
        minzoom: 11,
        symbolizer: new protomapsL.CircleSymbolizer({
          radius: 2.4, fill: "#f59e0b", opacity: 0.95, strokeWidth: 0,
        }),
      }],
    });
    return capas.paradas;
  }

  function pintaLineas() {
    if (capas.lineas) return capas.lineas;
    const modo = (f) => COLOR[(f && f.props && f.props.modo) || "bus"] || COLOR.bus;
    capas.lineas = protomapsL.leafletLayer({
      pane: pane(mapa()),
      url: BASE + "lines.pmtiles",
      maxDataZoom: 14,
      attribution: "Red: NAP · MITRAMS",
      paintRules: [
        {
          dataLayer: "lines",
          minzoom: 6,
          symbolizer: new protomapsL.LineSymbolizer({
            color: modo, width: 1.6, opacity: 0.75,
          }),
        },
      ],
    });
    return capas.lineas;
  }

  function poner(que, on) {
    const m = mapa();
    if (!m || !hayMotor()) return false;
    const clave = que === "lineas" ? "lineas" : "paradas";
    let capa;
    try {
      capa = clave === "lineas" ? pintaLineas() : pintaParadas();
    } catch (e) {
      document.documentElement.dataset.tmerror = "crear: " + e.message;
      return false;
    }
    try {
      if (on) capa.addTo(m); else capa.remove();
    } catch (e) {
      document.documentElement.dataset.tmerror = "add: " + e.message;
      return false;
    }
    estado[clave] = !!on;
    pintaEstado();
    return true;
  }

  function pintaEstado() {
    const b = $("#tm-estado");
    if (b) {
      const act = [];
      if (estado.paradas) act.push("paradas");
      if (estado.lineas) act.push("líneas");
      b.textContent = act.length ? act.join(" + ") + " en el mapa" : "sin activar";
      b.className = "tm-est" + (act.length ? " on" : "");
    }
    const p = $("#tm-paradas"), l = $("#tm-lineas");
    if (p) p.checked = estado.paradas;
    if (l) l.checked = estado.lineas;
  }

  const CSS = `
  #tm-btn{position:fixed;left:16px;bottom:96px;z-index:1200;display:flex;align-items:center;gap:6px;
    padding:0 12px;height:40px;border-radius:20px;border:1px solid var(--borde-fuerte,#2a3a5c);
    background:var(--panel-solido,#132038);color:var(--tinta,#e6edf9);font:600 12px inherit;
    cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.45)}
  #tm-btn:hover{border-color:#f59e0b}
  #tm-btn.on{border-color:#f59e0b;color:#f59e0b}
  #tm-caja{position:fixed;left:16px;bottom:146px;z-index:1201;width:min(260px,calc(100vw - 32px));
    display:none;flex-direction:column;gap:8px;padding:12px;border-radius:12px;
    background:var(--panel-solido,#0f1729);border:1px solid var(--borde-fuerte,#2a3a5c);
    box-shadow:0 12px 40px rgba(0,0,0,.5);color:var(--tinta,#e6edf9);font:12px inherit}
  #tm-caja.on{display:flex}
  #tm-caja h4{margin:0 0 2px;font:700 12px inherit;color:#f59e0b}
  #tm-caja label{display:flex;align-items:center;gap:8px;cursor:pointer;line-height:1.35}
  #tm-caja input{accent-color:#f59e0b;width:15px;height:15px;flex:0 0 auto}
  #tm-caja small{color:#7d8ca8;font-size:10.5px;line-height:1.4}
  .tm-est{color:#7d8ca8;font-size:11px;margin-top:2px}
  .tm-est.on{color:#22c55e}
  @media(max-width:720px){
    #tm-btn{left:12px;bottom:150px;height:38px;font-size:11.5px}
    #tm-caja{left:8px;right:8px;width:auto;bottom:196px}
  }`;

  function monta() {
    const st = document.createElement("style");
    st.textContent = CSS;
    document.head.appendChild(st);

    const btn = document.createElement("button");
    btn.id = "tm-btn";
    btn.type = "button";
    btn.title = "Transporte público del NAP";
    btn.innerHTML = "<span>🚏</span><span>Transporte</span>";
    btn.onclick = () => {
      const caja = $("#tm-caja");
      caja.classList.toggle("on");
      btn.classList.toggle("on", caja.classList.contains("on"));
    };

    const caja = document.createElement("div");
    caja.id = "tm-caja";
    caja.innerHTML = `
      <h4>Transporte público · NAP</h4>
      <label><input type="checkbox" id="tm-paradas"> 207.943 paradas</label>
      <label><input type="checkbox" id="tm-lineas"> 31.970 líneas</label>
      <small>Teselas del MITRAMS. A zoom de España no se descarga nada; entrando, se dibuja solo lo que ves.</small>
      <div class="tm-est" id="tm-estado">sin activar</div>`;
    document.body.append(btn, caja);

    $("#tm-paradas").onchange = (e) => poner("paradas", e.target.checked);
    $("#tm-lineas").onchange = (e) => poner("lineas", e.target.checked);

    // Deep link: ?transporte=paradas,lineas
    const pedido = new URLSearchParams(location.search).get("transporte");
    if (pedido) {
      pedido.split(",").forEach((q) => {
        const clave = q.trim() === "lineas" || q.trim() === "líneas" ? "lineas" : "paradas";
        if (poner(clave, true)) { /* ya pinta */ }
      });
      $("#tm-caja").classList.add("on");
      btn.classList.add("on");
    }
  }

  window.OpenInfraES = window.OpenInfraES || {};
  window.OpenInfraES.transporte = {
    poner,
    estado: () => ({ ...estado }),
    hayMotor,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", monta);
  else monta();
})();
