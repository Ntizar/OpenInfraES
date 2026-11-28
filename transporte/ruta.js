// === MODO RUTA =============================================================
// Planificador de viaje sobre los mismos indices que usa el visor. Trabaja con las redes que
// estan en pantalla: se piden las paradas visibles al motor de tiles, se cargan sus ficheros y
// se corre un RAPTOR de 4 rondas en el navegador.
//
// Modelo de frecuencias: la espera al subir es medio intervalo de la linea en ese perfil de dia.
// No hay horas de paso individuales guardadas (serian decenas de millones de numeros).
(function () {
  const VEL = { 0: 20, 900: 20, 1: 32, 2: 55, 3: 14, 4: 26, 7: 18, 200: 60, 704: 20, 715: 18, "-1": 700 };
  const PARADA_S = 40, CAMINA = 1.35, ANTES_VUELO = 45;
  const MAX_R = 4, RADIO = 1100, PIE = 220;

  let activo = false, A = null, B = null, resultados = [], marcadores = [], redActual = null;

  const $ = (s) => document.querySelector(s);
  const hav = (a, b, c, d) => {
    const R = 6371000, p1 = a * Math.PI / 180, p2 = c * Math.PI / 180;
    const x = Math.sin((p2 - p1) / 2) ** 2 +
      Math.cos(p1) * Math.cos(p2) * Math.sin((d - b) * Math.PI / 360) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  };
  const hmm = (t) => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };
  const fmt = (x) => {
    let v = Math.round(x) % 1440; if (v < 0) v += 1440;
    return String(Math.floor(v / 60)).padStart(2, "0") + ":" + String(v % 60).padStart(2, "0");
  };
  const dur = (m) => m >= 60
    ? Math.floor(m / 60) + " h " + String(Math.round(m % 60)).padStart(2, "0")
    : Math.round(m) + " min";

  const css = `
  #btn-ruta{width:100%;margin:8px 0 2px;padding:8px 10px;border-radius:8px;border:1px solid #2a3a5c;
    background:#131c30;color:#e6edf7;font:600 12.5px system-ui;cursor:pointer}
  #btn-ruta.on{background:#f59e0b;color:#0b1020;border-color:#f59e0b}
  @media(max-width:720px){
    /* El mapa ocupa toda la pantalla y el panel flota encima: por eso nunca puede pasar de la
       mitad, o no queda sitio para tocar. Se recoge del todo mientras se eligen los puntos. */
    #panel{max-height:48vh;overflow:auto;transition:max-height .2s}
    #panel.rt-min{max-height:56px;overflow:hidden}
  }
  #panel-ruta{display:none;margin:6px 0 10px;padding:9px;border-radius:9px;background:#0f1729;
    border:1px solid #2a3a5c}
  #panel-ruta .rt-cab{display:flex;justify-content:space-between;align-items:center;font:700 12px system-ui;
    color:#f59e0b;margin-bottom:6px}
  #panel-ruta .rt-cab button{background:none;border:0;color:#93a3c4;font-size:14px;cursor:pointer}
  #panel-ruta .rt-campo{display:flex;gap:6px;align-items:center;margin:4px 0;padding:6px 8px;border-radius:7px;
    background:#131c30;font:12px system-ui;color:#c9d5ea;cursor:pointer;white-space:nowrap;
    overflow:hidden;text-overflow:ellipsis}
  #panel-ruta .rt-campo b{display:inline-block;width:16px;height:16px;border-radius:50%;text-align:center;
    font:700 10px/16px system-ui;color:#0b1020;flex:0 0 auto}
  #panel-ruta #rt-a b{background:#22c55e}
  #panel-ruta #rt-b b{background:#ef4444}
  #panel-ruta .rt-fila{display:flex;gap:5px;margin:7px 0 4px}
  #panel-ruta input[type=time],#panel-ruta select{flex:1;min-width:0;padding:5px;border-radius:6px;
    border:1px solid #2a3a5c;background:#131c30;color:#e6edf7;font:12px system-ui}
  #panel-ruta #rt-ir{flex:0 0 auto;padding:5px 10px;border-radius:6px;border:0;background:#f59e0b;
    color:#0b1020;font:700 12px system-ui;cursor:pointer}
  .rt-modos{display:flex;gap:4px;flex-wrap:wrap;margin:6px 0}
  .rt-modo{flex:1 1 0;min-width:0;padding:6px 4px;border-radius:7px;background:#131c30;
    border:1px solid #22304d;color:#c9d5ea;font:600 11.5px system-ui;cursor:pointer;
    display:flex;flex-direction:column;align-items:center;gap:1px;line-height:1.15}
  .rt-modo small{font:400 9.5px system-ui;color:#7d8ca8}
  .rt-modo:hover{border-color:var(--c)}
  .rt-modo.on{background:var(--c);color:#0b1020;border-color:var(--c)}
  .rt-modo.on small{color:#0b1020;opacity:.75}
  .rt-meta{font:10.5px system-ui;color:#7d8ca8;margin:6px 0 4px}
  .rt-it{padding:7px 8px;margin:5px 0;border-radius:7px;background:#131c30;border:1px solid #22304d;
    cursor:pointer}
  .rt-it:hover{border-color:#f59e0b}
  .rt-tot{font:700 13px system-ui;color:#e6edf7}
  .rt-tot small{font:400 10.5px system-ui;color:#93a3c4;margin-left:6px}
  .rt-lin{margin:3px 0;display:flex;flex-wrap:wrap;gap:3px;align-items:center}
  .rt-l{padding:1px 6px;border-radius:4px;background:#1c2a45;color:#c9d5ea;font:600 10.5px system-ui}
  .rt-sub{font:10px system-ui;color:#7d8ca8}
  .rt-err{font:11px system-ui;color:#fca5a5;padding:6px}
  .rt-cargando{font:11px system-ui;color:#93a3c4;padding:6px}
  `;

  // --- carga de indices de las redes presentes en pantalla ---
  function cidsEnPantalla() {
    const forzados = new URLSearchParams(location.search).get("cids");
    if (forzados) return forzados.split(",");
    const cids = new Set();
    try {
      map.queryRenderedFeatures({ layers: ["stops"] }).forEach((f) => {
        if (f.properties.cid) cids.add(String(f.properties.cid));
      });
    } catch (e) { /* sin mapa */ }
    // A zoom de barrio o de ciudad las paradas aun no existen: se pregunta a las lineas.
    if (!cids.size) {
      try {
        map.querySourceFeatures("lines", { sourceLayer: "lines" }).forEach((f) => {
          if (f.properties.cid) cids.add(String(f.properties.cid));
        });
      } catch (e) { /* sin source */ }
    }
    return [...cids].slice(0, 24);
  }

  // Variantes: lineas/<cid>.json guarda un solo recorrido por linea. Las ramificaciones reales
  // (el C1 que ademas va al T4) estan en variantes/<cid>.json. Si no existe, se sigue con una.
  async function variantesDe(cid) {
    try {
      const r = await fetch("https://ntizar.github.io/gtfs-espana/variantes/" + cid + ".json");
      if (!r.ok) return null;
      return await r.json();
    } catch (e) { return null; }
  }

  async function indices(cids) {
    const par = {}, hor = {}, lin = {}, var_ = {};
    await Promise.all(cids.map(async (cid) => {
      try {
        const [p, h, l, v] = await Promise.all([
          paradasDe(cid), horariosDe(cid), lineasDe(cid), variantesDe(cid)]);
        par[cid] = p; hor[cid] = h; lin[cid] = l; if (v) var_[cid] = v;
      } catch (e) { /* red sin datos */ }
    }));
    return construirGrid({ par, hor, lin, var: var_, cids: Object.keys(par) });
  }

  function serviciosDe(red, cid, sid, dia) {
    const out = {};
    const h = red.hor[cid] && red.hor[cid][sid];
    if (!h) return out;
    for (const L of h) {
      const per = L[2][dia];
      if (per) out[L[0]] = { modo: L[1], n: per[0], ini: hmm(per[1]), fin: hmm(per[2]), iv: per[3] };
    }
    return out;
  }

  // Rejilla espacial: sin ella, cada consulta de "paradas cerca" recorre las ~20.000 paradas
  // de Madrid y el RAPTOR no termina. Celdas de ~550 m.
  const CELL = 0.005;
  function construirGrid(red) {
    red.grid = new Map();
    // indice short -> recorrido, para no recorrer todas las rutas en cada expansion
    red.rec = {};
    for (const cid of red.cids) {
      red.rec[cid] = {};
      const L = red.lin[cid] || {};
      for (const rid in L) red.rec[cid][L[rid][0]] = [L[rid][2]];
      // las variantes (si las hay) sustituyen al recorrido unico
      const V = red.var[cid] || {};
      for (const rid in V) {
        const sh = L[rid] && L[rid][0];
        if (!sh) continue;
        const lista = V[rid].filter((r) => r && r.length >= 2);
        if (lista.length) red.rec[cid][sh] = lista;
      }
    }
    for (const cid of red.cids) {
      const p = red.par[cid] || {};
      for (const sid in p) {
        const [nom, la, lo] = p[sid];
        const k = Math.floor(la / CELL) + "_" + Math.floor(lo / CELL);
        let arr = red.grid.get(k);
        if (!arr) { arr = []; red.grid.set(k, arr); }
        arr.push({ cid, sid, nom, la, lo });
      }
    }
    return red;
  }

  function cercaDe(red, lat, lon, radio) {
    const out = [];
    if (!red.grid) construirGrid(red);
    const dLat = radio / 111000;
    const dLon = radio / (111000 * Math.max(0.2, Math.cos(lat * Math.PI / 180)));
    const i0 = Math.floor((lat - dLat) / CELL), i1 = Math.floor((lat + dLat) / CELL);
    const j0 = Math.floor((lon - dLon) / CELL), j1 = Math.floor((lon + dLon) / CELL);
    for (let i = i0; i <= i1; i++) {
      for (let j = j0; j <= j1; j++) {
        const arr = red.grid.get(i + "_" + j);
        if (!arr) continue;
        for (const o of arr) {
          const d = hav(lat, lon, o.la, o.lo);
          if (d <= radio) out.push({ d, cid: o.cid, sid: o.sid, nom: o.nom, la: o.la, lo: o.lo });
        }
      }
    }
    out.sort((x, y) => x.d - y.d);
    return out;
  }

  function recorridosDe(red, cid, sh) {
    const r = red.rec && red.rec[cid] && red.rec[cid][sh];
    if (!r) return [];
    return Array.isArray(r[0]) ? r : [r];
  }

  function tramoMin(red, cid, rec, i, j, modo) {
    let dist = 0;
    const p = red.par[cid] || {};
    const a = Math.min(i, j), b = Math.max(i, j);
    for (let k = a; k < b; k++) {
      const p1 = p[rec[k]], p2 = p[rec[k + 1]];
      if (p1 && p2) dist += hav(p1[1], p1[2], p2[1], p2[2]);
    }
    return (dist / 1000) / (VEL[modo] || 15) * 60 + (b - a) * PARADA_S / 60;
  }

  // En el centro de una ciudad 1,1 km sobra, pero en un aeropuerto la estacion esta a 2-3 km del
  // punto que tocas. Si no hay nada cerca, se abre el radio antes de rendirse.
  function puntosCerca(red, lat, lon) {
    let c = cercaDe(red, lat, lon, RADIO);
    if (c.length < 3) c = cercaDe(red, lat, lon, 2600);
    return c;
  }

  // Candidatos de origen/destino: las mas cercanas y ademas toda estacion de tren o metro del
  // radio. Sin esto, en un aeropuerto las 120 primeras son paradas de bus y la estacion de
  // Cercanias -que es la que sirve- se queda fuera del corte.
  function candidatos(red, lat, lon) {
    const cerca = puntosCerca(red, lat, lon);
    const out = [], vistos = new Set();
    const add = (x) => {
      const k = x.cid + "|" + x.sid;
      if (!vistos.has(k)) { vistos.add(k); out.push(x); }
    };
    cerca.slice(0, 40).forEach(add);
    for (const x of cerca) {
      if (out.length > 300) break;
      const hs = red.hor[x.cid] && red.hor[x.cid][x.sid];
      if (hs && hs.some((L) => L[1] === 1 || L[1] === 2)) add(x);
    }
    return out;
  }

  // --- RAPTOR sobre frecuencias ---
  function planificar(red, origen, destino, t0, dia) {
    const O = candidatos(red, origen[0], origen[1]).slice(0, 120);
    const D = candidatos(red, destino[0], destino[1]).slice(0, 300);
    if (!O.length || !D.length) return [];

    const mejor = {}, padre = {};
    const clave = (o) => o.cid + "|" + o.sid;
    for (const o of O) {
      const k = clave(o), t = t0 + o.d / CAMINA / 60;
      if (t < (mejor[k] ?? Infinity)) { mejor[k] = t; padre[k] = { tipo: "origen", o }; }
    }

    let frontera = Object.keys(mejor).map((k) => [k, mejor[k]]);
    for (let r = 0; r < MAX_R; r++) {
      const porLinea = new Map();
      for (const [k, t] of frontera) {
        const [cid, sid] = k.split("|");
        const ls = serviciosDe(red, cid, sid, dia);
        for (const sh in ls) {
          const recs = recorridosDe(red, cid, sh);
          for (let vi = 0; vi < recs.length; vi++) {
            const rec = recs[vi];
            const i = rec.indexOf(sid);
            if (i < 0) continue;
            const kk = cid + "|" + sh + "|" + vi;
            const cur = porLinea.get(kk);
            if (!cur || t < cur.t) porLinea.set(kk, { t, i0: i, k, cid, sh, vi, ls: ls[sh], rec });
          }
        }
      }
      const sig = new Map();
      for (const c of porLinea.values()) {
        const espera = Math.max(2, (c.ls.iv || 15) / 2) + (c.ls.modo === -1 ? ANTES_VUELO : 0);
        const salida = c.t + espera;
        if (salida > c.ls.fin) continue;
        for (let j = 0; j < c.rec.length; j++) {
          if (j === c.i0) continue;
          const q = c.cid + "|" + c.rec[j];
          const llegada = salida + tramoMin(red, c.cid, c.rec, c.i0, j, c.ls.modo);
          if (llegada < (mejor[q] ?? Infinity) - 0.01) {
            mejor[q] = llegada;
            padre[q] = { tipo: "linea", sh: c.sh, cid: c.cid, desde: c.k, vi: c.vi,
                         salida, espera, modo: c.ls.modo, iv: c.ls.iv, n: c.ls.n, rec: c.rec };
            sig.set(q, llegada);
          }
        }
      }
      for (const [k, t] of frontera) {
        const [cid, sid] = k.split("|");
        const p = red.par[cid] && red.par[cid][sid];
        if (!p) continue;
        for (const v of cercaDe(red, p[1], p[2], PIE)) {
          if (v.cid === cid && v.sid === sid) continue;
          const t2 = t + v.d / CAMINA / 60;
          const q = clave(v);
          if (t2 < (mejor[q] ?? Infinity) - 0.01) {
            mejor[q] = t2; padre[q] = { tipo: "pie", desde: k }; sig.set(q, t2);
          }
        }
      }
      if (!sig.size) break;
      frontera = [...sig.entries()].sort((a, b) => a[1] - b[1]).slice(0, 6000);
    }

    const res = [];
    for (const d of D) {
      const k = clave(d);
      if (!(k in mejor)) continue;
      const dFin = hav(d.la, d.lo, destino[0], destino[1]);
      const llegada = mejor[k] + dFin / CAMINA / 60;
      if (llegada <= t0) continue;
      const cadena = [];
      let cur = k, guarda = 0;
      while (cur && guarda++ < 14) {
        const p = padre[cur];
        if (!p || p.tipo === "origen") break;
        if (p.tipo === "linea") {
          cadena.push({ sh: p.sh, cid: p.cid, salida: p.salida, llega: mejor[cur],
                        espera: p.espera, modo: p.modo, iv: p.iv, n: p.n,
                        desde: p.desde, hasta: cur, rec: p.rec });
          cur = p.desde;
        } else cur = p.desde;
      }
      cadena.reverse();
      res.push({ total: llegada - t0, llega: llegada, fin: d, cadena,
                 caminata: dFin / CAMINA / 60, caminataIni: O[0].d / CAMINA / 60 });
    }
    return res;
  }

  // --- UI ---
  function pintarPanel() {
    const p = $("#panel-ruta"); if (!p) return;
    p.innerHTML =
      '<div class="rt-cab"><span>🧭 Cómo llegar</span><button id="rt-cerrar" title="Cerrar">✕</button></div>' +
      '<div class="rt-campo" id="rt-a"><b>A</b> ' + (A ? A.nombre : "toca el mapa") + '</div>' +
      '<div class="rt-campo" id="rt-b"><b>B</b> ' + (B ? B.nombre : "toca el mapa") + '</div>' +
      '<div class="rt-fila">' +
        '<input type="time" id="rt-hora" value="08:00">' +
        '<select id="rt-dia"><option value="0">Laborable</option><option value="1">Sábado</option>' +
        '<option value="2">Domingo</option></select>' +
        '<button id="rt-ir">Ruta</button>' +
      '</div><div id="rt-res"></div>';
    $("#rt-cerrar").onclick = () => { activo = false; window.__modoRuta = false; p.style.display = "none";
      limpiarMarcas(); $("#btn-ruta").classList.remove("on"); };
    $("#rt-ir").onclick = calcular;
    $("#rt-a").onclick = () => { A = null; pintarPanel(); recoge(true); };
    $("#rt-b").onclick = () => { B = null; pintarPanel(); recoge(true); };
  }

  // En movil, recoger el panel mientras se elige punto en el mapa.
  function recoge(cerrado) {
    const p = document.getElementById("panel");
    if (!p) return;
    if (window.innerWidth <= 720) p.classList.toggle("rt-min", !!cerrado);
    else p.classList.remove("rt-min");
  }

  function limpiarMarcas() {
    marcadores.forEach((m) => { try { m.remove(); } catch (e) { /* ya fuera */ } });
    marcadores = [];
    if (map.getLayer("ruta-sel")) map.removeLayer("ruta-sel");
    if (map.getSource("ruta-sel")) map.removeSource("ruta-sel");
  }

  function marca(lat, lon, letra, color) {
    const el = document.createElement("div");
    el.textContent = letra;
    el.style.cssText = "width:26px;height:26px;border-radius:50%;background:" + color +
      ";color:#0b1020;font:700 13px/26px system-ui;text-align:center;box-shadow:0 2px 8px #0008;" +
      "border:2px solid #0b1020";
    marcadores.push(new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map));
  }

  function pintarMarcas() {
    if (A) marca(A.lat, A.lon, "A", "#22c55e");
    if (B) marca(B.lat, B.lon, "B", "#ef4444");
  }

  // --- otros modos: motores de rutas por la red viaria (OSRM publico, sin clave ni coste) ---
  const SERV = {
    coche: "https://router.project-osrm.org/route/v1/driving/",
    bici: "https://routing.openstreetmap.de/routed-bike/route/v1/driving/",
    pie: "https://routing.openstreetmap.de/routed-foot/route/v1/driving/"
  };
  const ICONO = { coche: "🚗", bici: "🚲", pie: "🚶", tp: "🚌" };
  const COLOR = { coche: "#3b82f6", bici: "#22c55e", pie: "#a855f7", tp: "#f59e0b" };
  const NOMBRE = { coche: "coche", bici: "bici", pie: "andando", tp: "transporte" };
  let viales = {}, tpMejor = null;

  const durCorto = (m) => m >= 60
    ? Math.floor(m / 60) + "h" + String(Math.round(m % 60)).padStart(2, "0")
    : Math.round(m) + " min";

  async function rutasViales(o, d) {
    const par = o[1] + "," + o[0] + ";" + d[1] + "," + d[0];
    const out = {};
    await Promise.all(Object.keys(SERV).map(async (m) => {
      try {
        const r = await fetch(SERV[m] + par + "?overview=full&geometries=geojson");
        if (!r.ok) return;
        const j = await r.json();
        const rt = j.routes && j.routes[0];
        if (rt) out[m] = { min: rt.duration / 60, km: rt.distance / 1000,
                           geom: rt.geometry.coordinates };
      } catch (e) { /* ese modo no responde, se omite */ }
    }));
    return out;
  }

  function chips() {
    const modos = Object.keys(viales).sort((a, b) => viales[a].min - viales[b].min);
    if (tpMejor) modos.push("tp");
    const ordenados = modos.sort((a, b) => {
      const va = a === "tp" ? tpMejor.total : viales[a].min;
      const vb = b === "tp" ? tpMejor.total : viales[b].min;
      return va - vb;
    });
    return '<div class="rt-modos">' + ordenados.map((m) => {
      const min = m === "tp" ? tpMejor.total : viales[m].min;
      const km = m === "tp" ? "" : " · " + viales[m].km.toFixed(1) + " km";
      return '<button class="rt-modo" data-m="' + m + '" style="--c:' + COLOR[m] + '">' +
        ICONO[m] + " " + durCorto(min) + "<small>" + km + "</small></button>";
    }).join("") + "</div>";
  }

  function dibujarVial(m) {
    limpiarMarcas();
    pintarMarcas();
    const v = viales[m];
    if (!v) return;
    map.addSource("ruta-sel", { type: "geojson",
      data: { type: "Feature", geometry: { type: "LineString", coordinates: v.geom } } });
    map.addLayer({
      id: "ruta-sel", type: "line", source: "ruta-sel",
      paint: { "line-color": COLOR[m], "line-width": 5, "line-opacity": 0.9 },
      layout: { "line-cap": "round", "line-join": "round" }
    }, map.getLayer("stops") ? "stops" : undefined);
    const b = new maplibregl.LngLatBounds();
    v.geom.forEach((c) => b.extend(c));
    encuadrar(b, 15);
  }

  // Encuadre de una ruta. El ancho del panel cambia con la pantalla: con un padding fijo la ruta
  // se sale de la vista en movil, que es justo donde mas se usa.
  function encuadrar(b, maxZoom) {
    const panel = document.getElementById("panel");
    const movil = window.innerWidth <= 720;
    const ancho = panel ? panel.getBoundingClientRect().width : 0;
    map.fitBounds(b, {
      // En movil el panel flota ENCIMA del mapa: el hueco libre empieza en su borde inferior.
      // Con un top fijo la ruta se encuadraba debajo del panel y no se veia.
      padding: movil
        ? { top: Math.round((panel && panel.getBoundingClientRect().height > 60
              ? panel.getBoundingClientRect().bottom : 60)) + 14,
            bottom: 34, left: 16, right: 16 }
        : { top: 100, bottom: 100, left: Math.min(ancho + 40, window.innerWidth * 0.55), right: 70 },
      maxZoom: maxZoom, duration: 700
    });
  }

  async function calcular() {
    const res = $("#rt-res");
    if (!A || !B) { res.innerHTML = '<div class="rt-err">Marca el origen y el destino.</div>'; return; }
    res.innerHTML = '<div class="rt-cargando">Calculando…</div>';
    const t0 = hmm($("#rt-hora").value || "08:00");
    const dia = Number($("#rt-dia").value);

    // los tres modos por carretera van en paralelo con el calculo de transporte
    const promVial = rutasViales([A.lat, A.lon], [B.lat, B.lon]);
    let ms = 0, nredes = 0;
    tpMejor = null;
    resultados = [];

    const cids = cidsEnPantalla();
    if (cids.length) {
      res.innerHTML = '<div class="rt-cargando">Cargando ' + cids.length + ' redes…</div>';
      redActual = await indices(cids);
      nredes = redActual.cids.length;
      const t1 = performance.now();
      const r = planificar(redActual, [A.lat, A.lon], [B.lat, B.lon], t0, dia);
      ms = Math.round(performance.now() - t1);
      const vistas = new Map();
      for (const x of r) {
        const firma = x.cadena.map((c) => c.sh).join(">") || "pie";
        if (!vistas.has(firma) || x.total < vistas.get(firma).total) vistas.set(firma, x);
      }
      resultados = [...vistas.values()].sort((a, b) => a.total - b.total).slice(0, 5);
      resultados.forEach((x) => { x.hora = fmt(x.llega); });
      if (resultados.length) tpMejor = resultados[0];
    }

    viales = await promVial;
    if (!Object.keys(viales).length && !tpMejor) {
      res.innerHTML = '<div class="rt-err">No he podido calcular ninguna ruta. Prueba otra vez.</div>';
      return;
    }

    const meta = (tpMejor ? '<div class="rt-meta">' + nredes + ' redes · ' + ms + ' ms</div>' : "");
    const lista = tpMejor
      ? resultados.map((x, i) => tarjeta(x, i)).join("")
      : '<div class="rt-err">Sin transporte público aquí: el mapa está por encima de la escala de calle.</div>';
    res.innerHTML = chips() + meta + lista;

    res.querySelectorAll(".rt-modo").forEach((el) => {
      el.onclick = () => {
        res.querySelectorAll(".rt-modo").forEach((b) => b.classList.remove("on"));
        el.classList.add("on");
        if (el.dataset.m === "tp") dibujar(resultados[0]); else dibujarVial(el.dataset.m);
      };
    });
    res.querySelectorAll(".rt-it").forEach((el) => {
      el.onclick = () => dibujar(resultados[Number(el.dataset.i)]);
    });

    if (tpMejor) {
      const bt = res.querySelector('.rt-modo[data-m="tp"]');
      if (bt) bt.classList.add("on");
      dibujar(resultados[0]);
    } else {
      const m = Object.keys(viales).sort((a, b) => viales[a].min - viales[b].min)[0];
      dibujarVial(m);
      const b = res.querySelector('.rt-modo[data-m="' + m + '"]');
      if (b) b.classList.add("on");
    }
  }

  function tarjeta(x, i) {
    const lineas = x.cadena.map((c) => '<span class="rt-l">' + c.sh + "</span>").join(" › ");
    const salida = x.cadena.length ? x.cadena[0].salida : x.total;
    return '<div class="rt-it" data-i="' + i + '">' +
      '<div class="rt-tot">' + dur(x.total) + "<small>llega " + x.hora + "</small></div>" +
      '<div class="rt-lin">' + (lineas || "a pie") + "</div>" +
      '<div class="rt-sub">sale ' + fmt(salida) + " · " +
      (x.cadena.length ? x.cadena.length + (x.cadena.length > 1 ? " transbordos" : " línea") : "solo andando") +
      "</div></div>";
  }

  function dibujar(x) {
    limpiarMarcas();
    pintarMarcas();
    if (!redActual) return;
    const tramos = [];
    for (const p of x.cadena) {
      const rec = p.rec;
      if (!rec) continue;
      const i = rec.indexOf(p.desde.split("|")[1]);
      const j = rec.indexOf(p.hasta.split("|")[1]);
      if (i < 0 || j < 0) continue;
      const a = Math.min(i, j), b = Math.max(i, j);
      const pp = redActual.par[p.cid] || {};
      for (let k = a; k <= b; k++) {
        const st = pp[rec[k]];
        if (st) tramos.push([st[2], st[1]]);
      }
    }
    if (!tramos.length) return;
    map.addSource("ruta-sel", {
      type: "geojson",
      data: { type: "Feature", geometry: { type: "LineString", coordinates: tramos }, properties: {} }
    });
    map.addLayer({
      id: "ruta-sel", type: "line", source: "ruta-sel",
      paint: { "line-color": "#f59e0b", "line-width": 5, "line-opacity": 0.95 },
      layout: { "line-cap": "round", "line-join": "round" }
    }, map.getLayer("stops") ? "stops" : undefined);
    // El encuadre incluye los extremos A y B: los tramos de transporte terminan en la estacion y
    // el destino puede estar a 2 km (un aeropuerto), asi que sin ellos la ruta salia cortada.
    const b = new maplibregl.LngLatBounds();
    tramos.forEach((c) => b.extend(c));
    if (A) b.extend([A.lon, A.lat]);
    if (B) b.extend([B.lon, B.lat]);
    encuadrar(b, 14);
  }

  function init() {
    const st = document.createElement("style");
    st.textContent = css;
    document.head.appendChild(st);

    const panelEl = document.createElement("div");
    panelEl.id = "panel-ruta";
    const q = document.getElementById("q");
    q.parentNode.insertBefore(panelEl, q.nextSibling);

    const btn = document.createElement("button");
    btn.id = "btn-ruta";
    btn.textContent = "🧭 Cómo llegar";
    q.parentNode.insertBefore(btn, q.nextSibling);

    btn.onclick = () => {
      activo = !activo;
      window.__modoRuta = activo;
      limpiarMarcas();
      panelEl.style.display = activo ? "block" : "none";
      btn.classList.toggle("on", activo);
      if (activo) { pintarPanel(); if (!A || !B) recoge(true); } else { limpiarMarcas(); recoge(false); }
    };

    map.on("click", (e) => {
      if (!activo) return;
      const { lat, lng } = e.lngLat;
      let nombre = lat.toFixed(5) + ", " + lng.toFixed(5);
      try {
        const f = map.queryRenderedFeatures(e.point, { layers: ["stops"] })[0];
        if (f && f.properties.nombre) nombre = f.properties.nombre;
      } catch (err) { /* sin capa */ }
      const punto = { lat, lon: lng, nombre };
      if (!A) A = punto;
      else if (!B) B = punto;
      else { A = punto; B = null; }
      // Sigue recogido mientras falte un punto: hace falta el mapa entero para tocarlo.
      recoge(!A || !B);
      pintarPanel();
      limpiarMarcas();
      pintarMarcas();
    });
  }

  // Punto de entrada para el chat: fija origen o destino y calcula si ya estan los dos.
  window.__rutaPunto = (lat, lon, nombre, rol) => {
    if (!activo) {
      activo = true;
      window.__modoRuta = true;
      const pel = document.getElementById("panel-ruta");
      if (pel) pel.style.display = "block";
      const b = document.getElementById("btn-ruta");
      if (b) b.classList.add("on");
    }
    const p = { lat: lat, lon: lon, nombre: nombre || (lat.toFixed(5) + ", " + lon.toFixed(5)) };
    if (rol === "B") B = p;
    else if (rol === "A") A = p;
    else if (!A) A = p; else B = p;
    pintarPanel();
    pintarMarcas();
    if (A && B) calcular();
    return { a: !!A, b: !!B };
  };

  window.__dbg = {
    cerca: (lat, lon, r) => cercaDe(redActual, lat, lon, r || RADIO),
    red: () => redActual,
    recs: (cid, sh) => recorridosDe(redActual, cid, sh).map((r) => r.length)
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
