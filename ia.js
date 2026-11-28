// ia.js — el asistente del visor, con el mapa a la vista.
//
// El navegador NO habla con el modelo: manda la frase a /api/chat y recibe una orden ya resuelta
// (chat_openinfra.py). Aquí solo se ejecuta. Si el backend no está, se dice y no se inventa nada.
//
// Acciones que sabe ejecutar:
//   volar    {centro:[lon,lat], zoom}
//   capa     {id, visible}
//   filtrar  {id, campo, op:"in", valor:[...]}
//   mezclar  {coropleta:{...}, puntos:{...}}  + top de municipios con coordenadas
//   ficha    {titulo, html}
(function () {
  "use strict";

  if (window.__IA_CARGADA) return;
  window.__IA_CARGADA = true;

  let abierto = false;
  let escuchando = false;
  let reconocedor = null;
  let posicion = null;

  const CSS = `
  #ia-btn{position:fixed;right:16px;bottom:96px;z-index:1200;width:52px;height:52px;border-radius:50%;
    border:1px solid var(--borde-fuerte,#2a3a5c);background:var(--panel-solido,#132038);color:#f59e0b;
    font-size:21px;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.45);display:flex;align-items:center;
    justify-content:center}
  #ia-btn:hover{filter:brightness(1.25)}
  #ia-btn.on{background:#f59e0b;color:#0b1020;border-color:#f59e0b}
  #ia-caja{position:fixed;right:16px;bottom:158px;z-index:1201;width:min(400px,calc(100vw - 32px));
    max-height:min(64vh,540px);display:none;flex-direction:column;background:var(--panel-solido,#0f1729);
    border:1px solid var(--borde-fuerte,#2a3a5c);border-radius:14px;overflow:hidden;
    box-shadow:0 12px 40px rgba(0,0,0,.5);color:var(--tinta,#e6edf9)}
  #ia-caja.on{display:flex}
  #ia-cab{display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid var(--borde,#1e2b45);
    font:700 12.5px/1.2 inherit;color:#f59e0b}
  #ia-cab .est{margin-left:auto;font:400 10.5px inherit;color:var(--suave,#7d8ca8)}
  #ia-cab .est.ok{color:#22c55e}
  #ia-cab .est.mal{color:#ef4444}
  #ia-x{margin-left:6px;flex:0 0 auto;width:22px;height:22px;line-height:1;border-radius:6px;
    border:1px solid var(--borde,#22304d);background:transparent;color:var(--suave,#7d8ca8);
    font-size:12px;cursor:pointer;padding:0}
  #ia-x:hover{border-color:#f59e0b;color:#f59e0b}
  #ia-log{flex:1;overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:7px}
  #ia-log .m{max-width:90%;padding:7px 10px;border-radius:11px;font:12.5px/1.45 inherit;
    white-space:pre-wrap;word-break:break-word}
  #ia-log .yo{align-self:flex-end;background:#f59e0b;color:#0b1020}
  #ia-log .el{align-self:flex-start;background:var(--panel,#17233a);color:var(--tinta,#c9d5ea);
    border:1px solid var(--borde,#22304d)}
  #ia-log .av{align-self:flex-start;color:var(--suave,#7d8ca8);font-size:11px;padding:0 4px}
  #ia-log table{width:100%;border-collapse:collapse;font:11.5px inherit;margin-top:4px}
  #ia-log td,#ia-log th{padding:2px 4px;border-bottom:1px solid var(--borde,#22304d);text-align:left}
  #ia-log th{color:var(--suave,#7d8ca8);font-weight:600}
  #ia-pie{display:flex;gap:6px;padding:8px;border-top:1px solid var(--borde,#1e2b45);
    background:var(--panel,#0d1526)}
  #ia-q{flex:1;min-width:0;background:var(--fondo,#131c30);border:1px solid var(--borde,#22304d);
    border-radius:9px;padding:9px 11px;color:var(--tinta,#e6edf9);font:13px inherit;outline:none}
  #ia-q:focus{border-color:#f59e0b}
  #ia-pie button{background:var(--panel,#17233a);border:1px solid var(--borde,#22304d);border-radius:9px;
    color:var(--tinta,#c9d5ea);font-size:15px;width:38px;cursor:pointer;flex:0 0 auto}
  #ia-pie button:hover{border-color:#f59e0b;color:#f59e0b}
  #ia-pie button.on{background:#f59e0b;color:#0b1020}
  @media(max-width:720px){
    #ia-caja{right:8px;left:8px;width:auto;bottom:150px;max-height:62vh}
    #ia-btn{right:12px;bottom:150px;width:48px;height:48px}
  }`;

  const $ = (s) => document.querySelector(s);
  // `mapa`, `CAPAS` y `ponerCapa` son binding de script en index.html, no propiedades de window.
  // El visor los expone en window.OpenInfraES.ia; si no está, el chat no toca nada.
  const V = () => (window.OpenInfraES && window.OpenInfraES.ia) || null;

  function monta() {
    const st = document.createElement("style");
    st.textContent = CSS;
    document.head.appendChild(st);

    const btn = document.createElement("button");
    btn.id = "ia-btn";
    btn.type = "button";
    btn.title = "Pregunta al visor";
    btn.textContent = "🗣";
    btn.onclick = () => alterna();

    const caja = document.createElement("div");
    caja.id = "ia-caja";
    caja.innerHTML = `
      <div id="ia-cab">Asistente · OpenInfraES
        <span class="est" id="ia-est">comprobando…</span>
        <button id="ia-x" type="button" title="Minimizar" aria-label="Minimizar">✕</button>
      </div>
      <div id="ia-log"></div>
      <div id="ia-pie">
        <input id="ia-q" type="text" placeholder="Pregunta o pide algo…" autocomplete="off">
        <button id="ia-mic" type="button" title="Hablar">🎙</button>
        <button id="ia-env" type="button" title="Enviar">➤</button>
      </div>`;
    document.body.append(btn, caja);

    $("#ia-env").onclick = () => envia($("#ia-q").value);
    $("#ia-q").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); envia(e.target.value); }
    });
    $("#ia-mic").onclick = alternaVoz;
    $("#ia-x").onclick = () => alterna(false);

    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (p) => { posicion = { lat: p.coords.latitude, lon: p.coords.longitude }; },
        () => {},
        { timeout: 6000, maximumAge: 600000 });
    }
    salud();

    // Sondeo y enlace directo: `?ia=frase` abre el visor y hace la pregunta.
    // El resultado se publica en <html data-ia-*> para poder leerlo con --dump-dom.
    const doc = document.documentElement;
    doc.dataset.iaListo = "1";
    window.addEventListener("error", (e) => {
      doc.dataset.iaError = (e.message || "error").slice(0, 200);
    });
    const q = new URLSearchParams(location.search).get("ia");
    if (q) { alterna(true); setTimeout(() => envia(q), 1200); }
  }

  async function salud() {
    const est = $("#ia-est");
    try {
      const r = await fetch("/api/salud", { cache: "no-store" });
      const d = await r.json();
      est.textContent = d.estado === "ok" ? "servidor ok" : "sin datos";
      est.className = "est " + (d.estado === "ok" ? "ok" : "mal");
    } catch (e) {
      est.textContent = "sin servidor";
      est.className = "est mal";
    }
  }

  function alterna(encender) {
    abierto = encender === undefined ? !abierto : !!encender;
    $("#ia-caja").classList.toggle("on", abierto);
    $("#ia-btn").classList.toggle("on", abierto);
    if (abierto) setTimeout(() => $("#ia-q").focus(), 80);
  }

  function burbuja(texto, quien) {
    const log = $("#ia-log");
    const d = document.createElement("div");
    d.className = "m " + (quien === "yo" ? "yo" : "el");
    d.textContent = texto;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  function tabla(filas) {
    if (!filas || !filas.length) return null;
    const t = document.createElement("table");
    t.innerHTML = "<tr><th>Municipio</th><th>MW</th><th>€/año</th></tr>" +
      filas.slice(0, 8).map((f) => `<tr><td>${f.municipio || "—"}</td>
        <td>${Math.round(f.mw)}</td><td>${f.renta ?? "—"}</td></tr>`).join("");
    return t;
  }

  // ---------------------------------------------------------------- ejecutar
  function capaDe(id) {
    const v = V();
    return v ? v.def(id) : null;
  }

  function encender(id) {
    const v = V();
    if (v) return v.encender(id) === false ? "no se pudo encender " + id : null;
    return "sin puente al mapa";
  }

  function filtrar(a) {
    const c = capaDe(a.id);
    if (!c) return "capa desconocida: " + a.id;
    const valores = Array.isArray(a.valor) ? a.valor : [a.valor];
    const campo = a.campo;
    c.__filtroIa = (f) => valores.indexOf((f.properties || {})[campo]) >= 0;
    c.filtro = c.__filtroIa;
    // si ya estaba cargada con el filtro anterior, se suelta y se vuelve a cargar
    const v = V();
    if (c.__cargada && v) {
      v.apagar(c.id);
      c.__cargada = false;
    }
    return encender(c.id);
  }

  function volar(a) {
    const v = V();
    const mapa = v ? v.mapa() : null;
    if (!mapa || !a.centro) return "sin mapa";
    const [lon, lat] = a.centro;
    const z = a.zoom || 12;
    const quieto = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (quieto || typeof mapa.flyTo !== "function") {
      mapa.setView([lat, lon], z);
    } else {
      mapa.flyTo([lat, lon], z, { duration: 900 });
      // Red de seguridad: si la animación no arranca (pestaña en segundo plano, ahorro de batería),
      // el vuelo se completa de golpe. Sin esto, la orden se pierde sin error.
      setTimeout(() => {
        const c = mapa.getCenter();
        if (Math.abs(c.lat - lat) > 0.01 || Math.abs(c.lng - lon) > 0.01) mapa.setView([lat, lon], z);
      }, 1200);
    }
    if (a.etiqueta && window.L && typeof mapa.openPopup === "function") {
      window.L.popup({ closeButton: false, className: "ia-pin" })
        .setLatLng([lat, lon]).setContent("<b>" + a.etiqueta + "</b>").openOn(mapa);
    }
    return null;
  }

  function ficha(a) {
    const v = V();
    if (!v) return "sin puente al mapa";
    return v.ficha(a.html || "", a.titulo || "") ? null : "sin panel";
  }

  function mezclar(r) {
    // El mapa no repinta polígonos: enciende las plantas filtradas y marca los municipios que
    // encabezan el cruce. La tabla del chat lleva la cifra exacta. (La coropleta completa llega
    // con el motor de teselas.)
    const v = V();
    const mapa = v ? v.mapa() : null;
    const L = window.L;
    r.acciones.filter((a) => a.tipo === "filtrar").forEach(filtrar);
    r.acciones.filter((a) => a.tipo === "capa").forEach((a) => encender(a.id));
    const dg = (k, val) => { document.documentElement.dataset["iaMix" + k] = String(val); };
    dg("Mapa", !!mapa); dg("L", !!L); dg("Top", (r.top || []).length);
    if (!mapa || !L || !r.top) return;
    if (window.__iaMarcas) { window.__iaMarcas.remove(); }
    const g = L.layerGroup().addTo(mapa);
    const max = Math.max.apply(null, r.top.map((t) => t.mw).concat([1]));
    r.top.filter((t) => t.lat && t.lon).forEach((t) => {
      const radio = 8 + 16 * Math.sqrt(t.mw / max);
      L.circleMarker([t.lat, t.lon], {
        radius: radio, color: "#f59e0b", weight: 2, fillColor: "#f59e0b", fillOpacity: 0.18,
      }).bindTooltip(`${t.municipio}<br>${Math.round(t.mw)} MW · ${t.renta} €/año`,
        { permanent: false, direction: "top" }).addTo(g);
    });
    window.__iaMarcas = g;
    dg("Marcas", g.getLayers().length);
    const b = g.getBounds && g.getBounds();
    if (b && b.isValid()) mapa.fitBounds(b.pad(0.25), { animate: false });
  }

  function ejecuta(r) {
    const errores = [];
    const acciones = r.acciones || [];
    acciones.forEach((a) => {
      let e = null;
      if (a.tipo === "volar") e = volar(a);
      else if (a.tipo === "capa") e = encender(a.id);
      else if (a.tipo === "filtrar") e = filtrar(a);
      else if (a.tipo === "ficha") e = ficha(a);
      else if (a.tipo === "marcar") { /* solo para el motor de teselas */ }
      if (e) errores.push(a.tipo + ": " + e);
    });
    if (r.verbo === "mezclar") mezclar(r);
    if (errores.length) console.warn("[ia]", errores.join(" · "));
    document.documentElement.dataset.iaVerbo = r.verbo || "";
    document.documentElement.dataset.iaAcciones = String(acciones.length);
    document.documentElement.dataset.iaTexto = (r.texto || "").slice(0, 300);
    document.documentElement.dataset.iaErrores = errores.join(" | ");
    // En móvil, la ficha (foto de cámara) va al panel grande: se pliega el chat para no taparla.
    // El historial se conserva y se reabre con el botón.
    if (window.innerWidth <= 720 && acciones.some((a) => a.tipo === "ficha")) alterna(false);
    const v = V(), m = v ? v.mapa() : null;
    if (m) {
      // El vuelo es animado: el centro definitivo se publica al terminar (moveend), no al lanzarlo.
      const publica = () => {
        const c = m.getCenter();
        document.documentElement.dataset.iaCentro = c.lat.toFixed(4) + "," + c.lng.toFixed(4);
        document.documentElement.dataset.iaZoom = m.getZoom().toFixed(2);
      };
      publica();
      m.once("moveend", publica);
    }
    const pd = document.getElementById("panel-dato");
    document.documentElement.dataset.iaPanel = pd && !pd.hidden
      ? (document.querySelector("#panel-dato img") ? "imagen" : "texto") : "cerrado";
    return errores;
  }

  async function envia(texto) {
    texto = (texto || "").trim();
    if (!texto) return;
    $("#ia-q").value = "";
    burbuja(texto, "yo");
    const esperando = burbuja("…", "el");
    const cuerpo = { q: texto };
    if (posicion) { cuerpo.lat = posicion.lat; cuerpo.lon = posicion.lon; }
    try {
      const r = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(cuerpo),
      });
      const d = await r.json();
      esperando.remove();
      if (d.error) { burbuja("El asistente no está disponible: " + d.error, "el"); return; }
      const b = burbuja(d.texto || "(sin texto)", "el");
      const t = tabla(d.top);
      if (t) b.appendChild(t);
      if (d.alternativas && d.alternativas.length) {
        const s = document.createElement("div");
        s.className = "av";
        s.textContent = "También: " + d.alternativas.join(" · ");
        $("#ia-log").appendChild(s);
      }
      ejecuta(d);
    } catch (e) {
      esperando.remove();
      burbuja("No hay conexión con el servidor del asistente.", "el");
    }
  }

  function alternaVoz() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    const mic = $("#ia-mic");
    if (!SR) {
      burbuja("Este navegador no dicta. Escribe la pregunta.", "el");
      return;
    }
    if (escuchando) { reconocedor && reconocedor.stop(); return; }
    reconocedor = new SR();
    reconocedor.lang = "es-ES";
    reconocedor.interimResults = false;
    reconocedor.onstart = () => { escuchando = true; mic.classList.add("on"); };
    reconocedor.onend = () => { escuchando = false; mic.classList.remove("on"); };
    reconocedor.onerror = () => { escuchando = false; mic.classList.remove("on"); };
    reconocedor.onresult = (ev) => {
      const t = ev.results[0][0].transcript;
      if (t) envia(t);
    };
    reconocedor.start();
  }

  window.IA = { envia, ejecuta, alterna, acciones: () => (window.__iaAcciones || []) };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", monta);
  } else {
    monta();
  }
})();
