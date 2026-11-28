// Chat de OpenInfraES: preguntar en castellano (escrito o hablado) y que el mapa haga algo.
//
// Reparto de responsabilidades: el navegador NO habla con el modelo ni guarda ninguna clave. Manda
// la pregunta a /api/chat (servidor de OpenInfraES) y recibe una orden ya resuelta con coordenadas
// reales del índice. Si el servidor no está, el chat lo dice y no inventa nada.
(function () {
  "use strict";

  const LOCAL = /^(localhost|127\.0\.0\.1|0\.0\.0\.0)$/.test(location.hostname);
  const BACKEND = LOCAL ? "" : "https://openinfraes-ntizar-ntizar.apps.nan.builders";
  const ICONO = "🗣";

  let posicion = null;   // {lat, lon} del usuario
  let abierto = false;
  let escuchando = false;
  let reconocedor = null;

  const css = `
  #oi-chat-btn{position:fixed;right:16px;bottom:16px;z-index:30;width:52px;height:52px;border-radius:50%;
    border:1px solid #2a3a5c;background:#132038;color:#f59e0b;font-size:22px;cursor:pointer;
    box-shadow:0 6px 20px rgba(0,0,0,.45)}
  #oi-chat-btn:hover{background:#1a2a48}
  #oi-chat{position:fixed;right:16px;bottom:78px;z-index:31;width:min(390px,calc(100vw - 32px));
    max-height:min(62vh,520px);display:none;flex-direction:column;background:#0f1729;
    border:1px solid #2a3a5c;border-radius:14px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.5)}
  #oi-chat.on{display:flex}
  #oi-chat .cab{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid #1e2b45;
    font:700 12.5px system-ui;color:#f59e0b}
  #oi-chat .cab .est{margin-left:auto;font:400 10.5px system-ui;color:#7d8ca8}
  #oi-chat .cab .est.ok{color:#22c55e}
  #oi-log{flex:1;overflow:auto;padding:10px 12px;display:flex;flex-direction:column;gap:7px}
  #oi-log .m{max-width:88%;padding:7px 10px;border-radius:11px;font:12.5px/1.45 system-ui;
    white-space:pre-wrap;word-break:break-word}
  #oi-log .yo{align-self:flex-end;background:#f59e0b;color:#0b1020}
  #oi-log .el{align-self:flex-start;background:#17233a;color:#c9d5ea;border:1px solid #22304d}
  #oi-log .av{align-self:flex-start;background:none;color:#7d8ca8;font-size:11.5px;padding:0 4px}
  #oi-pie{display:flex;gap:6px;padding:8px;border-top:1px solid #1e2b45;background:#0d1526}
  #oi-q{flex:1;min-width:0;background:#131c30;border:1px solid #22304d;border-radius:9px;
    padding:9px 11px;color:#e6edf9;font:13px system-ui;outline:none}
  #oi-q:focus{border-color:#f59e0b}
  #oi-pie button{background:#17233a;border:1px solid #22304d;border-radius:9px;color:#c9d5ea;
    font-size:15px;width:38px;cursor:pointer;flex:0 0 auto}
  #oi-pie button:hover{border-color:#f59e0b;color:#f59e0b}
  #oi-pie button.on{background:#f59e0b;color:#0b1020;border-color:#f59e0b}
  #oi-pie button:disabled{opacity:.4;cursor:default}
  @media(max-width:720px){
    #oi-chat{right:8px;left:8px;width:auto;bottom:74px;max-height:66vh}
    #oi-chat-btn{right:12px;bottom:12px;width:48px;height:48px}
  }`;

  function $(s) { return document.querySelector(s); }

  // --- utilidades de mapas ---
  function ir(lat, lon, zoom, etiqueta) {
    if (!window.__map) return;
    const z = zoom || 14;
    if (etiqueta !== undefined) marcar(lat, lon, etiqueta);
    window.__map.flyTo({ center: [lon, lat], zoom: z, duration: 900 });
  }

  // Punto marcado con una capa GeoJSON, no con maplibregl.Marker: el Marker de esta version de
  // MapLibre revienta con "_getUIString is not a function" al pasarle un elemento propio.
  function marcar(lat, lon, etiqueta) {
    if (!window.__map) return;
    const data = { type: "Feature", geometry: { type: "Point", coordinates: [lon, lat] },
                   properties: { n: etiqueta || "" } };
    const src = window.__map.getSource("oi-punto");
    if (src) { src.setData(data); return; }
    window.__map.addSource("oi-punto", { type: "geojson", data: data });
    window.__map.addLayer({
      id: "oi-punto", type: "circle", source: "oi-punto",
      paint: { "circle-radius": 7, "circle-color": "#f59e0b",
               "circle-stroke-width": 3, "circle-stroke-color": "#0b1020" }
    });
  }

  function capas(lista, texto) {
    if (!Array.isArray(lista) || !lista.length) return "no he reconocido qué capa";
    const grupos = window.GRUPOS || [];
    const pedidos = [];
    lista.forEach((m) => {
      const t = String(m).toLowerCase();
      const g = grupos.find((x) => (x.id + "").toLowerCase().indexOf(t) === 0 ||
                                  (x.n + "").toLowerCase().indexOf(t) >= 0 ||
                                  t.indexOf((x.id + "").toLowerCase()) === 0);
      if (g) pedidos.push(g);
    });
    if (!pedidos.length) return texto || "no encuentro esa capa";
    // «enséñame los trenes» significa ver SOLO los trenes: se deja lo pedido y se quita el resto.
    if (window.modoOn) {
      grupos.forEach((g) => window.modoOn.delete(g.id));
      pedidos.forEach((g) => window.modoOn.add(g.id));
    }
    if (typeof window.aplicar === "function") window.aplicar();
    return "Ahora sólo se ven: " + pedidos.map((g) => g.n || g.id).join(", ");
  }

  // --- conversación ---
  function add(texto, quien) {
    const log = $("#oi-log");
    const d = document.createElement("div");
    d.className = "m " + quien;
    d.textContent = texto;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  function aviso(texto) {
    const log = $("#oi-log");
    const d = document.createElement("div");
    d.className = "m av";
    d.textContent = texto;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
  }

  async function preguntar(texto) {
    if (!texto.trim()) return;
    add(texto, "yo");
    $("#oi-q").value = "";
    aviso("pensando…");
    const log = $("#oi-log");
    try {
      const r = await fetch(BACKEND + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q: texto, lat: posicion ? posicion.lat : null, lon: posicion ? posicion.lon : null }),
      });
      const j = await r.json();
      if (log.lastChild && log.lastChild.className === "m av") log.removeChild(log.lastChild);
      if (j.error) { add(j.error === "falta NAN_API_KEY en el entorno del contenedor"
        ? "El asistente no está configurado en el servidor todavía."
        : "No he podido consultar el asistente: " + j.error, "el"); return; }

      try {
        ejecutar(j);
      } catch (e) {
        add("He entendido «" + (j.lugar || j.accion) + "» pero no he podido mover el mapa: " + e.message, "el");
      }
    } catch (e) {
      if (log.lastChild && log.lastChild.className === "m av") log.removeChild(log.lastChild);
      add("No hay conexión con el asistente (" + e.message + "). El mapa sigue funcionando.", "el");
    }
  }

  function ejecutar(j) {
    const primeros = j.lugares || [];
    if (j.accion === "ir" || j.accion === "ruta") {
      if (!primeros.length) {
        add(j.texto || ("No encuentro «" + (j.lugar || "") + "» en los datos de transporte."), "el");
        return;
      }
      const L = primeros[0];
      if (j.accion === "ir") {
        ir(L.lat, L.lon, L.tipo === "Aéreo" ? 12 : 15, L.nombre);
        add(j.texto ? j.texto + "\n" + L.nombre : "Te llevo a " + L.nombre + ".", "el");
        if (primeros.length > 1) {
          const otros = primeros.slice(1, 4).map((x) => x.nombre).join(" · ");
          if (otros) aviso("también: " + otros);
        }
        return;
      }
      // ruta: el destino es el lugar encontrado; el origen, la ubicación si la hay
      if (typeof window.__rutaPunto === "function") {
        // Sin ubicación el destino va a B y A queda pendiente: al revés el usuario tendría que
        // corregirlo a mano.
        if (posicion) {
          window.__rutaPunto(posicion.lat, posicion.lon, "Mi ubicación", "A");
          window.__rutaPunto(L.lat, L.lon, L.nombre, "B");
        } else {
          window.__rutaPunto(L.lat, L.lon, L.nombre, "B");
        }
        add("Ruta hasta " + L.nombre + (posicion ? " desde tu ubicación." : "."), "el");
        ir(L.lat, L.lon, 12);
        if (!posicion) aviso("pulsa 📍 para usar tu ubicación como origen");
      } else {
        ir(L.lat, L.lon, 13, L.nombre);
        add("Te llevo a " + L.nombre + ": pulsa «Cómo llegar» para la ruta.", "el");
      }
      return;
    }
    if (j.accion === "cerca") {
      if (posicion) {
        ir(posicion.lat, posicion.lon, 15);
        marcar(posicion.lat, posicion.lon, "Tú");
        add(j.texto || "Estás aquí. Mira las paradas a tu alrededor.", "el");
      } else {
        add("Dame tu ubicación con 📍 y te digo qué tienes cerca.", "el");
      }
      return;
    }
    if (j.accion === "capas") {
      const txt = capas(j.capas, j.texto);
      add(txt, "el");
      return;
    }
    add(j.texto || "No te he entendido.", "el");
  }

  // --- ubicación ---
  function ubicacion() {
    if (!navigator.geolocation) { add("Este navegador no da la ubicación.", "el"); return; }
    aviso("pidiendo ubicación…");
    navigator.geolocation.getCurrentPosition(
      (p) => {
        posicion = { lat: p.coords.latitude, lon: p.coords.longitude };
        $("#oi-log").querySelectorAll(".av").forEach((e) => e.remove());
        marcar(posicion.lat, posicion.lon, "Tú");
        ir(posicion.lat, posicion.lon, 15);
        add("Estás aquí. Pregúntame «qué tengo cerca» o «llévame a…».", "el");
        $("#oi-loc").classList.add("on");
      },
      (e) => {
        $("#oi-log").querySelectorAll(".av").forEach((x) => x.remove());
        add(e.code === 1
          ? "No me has dado permiso de ubicación. Actívalo en el navegador y vuelve a pulsar 📍."
          : "No he podido obtener tu ubicación.", "el");
      },
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 }
    );
  }

  // --- voz ---
  function voz() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { add("Este navegador no tiene dictado. Escribe la pregunta.", "el"); return; }
    if (escuchando) { try { reconocedor.stop(); } catch (e) { /* ya parado */ } return; }
    reconocedor = new SR();
    reconocedor.lang = "es-ES";
    reconocedor.interimResults = false;
    reconocedor.maxAlternatives = 1;
    reconocedor.onstart = () => { escuchando = true; $("#oi-mic").classList.add("on"); aviso("escuchando…"); };
    reconocedor.onend = () => { escuchando = false; $("#oi-mic").classList.remove("on"); };
    reconocedor.onerror = (e) => {
      escuchando = false; $("#oi-mic").classList.remove("on");
      if (e.error !== "aborted" && e.error !== "no-speech") add("No te he oído: " + e.error, "el");
    };
    reconocedor.onresult = (ev) => {
      const t = ev.results[0][0].transcript;
      const log = $("#oi-log");
      if (log.lastChild && log.lastChild.className === "m av") log.removeChild(log.lastChild);
      preguntar(t);
    };
    try { reconocedor.start(); } catch (e) { add("No he podido escuchar: " + e.message, "el"); }
  }

  // --- montaje ---
  function montar() {
    const st = document.createElement("style");
    st.textContent = css;
    document.head.appendChild(st);

    const btn = document.createElement("button");
    btn.id = "oi-chat-btn";
    btn.title = "Preguntar al asistente de transporte";
    btn.textContent = ICONO;

    const caja = document.createElement("div");
    caja.id = "oi-chat";
    caja.innerHTML =
      '<div class="cab">Asistente de transporte<span class="est" id="oi-est">comprobando…</span></div>' +
      '<div id="oi-log"></div>' +
      '<div id="oi-pie">' +
        '<input id="oi-q" placeholder="Llévame a Atocha, qué hay cerca…" autocomplete="off">' +
        '<button id="oi-loc" title="Usar mi ubicación">📍</button>' +
        '<button id="oi-mic" title="Hablar">🎤</button>' +
        '<button id="oi-env" title="Enviar">➤</button>' +
      "</div>";

    document.body.appendChild(btn);
    document.body.appendChild(caja);

    btn.onclick = () => {
      abierto = !abierto;
      caja.classList.toggle("on", abierto);
      if (abierto) {
        $("#oi-q").focus();
        if (!$("#oi-log").children.length) {
          aviso("Prueba: «llévame al aeropuerto de Barajas», «qué tengo cerca», «enséñame los trenes».");
        }
      }
    };
    $("#oi-env").onclick = () => preguntar($("#oi-q").value);
    $("#oi-q").onkeydown = (e) => { if (e.key === "Enter") preguntar($("#oi-q").value); };
    $("#oi-loc").onclick = ubicacion;
    $("#oi-mic").onclick = voz;
    if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) {
      $("#oi-mic").disabled = true;
      $("#oi-mic").title = "Este navegador no dicta";
    }

    // estado del servidor: si no hay backend, se avisa en vez de fallar al preguntar
    fetch(BACKEND + "/api/salud").then((r) => r.json()).then((j) => {
      const el = $("#oi-est");
      el.textContent = j.estado === "ok" ? "listo" : "sin servicio";
      el.classList.toggle("ok", j.estado === "ok");
    }).catch(() => {
      const el = $("#oi-est");
      el.textContent = "sin servicio";
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", montar);
  else montar();
})();
